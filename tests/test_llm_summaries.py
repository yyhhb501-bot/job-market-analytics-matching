from __future__ import annotations

from sqlalchemy import select

from apps.api.config import Settings
from apps.api.models import Job
from apps.worker import tasks
from apps.worker.pipeline import persist_job
from packages.job_schema import NormalizedJob
from packages.llm import build_chat_client, build_summary_prompt


class FakeChat:
    async def complete(self, prompt: str) -> str:
        return "LLM generated summary"


def test_build_chat_client_selection():
    assert build_chat_client(Settings(enable_llm_summaries=False)) is None
    assert build_chat_client(Settings(enable_llm_summaries=True, llm_provider="local")) is None
    assert (
        build_chat_client(
            Settings(enable_llm_summaries=True, llm_provider="openai", llm_api_key="key")
        )
        is not None
    )


def test_build_summary_prompt_truncates():
    prompt = build_summary_prompt("Data Engineer", "x" * 100, max_chars=10)
    assert "Data Engineer" in prompt
    assert "x" * 100 not in prompt


def test_generate_summaries_sync(session_factory, session, monkeypatch):
    persist_job(
        session,
        NormalizedJob(
            source="test",
            source_job_id="llm-1",
            title="Data Engineer",
            company="Acme",
            description="Python AWS pipelines",
            city="Austin",
            country="US",
        ),
    )
    session.commit()

    monkeypatch.setattr(tasks, "get_session_factory", lambda: session_factory)
    monkeypatch.setattr(
        tasks,
        "get_settings",
        lambda: Settings(
            enable_llm_summaries=True,
            llm_provider="openai",
            llm_api_key="key",
            llm_summary_max_chars=1000,
        ),
    )
    monkeypatch.setattr(tasks, "build_chat_client", lambda settings: FakeChat())

    result = tasks.generate_summaries_sync(batch_size=10)
    assert result["summarized"] == 1

    session.expire_all()
    job = session.scalars(select(Job)).one()
    assert job.summary == "LLM generated summary"
    assert job.summary_source == "llm"


def test_generate_summaries_skipped_without_client(session_factory, session, monkeypatch):
    monkeypatch.setattr(tasks, "get_session_factory", lambda: session_factory)
    monkeypatch.setattr(tasks, "get_settings", lambda: Settings(enable_llm_summaries=False))
    result = tasks.generate_summaries_sync(batch_size=10)
    assert result == {"summarized": 0, "skipped": "llm summaries disabled"}
