"""Public, aggregate-only view of the versioned classification experiment."""

import json
from pathlib import Path

from fastapi import APIRouter

router = APIRouter(tags=["methodology"])
METRICS_PATH = (
    Path(__file__).resolve().parents[3] / "artifacts/classification_eval/evaluation_metrics.json"
)


@router.get("/methodology")
def methodology() -> dict:
    try:
        value = json.loads(METRICS_PATH.read_text(encoding="utf-8"))
        strategies = [
            {
                "name": name,
                "occupation_macro_f1": row["occupation"]["macro_f1"],
                "seniority_macro_f1": row["seniority"]["macro_f1"],
                "overall_macro_f1": row["overall_macro_f1"],
            }
            for name, row in value["strategies"].items()
        ]
        return {
            "available": True,
            "dataset_sha256": value["dataset_sha256"],
            "corpus_scope": value.get("corpus_scope", "unverified_snapshot"),
            "human_ground_truth_present": value["human_ground_truth_present"],
            "train_count": value["train_count"],
            "test_count": value["test_count"],
            "seed": value["seed"],
            "strategies": strategies,
            "generalisation_status": value["generalisation_status"],
        }
    except (OSError, ValueError, KeyError, TypeError):
        return {"available": False, "message": "尚无可核对的实验产物；不展示估计指标。"}
