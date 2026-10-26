"""Build an explicitly dated public aggregate snapshot; never export job records."""

from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path

from apps.api.routers.methodology import methodology
from apps.api.schemas import CollectionOverviewResponse
from packages.illustrative_jobs import illustrative_jobs

ROOT = Path(__file__).resolve().parents[1]


def build(api_url: str, output: Path) -> None:
    with urllib.request.urlopen(
        f"{api_url.rstrip('/')}/api/v1/collection/overview", timeout=30
    ) as response:
        overview = CollectionOverviewResponse.model_validate_json(response.read())
    # Explicit whitelist: new API fields cannot silently enter the public export.
    snapshot = {
        "generated_at": overview.generated_at.isoformat(),
        "daily_target_per_source": overview.daily_target_per_source,
        "sources": [
            {
                key: row.model_dump(mode="json")[key]
                for key in (
                    "source",
                    "internal_total",
                    "public_total",
                    "today_new_bj",
                    "seven_day_new_bj",
                    "last_ingest_at",
                )
            }
            for row in overview.sources
        ],
        "uploads": [
            {
                key: row.model_dump(mode="json")[key]
                for key in (
                    "source",
                    "today_accepted_bj",
                    "today_duplicate_bj",
                    "today_rejected_bj",
                    "last_batch_status",
                    "last_batch_accepted",
                    "last_batch_duplicate",
                    "last_batch_rejected",
                    "last_batch_completed_at",
                    "collector_state",
                )
            }
            for row in overview.local_uploads
        ],
        "trend": [row.model_dump(mode="json") for row in overview.seven_day_trend],
        "methodology": methodology(),
        "examples": [
            {
                "title": job.title,
                "country": job.country,
                "city": job.city,
                "description": job.description,
                "remote_type": job.remote_type,
            }
            for job in illustrative_jobs()
        ],
    }
    if snapshot["methodology"].get("corpus_scope") != "synthetic_only":
        raise ValueError("Public demo requires a synthetic-only evaluation artifact")
    output.mkdir(parents=True, exist_ok=True)
    (output / "snapshot.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for name in ("index.html", "demo.js", "demo.css"):
        (output / name).write_bytes((ROOT / "apps/teacher-demo" / name).read_bytes())
    (output / ".nojekyll").write_text("", encoding="utf-8")
    print(f"Built {output}; snapshot {snapshot['generated_at']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://localhost:8010")
    parser.add_argument("--output", type=Path, default=ROOT / "out/teacher-demo")
    args = parser.parse_args()
    build(args.api_url, args.output)
