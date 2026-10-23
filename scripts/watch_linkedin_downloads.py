"""Import completed LinkedIn extension downloads into the local SQLite database.

This is a local bridge only: it does not control the browser, change LinkedIn
requests, or bypass challenges. The extension remains responsible for
collection and pausing when LinkedIn asks for verification.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import time
from pathlib import Path

# Allow direct execution from the repository root or from another working
# directory without requiring an installed package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clients.linkedin_database import connect, ingest
from clients.linkedin_local_agent.uploader.api_client import ImportClient, UploadError, chunked

LOG = logging.getLogger("linkedin-download-watcher")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--downloads",
        type=Path,
        default=Path.home() / "Downloads",
        help="Edge download directory (default: %%USERPROFILE%%/Downloads)",
    )
    parser.add_argument("--db", type=Path, default=None, help="SQLite path")
    parser.add_argument("--interval", type=float, default=10.0, help="Polling interval in seconds")
    parser.add_argument("--once", action="store_true", help="Import currently completed files and exit")
    parser.add_argument(
        "--upload-url",
        default=os.environ.get("JOBAGG_API_BASE_URL"),
        help="Job Aggregator API base URL; defaults to JOBAGG_API_BASE_URL",
    )
    parser.add_argument(
        "--token-env",
        default="JOBAGG_DEVICE_TOKEN",
        help="Environment variable containing the device token",
    )
    return parser.parse_args()


def is_completed(path: Path, seen_sizes: dict[Path, int]) -> bool:
    """Return true after observing the same non-zero file size twice."""
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return False
    if size <= 0 or path.suffix.lower() != ".json" or not path.name.startswith("linkedin-"):
        return False
    previous = seen_sizes.get(path)
    seen_sizes[path] = size
    return previous == size


def upload_export(path: Path, payload: dict, uploader: ImportClient) -> dict:
    if payload.get('observations'):
        return uploader.observe(payload['observations'])
    jobs = payload.get("jobs", [])
    if not isinstance(jobs, list):
        raise ValueError("导出文件中的 jobs 必须是数组")
    config = payload.get("config") or {}
    location_country = {"usa": "US", "australia": "AU", "melbourne": "AU", "sydney": "AU", "austin": "US"}.get(config.get("location"))
    normalized = []
    for job in jobs:
        item = dict(job)
        extra = dict(item.get("raw_payload") or {})
        item["country"] = item.get("country") or extra.get("search_country") or location_country
        item["state"] = item.get("state") or extra.get("search_state")
        item["city"] = item.get("city") or extra.get("search_city")
        item["raw_payload"] = extra
        normalized.append(item)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    responses = []
    for index, batch in enumerate(chunked(normalized)):
        responses.append(uploader.upload(
            batch,
            query=f"linkedin:{config.get('plan') or 'custom'}",
            idempotency_key=f"linkedin-{digest}-{index}",
        ))
    return {"batches": len(responses), "records": len(normalized), "responses": responses}


def import_ready(
    downloads: Path,
    db_path: Path,
    seen_sizes: dict[Path, int],
    uploader: ImportClient | None = None,
    uploaded_digests: set[str] | None = None,
) -> int:
    downloads.mkdir(parents=True, exist_ok=True)
    imported = 0
    uploaded_digests = uploaded_digests if uploaded_digests is not None else set()
    with connect(db_path) as db:
        for path in sorted(downloads.glob("linkedin-*.json"), key=lambda p: p.stat().st_mtime):
            if not is_completed(path, seen_sizes):
                continue
            try:
                result = ingest(db, path)
            except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
                LOG.error("无法导入 %s：%s", path, exc)
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if result.get("already_imported"):
                LOG.info("跳过重复文件：%s", path.name)
            if uploader and digest not in uploaded_digests:
                try:
                    payload = json.loads(path.read_text(encoding="utf-8-sig"))
                    uploaded = upload_export(path, payload, uploader)
                    uploaded_digests.add(digest)
                    LOG.info("已写入职位聚合平台 %s：%s", path.name, uploaded)
                except (OSError, UnicodeError, ValueError, json.JSONDecodeError, UploadError) as exc:
                    LOG.error("本地已导入，但写入职位聚合平台失败 %s：%s", path.name, exc)
            if not result.get("already_imported"):
                imported += 1
                LOG.info("已导入本地数据库 %s：%s", path.name, result)
    return imported


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    db_path = args.db or Path(__file__).resolve().parents[1] / "data/linkedin/positions.sqlite3"
    seen_sizes: dict[Path, int] = {}
    uploaded_digests: set[str] = set()
    uploader = None
    if args.upload_url:
        token = os.environ.get(args.token_env)
        if not token:
            raise SystemExit(f"已指定 --upload-url，但环境变量 {args.token_env} 未设置")
        uploader = ImportClient(args.upload_url, token)
    try:
        while True:
            import_ready(args.downloads, db_path, seen_sizes, uploader, uploaded_digests)
            if args.once:
                return
            time.sleep(max(1.0, args.interval))
    finally:
        if uploader:
            uploader.close()


if __name__ == "__main__":
    main()
