"""Tests for the collection-control contract.

Covers the user-facing guarantees: a normal response persists without the
response hook exploding; network failures classify as retryable (Celery
retries them); access blocks pause the source instead of retrying; a failing
board can never age out jobs; visit/time budgets stop runs cleanly; a run
mutex keeps duplicate dispatches from collecting the same source.
"""

from __future__ import annotations

import asyncio
import datetime as dt

import httpx
import pytest
from sqlalchemy import select

from apps.api.config import Settings
from apps.api.models import Board, CollectorRun, Job, SourceControl, utcnow
from apps.worker import pipeline, tasks
from apps.worker.pipeline import persist_job_row
from collectors.base import (
    AccessBlockedError,
    BaseCollector,
    RateLimitedError,
    RetryableCollectorError,
    SearchParams,
    classify_exception,
    parse_retry_after,
)
from collectors.seek_adapter.adapter import SeekCollector
from packages.job_schema import NormalizedJob


def make_job(**overrides) -> NormalizedJob:
    data = {
        "source": "greenhouse",
        "source_job_id": "c-1",
        "title": "Senior Data Engineer",
        "company": "Acme, Inc.",
        "description": "Build pipelines with Python and Spark.",
        "city": "Austin",
        "country": "US",
        "apply_url": "https://example.com/jobs/42",
    }
    data.update(overrides)
    return NormalizedJob(**data)


def make_collector(name: str, settings: Settings, *, jobs=(), exc=None) -> BaseCollector:
    scripted_jobs = list(jobs)
    scripted_exc = exc

    class ScriptedCollector(BaseCollector):
        async def stream(self, params):
            for job in scripted_jobs:
                yield job
            if scripted_exc is not None:
                raise scripted_exc

    ScriptedCollector.name = name
    return ScriptedCollector(settings)


def run_async(collector, session_factory):
    return asyncio.run(pipeline.run_collector(collector, SearchParams(), session_factory))


# ---------------------------------------------------------------------------
# HTTP client contract
# ---------------------------------------------------------------------------


def test_async_response_hook_does_not_break_normal_responses():
    """Regression: a sync hook on the async client raised on every response."""
    collector = SeekCollector(Settings())

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    async def main() -> httpx.Response:
        async with collector._client(transport=httpx.MockTransport(handler)) as client:
            return await client.get("https://www.seek.com.au/api/test")

    response = asyncio.run(main())
    assert response.status_code == 200


def test_raise_for_status_classifies_429_with_retry_after():
    collector = SeekCollector(Settings())
    request = httpx.Request("GET", "https://example.com/")
    response = httpx.Response(429, headers={"Retry-After": "7"}, request=request)
    with pytest.raises(RateLimitedError) as excinfo:
        collector._raise_for_status(response)
    assert excinfo.value.retry_after == 7.0


def test_raise_for_status_classifies_403_as_blocked():
    collector = SeekCollector(Settings())
    request = httpx.Request("GET", "https://example.com/")
    response = httpx.Response(403, request=request)
    with pytest.raises(AccessBlockedError):
        collector._raise_for_status(response)


def test_classify_exception_outcomes():
    assert classify_exception(httpx.ConnectError("boom")) == ("retryable", None)
    assert classify_exception(httpx.ReadTimeout("slow")) == ("retryable", None)
    request = httpx.Request("GET", "https://x/")
    blocked = classify_exception(
        httpx.HTTPStatusError("403", request=request, response=httpx.Response(403, request=request))
    )
    assert blocked == ("blocked", None)
    assert classify_exception(RateLimitedError("429", retry_after=5)) == ("retryable", 5.0)


def test_parse_retry_after_formats():
    assert parse_retry_after("120") == 120.0
    assert parse_retry_after("garbage") is None
    assert parse_retry_after(None) is None
    http_date = dt.datetime.now(dt.UTC).strftime("%a, %d %b %Y %H:%M:%S GMT")
    assert parse_retry_after(http_date) is not None


# ---------------------------------------------------------------------------
# Retry decisions
# ---------------------------------------------------------------------------


def test_retry_decision_blocked_never_retries():
    should, countdown = tasks.retry_decision(AccessBlockedError("captcha"), 0)
    assert should is False
    assert countdown == 0.0


def test_retry_decision_rate_limit_waits_retry_after():
    should, countdown = tasks.retry_decision(RateLimitedError("429", retry_after=45), 0)
    assert should is True
    assert countdown == 45.0


def test_retry_decision_transient_uses_backoff_and_cap():
    should, countdown = tasks.retry_decision(RetryableCollectorError("network"), 0)
    assert should is True
    assert 60 <= countdown <= 90 + 30

    should, _ = tasks.retry_decision(RetryableCollectorError("network"), 99)
    assert should is False


