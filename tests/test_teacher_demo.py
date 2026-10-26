"""Public publishing must stay aggregate-only even if the API grows fields."""

import io
import json

from scripts import build_teacher_demo


def test_export_whitelist_excludes_raw_jobs_and_device_identity(tmp_path, monkeypatch):
    value = {
        "generated_at": "2026-10-26T00:00:00Z",
        "daily_target_per_source": 600,
        "sources": [
            {
                "source": "seek_user_import",
                "internal_total": 158,
                "public_total": 0,
                "today_new_bj": 0,
                "seven_day_new_bj": 6,
                "raw_jobs": [{"description": "PRIVATE JOB BODY"}],
            }
        ],
        "local_uploads": [
            {
                "source": "seek_user_import",
                "today_accepted_bj": 0,
                "today_duplicate_bj": 0,
                "today_rejected_bj": 0,
                "device_token": "PRIVATE DEVICE TOKEN",
                "owner": "PRIVATE OWNER",
            }
        ],
        "seven_day_trend": [],
        "new_private_field": "DO NOT EXPORT",
    }
    monkeypatch.setattr(
        build_teacher_demo.urllib.request,
        "urlopen",
        lambda *args, **kwargs: io.BytesIO(json.dumps(value).encode()),
    )
    build_teacher_demo.build("http://test-api", tmp_path)
    exported = (tmp_path / "snapshot.json").read_text(encoding="utf-8")
    assert all(
        private not in exported
        for private in [
            "PRIVATE JOB BODY",
            "PRIVATE DEVICE TOKEN",
            "PRIVATE OWNER",
            "DO NOT EXPORT",
        ]
    )
    result = json.loads(exported)
    assert result["sources"][0]["internal_total"] == 158
    assert len(result["examples"]) == 6
    assert result["methodology"]["corpus_scope"] == "synthetic_only"
    assert (tmp_path / "index.html").exists()
