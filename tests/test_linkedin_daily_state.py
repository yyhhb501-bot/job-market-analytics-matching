"""Tests for the LinkedIn daily runner's schedule state machine.

Guarantees: a failed day keeps its checkpoint and retries with backoff
(attempts are recorded separately from successes); a challenge/login pause
blocks auto-retry until a manual run succeeds; the success marker is only
written on success.
"""

from __future__ import annotations

import datetime as dt

import pytest

from clients.linkedin_daily import schedule_state


def make_state(**overrides) -> schedule_state.CollectState:
    state = schedule_state.CollectState()
    for key, value in overrides.items():
        setattr(state, key, value)
    return state


def test_first_attempt_of_the_day_runs():
    state = make_state(day="2026-09-21", attempts=0)
    allowed, _ = schedule_state.should_run(
        state, dt.datetime(2026, 9, 22, 8, 0, tzinfo=dt.UTC)
    )
    assert allowed is True


def test_failed_day_is_retried_after_backoff_not_lost():
    """The old bug: the success marker was written even on failure, so a
    failed day never resumed. Now attempts are tracked separately."""
    state = make_state(
        day="2026-09-22",
        attempts=1,
        last_attempt_at="2026-09-22T08:00:00+00:00",
        last_error="ConnectError: boom",
    )
    now = dt.datetime(2026, 9, 22, 8, 5, tzinfo=dt.UTC)
    allowed, reason = schedule_state.should_run(state, now)
    assert allowed is False
    assert "backing off" in reason

    # After the 30-minute backoff the run resumes from its checkpoint.
    later = dt.datetime(2026, 9, 22, 8, 31, tzinfo=dt.UTC)
    allowed, reason = schedule_state.should_run(state, later)
    assert allowed is True
    assert "retry attempt 2" in reason


def test_max_attempts_reached_for_the_day():
    state = make_state(day="2026-09-22", attempts=3)
    allowed, reason = schedule_state.should_run(
        state, dt.datetime(2026, 9, 22, 18, 0, tzinfo=dt.UTC)
    )
    assert allowed is False
    assert "max attempts" in reason


def test_new_day_resets_attempts_but_not_challenge_pause():
    state = make_state(day="2026-09-22", attempts=3, paused_reason="challenge")
    schedule_state.reset_attempts_for_today(state, "2026-09-23")
    assert state.attempts == 0
    assert state.paused_reason == "challenge"

    allowed, reason = schedule_state.should_run(
        state, dt.datetime(2026, 9, 23, 8, 0, tzinfo=dt.UTC)
    )
    assert allowed is False
    assert "paused" in reason


def test_challenge_pause_only_cleared_by_success():
    now = dt.datetime(2026, 9, 22, 9, 0, tzinfo=dt.UTC)
    state = make_state(day="2026-09-22", attempts=1, paused_reason="")
    schedule_state.record_failure(
        state, now, "LOGIN_REQUIRED: run login and complete sign-in at localhost:7900"
    )
    assert state.paused_reason == "challenge"

    # Non-challenge failures pause nothing.
    other = make_state(day="2026-09-22", attempts=1)
    schedule_state.record_failure(other, now, "TimeoutError: slow")
    assert other.paused_reason == ""

    # A successful manual run clears the pause.
    schedule_state.record_success(state, now)
    assert state.paused_reason == ""
    allowed, _ = schedule_state.should_run(state, now)
    assert allowed is True


def test_success_marker_only_written_on_success():
    state = make_state(day="2026-09-22", attempts=2, last_error="boom")
    schedule_state.record_failure(state, dt.datetime(2026, 9, 22, 9, 0, tzinfo=dt.UTC), "boom")
    assert state.last_success_date == ""

    schedule_state.record_success(state, dt.datetime(2026, 9, 22, 10, 0, tzinfo=dt.UTC))
    assert state.last_success_date == "2026-09-22"
    assert state.attempts == 0
    assert state.last_error == ""


