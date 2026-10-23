"""Reconcile local LinkedIn staging databases with the website import gateway.

SEEK and the Edge download watcher upload as they collect. This job catches
LinkedIn rows left in local SQLite after an uploader or API outage. Every batch
uses the existing device identity, server validation and deduplication path.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import os
import sqlite3
import time
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path

from sqlalchemy import select

from apps.api.database import get_session_factory
from apps.api.import_gateway import import_jobs
from apps.api.models import CollectorDevice, ImportBatch
from apps.api.schemas import ImportJobIn, ImportJobsRequest
from apps.api.security import hash_device_token

LOG = logging.getLogger("jobagg.nightly_import")
ROOT = Path(__file__).resolve().parents[2]
SOURCE_PATHS = {
    "edge": ROOT / "data/linkedin/positions.sqlite3",
    "daily": ROOT / "data/linkedin-daily/jobs.sqlite3",
}
STATE_PATH = ROOT / "data/imports/nightly-sync-state.json"
BATCH_SIZE = 200


def _timestamp(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)


def _open_readonly(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    return db


def _edge_rows(path: Path, cursor: tuple[str, str]) -> Iterator[tuple[tuple[str, str], ImportJobIn]]:
    with closing(_open_readonly(path)) as db:
        rows = db.execute(
            "SELECT * FROM positions WHERE last_seen > ? OR (last_seen = ? AND job_id > ?) "
            "ORDER BY last_seen, job_id",
            (cursor[0], cursor[0], cursor[1]),
        )
        for row in rows:
            marker = (row["last_seen"], row["job_id"])
            yield marker, ImportJobIn(
                source="linkedin_user_import",
                source_job_id=row["job_id"],
                title=row["title"],
                company=row["company"],
                description=row["description"],
                country=row["search_country"],
                state=row["search_state"],
                city=row["search_city"],
                canonical_url=row["url"] or f"https://www.linkedin.com/jobs/view/{row['job_id']}/",
                collected_at=_timestamp(row["last_seen"]),
                raw_payload={
                    "staging_source": "linkedin_edge",
                    "location": row["location"],
                    "occupation_group": row["occupation_group"],
                    "occupation_soc": row["occupation_soc"],
                    "occupation_anzsco": row["occupation_anzsco"],
                    "lifecycle_status": row["lifecycle_status"],
                    "possibly_closed_at": row["possibly_closed_at"],
                },
            )


def _daily_rows(path: Path, cursor: tuple[str, str]) -> Iterator[tuple[tuple[str, str], ImportJobIn]]:
    with closing(_open_readonly(path)) as db:
        rows = db.execute(
            "SELECT target, id, payload FROM jobs ORDER BY target, id"
        )
        pending: list[tuple[tuple[str, str], ImportJobIn]] = []
        for row in rows:
            job = json.loads(row["payload"])
            seen = str(job.get("collected_at") or "")
            marker = (seen, f"{row['target']}:{row['id']}")
            if marker <= cursor:
                continue
            country = "US" if row["target"].startswith("us-") else "AU" if row["target"].startswith("au-") else None
            pending.append((marker, ImportJobIn(
                source="linkedin_user_import",
                source_job_id=str(row["id"]),
                title=job["title"],
                company=job.get("company"),
                description=job.get("description"),
                country=country,
                canonical_url=job.get("canonical_url") or f"https://www.linkedin.com/jobs/view/{row['id']}/",
                collected_at=_timestamp(seen),
                raw_payload={
                    "staging_source": "linkedin_daily",
                    "target": row["target"],
                    "keyword": job.get("keyword"),
                    "location": job.get("location"),
                },
            )))
        yield from sorted(pending, key=lambda pair: pair[0])


def _load_state(path: Path) -> dict:
    if not path.exists():
        return {"cursors": {}}
    state = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(state, dict) or not isinstance(state.get("cursors"), dict):
        raise ValueError("nightly import state is invalid")
    return state


def _save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


@contextmanager
def _lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_suffix(".lock")
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        if time.time() - lock.stat().st_mtime < 7200:
            raise RuntimeError("nightly import is already running") from None
        lock.unlink()
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.close(fd)
        yield
    finally:
        lock.unlink(missing_ok=True)


def sync_nightly_imports(
    *, state_path: Path = STATE_PATH, source_paths: dict[str, Path] | None = None
) -> dict:
    """Resume every unfinished local batch, then record the latest checkpoint."""
    token = os.environ.get("JOBAGG_DEVICE_TOKEN")
    if not token:
        raise RuntimeError("JOBAGG_DEVICE_TOKEN is required for nightly imports")
    paths = source_paths or SOURCE_PATHS
    with _lock(state_path):
        state = _load_state(state_path)
        summary = {"attempted": 0, "accepted": 0, "duplicate": 0, "rejected": 0, "missing": []}
        with get_session_factory()() as db:
            device = db.scalar(
                select(CollectorDevice).where(CollectorDevice.token_hash == hash_device_token(token))
            )
            if device is None or device.revoked_at is not None:
                raise RuntimeError("nightly import device token is invalid or revoked")

            for source, path in paths.items():
                if not path.is_file():
                    summary["missing"].append(source)
                    continue
                cursor = tuple(state["cursors"].get(source, ["", ""]))
                rows = _edge_rows(path, cursor) if source == "edge" else _daily_rows(path, cursor)
                batch: list[ImportJobIn] = []
                marker = cursor
                for marker, item in rows:
                    batch.append(item)
                    if len(batch) >= BATCH_SIZE:
                        _flush(db, device, source, batch, marker, state, state_path, summary)
                        batch = []
                if batch:
                    _flush(db, device, source, batch, marker, state, state_path, summary)

        state["last_run"] = {"at": dt.datetime.now(dt.UTC).isoformat(), **summary}
        _save_state(state_path, state)
        LOG.info("nightly local import completed: %s", summary)
        return summary


def _flush(db, device, source, jobs, marker, state, state_path, summary) -> None:
    identity = "|".join(f"{job.source_job_id}:{job.collected_at}" for job in jobs)
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
    key = f"nightly-{source}-{digest}"
    was_imported = db.scalar(
        select(ImportBatch.id).where(
            ImportBatch.device_id == device.id,
            ImportBatch.idempotency_key == key,
        )
    ) is not None
    batch, errors = import_jobs(
        db,
        device,
        ImportJobsRequest(source="linkedin_user_import", query=f"nightly:{source}", jobs=jobs),
        idempotency_key=key,
    )
    summary["attempted"] += len(jobs)
    if not was_imported:
        summary["accepted"] += batch.accepted_count
        summary["duplicate"] += batch.duplicate_count
        summary["rejected"] += batch.rejected_count
    if errors:
        LOG.warning("nightly import %s rejected %s records: %s", source, len(errors), errors[:3])
    state["cursors"][source] = list(marker)
    _save_state(state_path, state)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(sync_nightly_imports(), ensure_ascii=False))