def test_clamp_to_daily_target(session):
    persist_job_row(session, make_job(source="seek", source_job_id="s1", title="Role One"))
    session.commit()
    settings = Settings(seek_daily_new_target=3)
    assert tasks.clamp_to_daily_target(session, settings, "seek", 100) == 2

    persist_job_row(session, make_job(source="seek", source_job_id="s2", title="Role Two"))
    persist_job_row(session, make_job(source="seek", source_job_id="s3", title="Role Three"))
    session.commit()
    assert tasks.clamp_to_daily_target(session, settings, "seek", 100) == 0
    # Sources without a configured target are not capped.
    assert tasks.clamp_to_daily_target(session, settings, "greenhouse", 100) == 100


def test_collect_source_sync_skips_when_daily_target_met(
    session_factory, session, monkeypatch
):
    monkeypatch.setattr(tasks, "build_collectors", lambda settings: [SeekCollector(Settings())])
    monkeypatch.setattr(tasks, "get_settings", lambda: Settings(seek_daily_new_target=1))
    monkeypatch.setattr(tasks, "get_session_factory", lambda: session_factory)
    persist_job_row(session, make_job(source="seek", source_job_id="s1", title="Role One"))
    session.commit()

    result = tasks.collect_source_sync("seek", {"results_wanted": 10})
    assert result["skipped"] is True
    assert result["reason"] == "daily new-job target met"


# ---------------------------------------------------------------------------
# Pipeline gates: mutex, pause, budgets, outcomes
# ---------------------------------------------------------------------------


def test_run_skipped_when_same_source_already_running(session_factory, session, monkeypatch):
    monkeypatch.setattr(pipeline, "get_settings", lambda: Settings())
    monkeypatch.setattr(pipeline, "load_runtime_boards", lambda session: {})
    session.add(CollectorRun(source="greenhouse", status="running", started_at=utcnow()))
    session.commit()

    stats = run_async(
        make_collector("greenhouse", Settings(), jobs=[make_job()]), session_factory
    )
    assert stats.outcome == "skipped"
    assert stats.stopped_reason == "already_running"
    assert stats.seen == 0


def test_stale_running_run_does_not_block(session_factory, session, monkeypatch):
    monkeypatch.setattr(pipeline, "get_settings", lambda: Settings())
    monkeypatch.setattr(pipeline, "load_runtime_boards", lambda session: {})
    stale = utcnow() - dt.timedelta(days=1)
    session.add(CollectorRun(source="greenhouse", status="running", started_at=stale))
    session.commit()

    stats = run_async(
        make_collector("greenhouse", Settings(), jobs=[make_job()]), session_factory
    )
    assert stats.outcome == "success"
    assert stats.inserted == 1


def test_paused_source_collects_nothing(session_factory, session, monkeypatch):
    monkeypatch.setattr(pipeline, "get_settings", lambda: Settings())
    monkeypatch.setattr(pipeline, "load_runtime_boards", lambda session: {})
    session.add(SourceControl(source="greenhouse", paused=True, pause_reason="challenge"))
    session.commit()

    stats = run_async(
        make_collector("greenhouse", Settings(), jobs=[make_job()]), session_factory
    )
    assert stats.outcome == "paused"
    assert stats.seen == 0

    # Resuming clears the gate and collection proceeds.
    with session_factory() as s:
        assert pipeline.resume_source(s, "greenhouse") is True
    stats = run_async(
        make_collector("greenhouse", Settings(), jobs=[make_job()]), session_factory
    )
    assert stats.outcome == "success"
    assert stats.inserted == 1


def test_access_block_pauses_source_and_does_not_raise(session_factory, monkeypatch):
    monkeypatch.setattr(
        pipeline, "get_settings", lambda: Settings(pause_on_challenge=True)
    )
    monkeypatch.setattr(pipeline, "load_runtime_boards", lambda session: {})

    stats = run_async(
        make_collector("greenhouse", Settings(), exc=AccessBlockedError("captcha")),
        session_factory,
    )
    assert stats.outcome == "blocked"

    with session_factory() as session:
        control = session.scalar(
            select(SourceControl).where(SourceControl.source == "greenhouse")
        )
        assert control is not None
        assert control.paused is True
        assert control.pause_reason == "challenge"


def test_retryable_failure_raises_for_the_task_layer(session_factory, monkeypatch):
    monkeypatch.setattr(pipeline, "get_settings", lambda: Settings())
    monkeypatch.setattr(pipeline, "load_runtime_boards", lambda session: {})

    with pytest.raises(RetryableCollectorError):
        run_async(
            make_collector("greenhouse", Settings(), exc=httpx.ConnectError("boom")),
            session_factory,
        )

    with session_factory() as session:
        run = session.scalars(
            select(CollectorRun).where(CollectorRun.source == "greenhouse")
        ).one()
        assert run.status == "retryable"
        assert run.error


