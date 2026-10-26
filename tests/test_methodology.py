import json


def test_methodology_returns_computed_aggregate_only(client, monkeypatch, tmp_path):
    from apps.api.routers import methodology as module

    path = tmp_path / "metrics.json"
    path.write_text(
        json.dumps(
            {
                "dataset_sha256": "abc",
                "human_ground_truth_present": False,
                "corpus_scope": "synthetic_only",
                "seed": 42,
                "train_count": 10,
                "test_count": 4,
                "generalisation_status": "not human ground truth",
                "private_title": "DO_NOT_EXPOSE",
                "strategies": {
                    "keyword_baseline": {
                        "occupation": {"macro_f1": 0.31},
                        "seniority": {"macro_f1": 0.42},
                        "overall_macro_f1": 0.365,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "METRICS_PATH", path)
    response = client.get("/api/v1/methodology")
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True
    assert body["strategies"][0]["occupation_macro_f1"] == 0.31
    assert "DO_NOT_EXPOSE" not in response.text


def test_missing_experiment_never_invents_metrics(client, monkeypatch, tmp_path):
    from apps.api.routers import methodology as module

    monkeypatch.setattr(module, "METRICS_PATH", tmp_path / "missing.json")
    body = client.get("/api/v1/methodology").json()
    assert body["available"] is False and "strategies" not in body