def test_state_persists_roundtrip(tmp_path):
    state = make_state(
        day="2026-09-22",
        attempts=2,
        last_attempt_at="2026-09-22T08:00:00+00:00",
        paused_reason="challenge",
        last_error="LOGIN_REQUIRED: x",
    )
    schedule_state.save_state(tmp_path, state)
    loaded = schedule_state.load_state(tmp_path)
    assert loaded.day == "2026-09-22"
    assert loaded.attempts == 2
    assert loaded.paused_reason == "challenge"
    assert loaded.last_attempt_at == "2026-09-22T08:00:00+00:00"


# ---------------------------------------------------------------------------
# scheduled_cycle: the runner's shared-state contract (regression tests for
# the stale-state overwrite bug where a run's success/pause was erased by the
# schedule loop saving an older copy).
# ---------------------------------------------------------------------------

# Mirror the runner: now_local comes from ZoneInfo (aware), now_utc aware.
_TZ = dt.timezone(dt.timedelta(hours=8))
NOW_LOCAL = dt.datetime(2026, 9, 22, 8, 0, tzinfo=_TZ)
NOW_UTC = dt.datetime(2026, 9, 22, 8, 0, tzinfo=dt.UTC)
CYCLE = {"start_hour": 8, "start_minute": 0, "now_local": NOW_LOCAL, "now_utc": NOW_UTC}


def test_cycle_success_writes_marker_and_stops_for_the_day(tmp_path):
    state = make_state(day="2026-09-21")

    def run_fn(shared):
        assert shared is state, "run must operate on the caller's state object"
        schedule_state.record_success(shared, NOW_UTC)

    ran, reason = schedule_state.scheduled_cycle(state, run_fn=run_fn, **CYCLE)
    assert ran is True
    assert state.last_success_date == "2026-09-22"
    schedule_state.save_state(tmp_path, state)

    # Reloading from disk (what the schedule loop does each tick) and running
    # the next tick must NOT re-run on the same day.
    reloaded = schedule_state.load_state(tmp_path)
    ran_again, reason_again = schedule_state.scheduled_cycle(
        reloaded, run_fn=run_fn, **CYCLE
    )
    assert ran_again is False
    assert reason_again == "already succeeded today"


def test_cycle_challenge_pause_survives_the_loop(tmp_path):
    state = schedule_state.CollectState()

    def run_fn(shared):
        schedule_state.record_failure(
            shared, NOW_UTC, "LOGIN_REQUIRED: run login and complete sign-in"
        )
        raise RuntimeError("LOGIN_REQUIRED: run login and complete sign-in")

    with pytest.raises(RuntimeError):
        schedule_state.scheduled_cycle(state, run_fn=run_fn, **CYCLE)

    # The schedule loop persists the shared state even after a failure.
    schedule_state.save_state(tmp_path, state)
    reloaded = schedule_state.load_state(tmp_path)
    assert reloaded.paused_reason == "challenge"

    # Held: the login wall is never auto-retried.
    allowed, reason = schedule_state.should_run(
        reloaded, NOW_LOCAL + dt.timedelta(hours=2)
    )
    assert allowed is False
    assert "paused" in reason


def test_cycle_records_attempt_before_running(tmp_path):
    state = schedule_state.CollectState()

    def run_fn(_shared):
        raise RuntimeError("crash before recording anything")

    with pytest.raises(RuntimeError):
        schedule_state.scheduled_cycle(state, run_fn=run_fn, **CYCLE)

    schedule_state.save_state(tmp_path, state)
    reloaded = schedule_state.load_state(tmp_path)
    # The attempt was persisted up-front, so a crash cannot loop tightly.
    assert reloaded.attempts == 1
    assert reloaded.last_attempt_at
    allowed, reason = schedule_state.should_run(
        reloaded, NOW_LOCAL + dt.timedelta(minutes=1)
    )
    assert allowed is False
    assert "backing off" in reason


def test_cycle_not_due_before_start_time():
    state = schedule_state.CollectState()
    early = dict(CYCLE)
    early["now_local"] = NOW_LOCAL - dt.timedelta(minutes=1)
    early["now_utc"] = NOW_UTC - dt.timedelta(minutes=1)
    ran, reason = schedule_state.scheduled_cycle(state, run_fn=lambda s: None, **early)
    assert ran is False
    assert reason == "not due yet"
    assert state.attempts == 0