def test_all_boards_failing_is_retryable_not_success(session_factory, monkeypatch):
    """A run where every board failed must not look like a success."""
    monkeypatch.setattr(
        pipeline,
        "get_settings",
        lambda: Settings(board_sweep_enabled=True, missing_run_threshold=1),
    )
    monkeypatch.setattr(pipeline, "load_runtime_boards", lambda session: {})
    collector = make_collector("greenhouse", Settings())
    collector.board_outcomes["acme"] = False
    collector.board_errors["acme"] = "ConnectError: boom"

    with pytest.raises(RetryableCollectorError):
        run_async(collector, session_factory)


def test_time_budget_stops_the_run(session_factory, monkeypatch):
    monkeypatch.setattr(pipeline, "get_settings", lambda: Settings(max_run_minutes=1))

    class FakeTime:
        """Only pipeline's own time.monotonic calls go through here.

        Call 1 computes the deadline; later calls (the in-loop stop checks)
        jump past it. asyncio keeps using the real stdlib time module.
        """

        def __init__(self) -> None:
            self.calls = 0

        def monotonic(self) -> float:
            self.calls += 1
            return 1000.0 if self.calls == 1 else 2000.0

    monkeypatch.setattr(pipeline, "time", FakeTime())
    monkeypatch.setattr(pipeline, "load_runtime_boards", lambda session: {})

    stats = run_async(
        make_collector("greenhouse", Settings(), jobs=[make_job()]), session_factory
    )
    assert stats.outcome == "partial"
    assert stats.stopped_reason == "time_budget"


def test_visit_budget_stops_the_run(session_factory, monkeypatch):
    settings = Settings(daily_page_visit_limit=2)
    monkeypatch.setattr(pipeline, "get_settings", lambda: settings)
    monkeypatch.setattr(pipeline, "load_runtime_boards", lambda session: {})

    class BudgetedCollector(BaseCollector):
        name = "seek"

        def __init__(self, settings_):
            super().__init__(settings_)
            self.counter = 0

        async def stream(self, params):
            while True:
                if not await self._pre_request():
                    return
                await self.budget.record_page()
                self.counter += 1
                yield make_job(
                    source="seek",
                    source_job_id=f"b-{self.counter}",
                    title=f"Role {self.counter}",
                    apply_url=f"https://example.com/jobs/{self.counter}",
                )

    stats = run_async(BudgetedCollector(settings), session_factory)
    assert stats.pages_visited == 2
    assert stats.stopped_reason == "visit_budget"
    assert stats.outcome == "partial"
    assert stats.inserted == 2


# ---------------------------------------------------------------------------
# Per-board missing sweep: a failing board can never age out jobs
# ---------------------------------------------------------------------------


def test_failed_board_never_ages_out_its_jobs(session_factory, session, monkeypatch):
    monkeypatch.setattr(
        pipeline,
        "get_settings",
        lambda: Settings(board_sweep_enabled=True, missing_run_threshold=1),
    )
    healthy = Board(provider="greenhouse", board_token="healthy")
    broken = Board(provider="greenhouse", board_token="broken")
    session.add_all([healthy, broken])
    session.commit()
    # Give the pre-existing jobs a historical run so the collector's new run
    # gets a fresh run id.
    session.add(CollectorRun(source="greenhouse", status="success", started_at=utcnow()))
    session.commit()

    seen_job = persist_job_row(
        session,
        make_job(source_job_id="h-1", title="Healthy Role"),
        run_id=1,
        source_board_id=healthy.id,
    )[1].id
    gone_job = persist_job_row(
        session,
        make_job(source_job_id="g-1", title="Gone Role"),
        run_id=1,
        source_board_id=healthy.id,
    )[1].id
    protected_job = persist_job_row(
        session,
        make_job(source_job_id="b-1", title="Protected Role"),
        run_id=1,
        source_board_id=broken.id,
    )[1].id
    session.commit()

    # Only "h-1" is re-seen this run; "g-1" stays behind on a completed board.
    jobs = [make_job(source_job_id="h-1", title="Healthy Role")]
    collector = make_collector("greenhouse", Settings(), jobs=jobs)
    collector.board_outcomes["healthy"] = True
    collector.complete_boards.add("healthy")
    collector._note_board_failure("broken", httpx.ConnectError("boom"))
    monkeypatch.setattr(
        pipeline,
        "load_runtime_boards",
        lambda session: {
            "greenhouse": [
                {"token": "healthy", "board_id": healthy.id},
                {"token": "broken", "board_id": broken.id},
            ]
        },
    )

    stats = run_async(collector, session_factory)
    assert stats.outcome == "partial"  # one board failed

    with session_factory() as s:
        # "h-1" was re-seen this run -> stays active.
        assert s.get(Job, seen_job).is_active is True
        # "g-1" was not re-seen and its board completed (threshold=1)
        # -> legitimately closed.
        assert s.get(Job, gone_job).is_active is False
        # The broken board's jobs are untouched, no matter how often it fails.
        broken_row = s.get(Job, protected_job)
        assert broken_row.is_active is True
        assert broken_row.missing_runs == 0


