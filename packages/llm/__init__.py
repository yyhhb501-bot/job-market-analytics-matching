"""Minimal OpenAI-compatible chat client used for LLM-generated summaries.

Enabled only when ``ENABLE_LLM_SUMMARIES=true`` and an ``LLM_API_KEY`` is set;
otherwise enrichment keeps the deterministic extractive summary.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

import httpx

logger = logging.getLogger("jobagg.llm")

DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_BASE_URL = "https://api.openai.com/v1"


class ChatClient(Protocol):
    async def complete(self, prompt: str) -> str: ...


class OpenAIChatClient:
    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def complete(self, prompt: str) -> str:
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "max_tokens": 220,
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
            response.raise_for_status()
            choices = response.json().get("choices") or []
        if not choices:
            return ""
        return str((choices[0].get("message") or {}).get("content") or "").strip()


def build_chat_client(settings: Any) -> ChatClient | None:
    if not getattr(settings, "enable_llm_summaries", False):
        return None
    provider = str(getattr(settings, "llm_provider", "local") or "local").lower()
    api_key = getattr(settings, "llm_api_key", None)
    if provider in {"openai", "auto"} and api_key:
        return OpenAIChatClient(
            api_key,
            model=getattr(settings, "llm_summary_model", DEFAULT_MODEL),
            base_url=getattr(settings, "llm_base_url", DEFAULT_BASE_URL),
            timeout=float(getattr(settings, "llm_timeout_seconds", 30.0)),
        )
    return None


def build_summary_prompt(title: str | None, description: str | None, max_chars: int = 6000) -> str:
    body = (description or "")[:max_chars]
    return (
        "Summarize this job posting in 2-3 concise sentences for a job seeker. "
        "Focus on the role, key responsibilities and required skills. No preamble.\n\n"
        f"Title: {title or ''}\n\n{body}"
    )


__all__ = [
    "ChatClient",
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "OpenAIChatClient",
    "build_chat_client",
    "build_summary_prompt",
]
