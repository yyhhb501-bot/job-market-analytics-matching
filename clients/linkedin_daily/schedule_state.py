"""Run-state machine for the daily LinkedIn collection loop.

Kept free of Selenium imports so it is unit-testable. The runner persists one
``collect-state.json`` recording:

- ``last_success_date`` — the last day a run completed (the old schedule
  marker; only written on success, so a failed day can resume);
- ``attempts`` / ``last_attempt_at`` — how many times today's run was tried,
  so failures back off instead of retrying in a tight loop;
- ``paused_reason`` — set on LOGIN_REQUIRED / verification pages. A paused
  run waits for the operator (``python runner.py once`` / ``login``) and is
  never auto-retried; a successful manual run clears the pause.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

STATE_FILE = "collect-state.json"

MAX_AUTO_ATTEMPTS_PER_DAY = 3
BASE_RETRY_MINUTES = 30

PAUSE_CHALLENGE = "challenge"


def _parse_ts(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value)
    except ValueError:
        return None


class CollectState:
    def __init__(self, data: dict | None = None) -> None:
        data = data or {}
        self.last_success_date: str = data.get("last_success_date") or ""
        self.day: str = data.get("day") or ""
        self.attempts: int = int(data.get("attempts") or 0)
        self.last_attempt_at: str = data.get("last_attempt_at") or ""
        self.last_success_at: str = data.get("last_success_at") or ""
        self.last_error: str = data.get("last_error") or ""
        self.paused_reason: str = data.get("paused_reason") or ""

    def to_dict(self) -> dict:
        return {
            "last_success_date": self.last_success_date,
            "day": self.day,
            "attempts": self.attempts,
            "last_attempt_at": self.last_attempt_at,
            "last_success_at": self.last_success_at,
            "last_error": self.last_error,
            "paused_reason": self.paused_reason,
        }


def load_state(data_dir: Path) -> CollectState:
    path = data_dir / STATE_FILE
    if not path.exists():
        return CollectState()
    try:
        return CollectState(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError):
        return CollectState()


def save_state(data_dir: Path, state: CollectState) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    temp = data_dir / (STATE_FILE + ".tmp")
    temp.write_text(
        json.dumps(state.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temp.replace(data_dir / STATE_FILE)


def reset_attempts_for_today(state: CollectState, today: str) -> None:
    """Clear the per-day attempt counter when the schedule moves to a new day.

    A challenge pause deliberately survives the day roll-over: it can only be
    cleared by a successful manual run.
    """
    if state.day != today:
        state.day = today
        state.attempts = 0


def should_run(state: CollectState, now: dt.datetime) -> tuple[bool, str]:
    """Decide whether the scheduled loop may start a run now."""
    if state.paused_reason:
        return False, f"paused ({state.paused_reason}); resolve manually, then run once"
    attempts = state.attempts
    if attempts >= MAX_AUTO_ATTEMPTS_PER_DAY:
        return False, f"max attempts reached for {state.day}"
    if attempts == 0:
        return True, "first attempt of the day"
    last_attempt = _parse_ts(state.last_attempt_at)
    if last_attempt is None:
        return True, "no attempt timestamp recorded"
    backoff = dt.timedelta(minutes=BASE_RETRY_MINUTES * (2 ** (attempts - 1)))
    remaining = (last_attempt + backoff) - now
    if remaining.total_seconds() > 0:
        return False, f"backing off; retry in ~{int(remaining.total_seconds() // 60) + 1} min"
    return True, f"retry attempt {attempts + 1}"


def record_attempt(state: CollectState, now: dt.datetime) -> None:
    state.attempts += 1
    state.last_attempt_at = now.isoformat()


def record_success(state: CollectState, now: dt.datetime) -> None:
    state.last_success_date = now.date().isoformat()
    state.last_success_at = now.isoformat()
    state.attempts = 0
    state.last_error = ""
    state.paused_reason = ""


def record_failure(state: CollectState, now: dt.datetime, error: str) -> None:
    error_text = str(error)
    state.last_error = error_text[:2000]
    if error_text.startswith("LOGIN_REQUIRED"):
        state.paused_reason = PAUSE_CHALLENGE
    else:
        # attempts incremented separately via record_attempt
        pass


def scheduled_cycle(
    state: CollectState,
    *,
    now_local: dt.datetime,
    now_utc: dt.datetime,
    start_hour: int,
    start_minute: int,
    run_fn,
) -> tuple[bool, str]:
    """One iteration of the schedule loop, operating on the caller's state.

    The same ``CollectState`` object must be shared with ``run_fn`` so the
    outcome recorded inside the run (success marker / challenge pause) is the
    state the caller persists afterwards — never an older copy. Returns
    ``(ran, reason)``.
    """
    today = now_local.date().isoformat()
    reset_attempts_for_today(state, today)
    due = (now_local.hour, now_local.minute) >= (start_hour, start_minute)
    if not due:
        return False, "not due yet"
    if state.last_success_date == today:
        return False, "already succeeded today"
    allowed, reason = should_run(state, now_local)
    if not allowed:
        return False, reason
    # Persist the attempt up-front (the caller saves the shared state), so a
    # crash mid-run still counts and cannot cause a tight retry loop.
    record_attempt(state, now_utc)
    run_fn(state)
    return True, "ran"