# ---------------------------------------------------------------------------
# Collector controls API
# ---------------------------------------------------------------------------


def test_collector_status_endpoint(client):
    response = client.get("/api/v1/collector/status")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"weekly", "sources"}
    assert "target" in body["weekly"]


def test_pause_and_resume_endpoints(client, session):
    paused = client.post("/api/v1/collector/greenhouse/pause", json={"reason": "manual"})
    assert paused.status_code == 200
    assert paused.json()["paused"] is True

    status = client.get("/api/v1/collector/status").json()
    row = next(item for item in status["sources"] if item["source"] == "greenhouse")
    assert row["paused"] is True

    resumed = client.post("/api/v1/collector/greenhouse/resume")
    assert resumed.status_code == 200
    again = client.post("/api/v1/collector/greenhouse/resume")
    assert again.status_code == 409


# ---------------------------------------------------------------------------
# Dispatch grouping: same-source specs must run serially (run mutex would
# otherwise skip the later keyword/country expansions of a search source).
# ---------------------------------------------------------------------------


def test_group_specs_by_source_serializes_same_source():
    specs = [
        ("jobspy", {"keywords": "nurse", "country": "US"}),
        ("greenhouse", {"keywords": None}),
        ("jobspy", {"keywords": "nurse", "country": "AU"}),
        ("jobspy", {"keywords": "teacher", "country": "US"}),
    ]
    groups = tasks.group_specs_by_source(specs)
    assert len(groups) == 2
    by_name = {group[0][0]: group for group in groups}
    assert [spec["country"] for _, spec in by_name["jobspy"]] == ["US", "AU", "US"]
    assert len(by_name["greenhouse"]) == 1


def test_dispatch_header_runs_same_source_serially():
    specs = [
        ("jobspy", {"keywords": "nurse"}),
        ("jobspy", {"keywords": "teacher"}),
        ("greenhouse", {"keywords": None}),
    ]
    header = tasks._dispatch_header(specs)
    # One entry per source: jobspy's two specs are a single serial chain.
    assert len(header) == 2


def test_daily_target_met_records_skipped_run(session_factory, session, monkeypatch):
    monkeypatch.setattr(tasks, "build_collectors", lambda settings: [SeekCollector(Settings())])
    monkeypatch.setattr(tasks, "get_settings", lambda: Settings(seek_daily_new_target=1))
    monkeypatch.setattr(tasks, "get_session_factory", lambda: session_factory)
    persist_job_row(session, make_job(source="seek", source_job_id="s1", title="Role One"))
    session.commit()

    result = tasks.collect_source_sync("seek", {"results_wanted": 10})
    assert result["skipped"] is True

    with session_factory() as s:
        run = s.scalar(
            select(CollectorRun).where(
                CollectorRun.source == "seek", CollectorRun.status == "skipped"
            )
        )
        assert run is not None
        assert run.stopped_reason == "daily_target_met"


def test_dispatch_header_chains_execute_with_intact_arguments(monkeypatch):
    """Regression: a Celery chain prepends the previous task's result to the
    next call, so same-source serial chains must use immutable signatures.
    This test actually executes the header in eager mode."""
    from apps.worker.celery_app import celery_app

    calls: list[tuple[str, dict | None]] = []

    def fake_sync(name, params=None):
        calls.append((name, params))
        return {"source": name}

    monkeypatch.setattr(tasks, "collect_source_sync", fake_sync)
    monkeypatch.setattr(celery_app.conf, "task_always_eager", True, raising=False)
    monkeypatch.setattr(celery_app.conf, "task_eager_propagates", True, raising=False)
    try:
        header = tasks._dispatch_header(
            [
                ("jobspy", {"keywords": "nurse"}),
                ("jobspy", {"keywords": "teacher"}),
                ("greenhouse", {}),
            ]
        )
        for signature in header:
            signature.apply()
    finally:
        monkeypatch.undo()

    assert calls == [
        ("jobspy", {"keywords": "nurse"}),
        ("jobspy", {"keywords": "teacher"}),
        ("greenhouse", {}),
    ]
