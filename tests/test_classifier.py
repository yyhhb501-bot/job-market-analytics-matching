"""Classification evaluation tests: online behavior, split hygiene, and
that the generated report is fully driven by computed evaluation metrics."""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

import pytest

import packages.enrichment.classifier as classifier_module
from packages.enrichment.classifier import (
    EvaluationReport,
    OccupationSeniorityClassifier,
    set_global_classifier,
)
from packages.enrichment.occupations import (
    classify_occupation,
    classify_seniority,
    classify_seniority_baseline,
)

# The evaluation script's helper functions are exercised directly; keep these
# imports tolerant of run-from-anywhere execution.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.train_and_eval_classifier import (  # noqa: E402
    build_evaluation_corpus,
    dataset_hash,
    evaluate_strategies,
    generate_evaluation_markdown,
    stratified_group_split,
)


@pytest.fixture()
def restore_global_classifier():
    previous = classifier_module._GLOBAL_CLASSIFIER
    try:
        yield previous
    finally:
        classifier_module._GLOBAL_CLASSIFIER = previous


def test_classifier_loaded():
    clf = classifier_module.get_classifier()
    assert clf is not None
    assert clf.is_trained is True
    assert len(clf.occupation_classes) > 0
    assert len(clf.seniority_classes) > 0


def test_svm_prediction_standard():
    clf = classifier_module.get_classifier()
    res = clf.predict("Senior Data Analyst", "SQL queries, dashboards, and KPI reporting.")
    assert res.occupation == "data-analyst"
    assert res.seniority == "senior"
    assert res.method == "svm"
    # This is an uncalibrated relative margin, not an accuracy guarantee.
    assert 0 < res.occupation_relative_score <= 1
    assert res.occupation_confidence == res.occupation_relative_score


def test_svm_prediction_ambiguous_title():
    clf = classifier_module.get_classifier()
    # "Operations Specialist" without domain in title:
    # 1. With customer service context
    res1 = clf.predict(
        "Operations Specialist",
        "Handle inbound Zendesk tickets, answer customer phone calls, resolve billing issues.",
    )
    assert res1.occupation == "customer-service"

    # 2. With warehouse context
    res2 = clf.predict(
        "Operations Specialist",
        "Operate forklift, manage daily shipping pallets, pick and pack warehouse orders.",
    )
    assert res2.occupation == "warehouse"


def test_svm_mixed_responsibility_title():
    clf = classifier_module.get_classifier()
    res = clf.predict(
        "Technical Product Manager",
        "Own API roadmaps, bridge engineering and business teams, define telemetry user stories.",
    )
    assert res.occupation == "product-manager"


def test_seniority_modifier_inversion():
    # Baseline rule checks SENIORITY_SENIOR first, so "vp" triggers false-positive 'senior'
    assert classify_seniority_baseline("Assistant to VP") == "senior"

    # The SVM can capture the inversion when the training data contains
    # assistant-duty junior evidence that the rule ignores. Trained in-test so
    # the assertion does not depend on whichever split the shipped artifact
    # happened to be trained on.
    clf = OccupationSeniorityClassifier()
    clf.fit([
        {"title": "Executive Assistant to the CEO", "description": "Calendar scheduling, booking flights, preparing meeting minutes and travel itineraries.", "occupation": "admin", "seniority": "junior"},
        {"title": "Administrative Assistant", "description": "Diary management, scheduling meetings, taking notes, booking travel.", "occupation": "admin", "seniority": "junior"},
        {"title": "VP of Engineering", "description": "Leading the engineering organisation, owning roadmap and headcount planning.", "occupation": "software-engineer", "seniority": "senior"},
        {"title": "Senior VP of Sales", "description": "Owns regional sales targets, manages sales directors.", "occupation": "sales", "seniority": "senior"},
        {"title": "Head Chef", "description": "Runs the kitchen brigade, designs seasonal menus.", "occupation": "chef", "seniority": "senior"},
    ])
    res = clf.predict(
        "Assistant to VP",
        "Calendar scheduling, booking flights, preparing meeting notes for the VP.",
    )
    assert res.seniority == "junior"


def test_classify_occupation_unified_interface():
    # Canonical titles
    assert classify_occupation("Senior Data Analyst") == "data-analyst"
    assert classify_occupation("Registered Nurse") == "registered-nurse"
    assert classify_occupation("Software Engineer") == "software-engineer"

    # Fallback to None on unknown
    assert classify_occupation("Chief Vibes Officer") is None
    assert classify_occupation(None) is None


def test_classify_seniority_unified_interface():
    assert classify_seniority("Senior Data Engineer") == "senior"
    assert classify_seniority("Junior Developer") == "junior"
    assert classify_seniority(None) is None


# ---------------------------------------------------------------------------
# Split hygiene: same template/job/cross-source duplicates must share a split.


def _corpus() -> list[dict]:
    return build_evaluation_corpus(db_path=None)


def test_group_split_never_leaks_groups():
    corpus = _corpus()
    train, test, assignment = stratified_group_split(corpus, 0.25, seed=42)

    seen: dict[str, set[str]] = defaultdict(set)
    for sample in train:
        seen[sample["group_key"]].add("train")
    for sample in test:
        seen[sample["group_key"]].add("test")
    straddling = {g: s for g, s in seen.items() if len(s) > 1}
    assert not straddling, "identical/near-duplicate variants must move together"

    # near 75/25 by whole groups; every occupation holding >=2 groups is present
    # on both sides
    test_occ = {s["occ"] for s in test}
    train_occ = {s["occ"] for s in train}
    for occ in {s["occ"] for s in corpus}:
        n_groups = len({s["group_key"] for s in corpus if s["occ"] == occ})
        if n_groups >= 2:
            assert occ in test_occ, occ
            assert occ in train_occ, occ

    # provenance is recorded; template rows are marked synthetic
    assert all(s["label_origin"] == "hand_authored_template" for s in corpus)
    assert all(
        s["source"] in ("synthetic_template", "ambiguous_mixed") for s in corpus
    )


def test_dataset_hash_changes_when_content_changes():
    corpus = _corpus()
    mutated = [dict(s) for s in corpus]
    mutated[0] = dict(mutated[0], desc=mutated[0]["desc"] + " mutated tail")
    assert dataset_hash(corpus) != dataset_hash(mutated)
    assert dataset_hash(corpus) == dataset_hash([dict(s) for s in corpus])


def test_split_reproducible_by_seed():
    corpus = _corpus()
    train_a, test_a, map_a = stratified_group_split(corpus, 0.25, seed=42)
    train_b, test_b, map_b = stratified_group_split(
        [dict(s) for s in corpus], 0.25, seed=42
    )
    assert map_a == map_b
    train_c, test_c, map_c = stratified_group_split(
        [dict(s) for s in corpus], 0.25, seed=12345
    )
    assert map_c != map_a


def test_tfidf_fit_only_on_train_split():
    train = [
        {"title": "Senior Data Analyst", "description": "SQL dashboards and KPI reporting.", "occupation": "data-analyst", "seniority": "senior"},
        {"title": "Junior Data Analyst", "description": "Excel charts and reporting.", "occupation": "data-analyst", "seniority": "junior"},
        {"title": "Head Chef", "description": "Kitchen staff leadership and menu engineering.", "occupation": "chef", "seniority": "senior"},
        {"title": "Kitchen Hand", "description": "Dishwashing and vegetable prep.", "occupation": "chef", "seniority": "junior"},
    ]
    test = [
        {"title": "zzzquark Analyst", "description": "zzzquark dashboards one.", "occupation": "data-analyst", "seniority": "mid"},
        {"title": "zzzquark Planner", "description": "zzzquark dashboards two.", "occupation": "data-analyst", "seniority": "mid"},
    ]
    clf = OccupationSeniorityClassifier()
    clf.fit(train)
    assert "zzzquark" not in clf.vectorizer.vocabulary_
    assert "analyst" in clf.vectorizer.vocabulary_  # control token from train
    clf.predict(test[0]["title"], test[0]["description"])  # transform path works


# ---------------------------------------------------------------------------
# Three distinct strategies on the same holdout.


def test_three_strategies_reported_separately(restore_global_classifier):
    corpus = _corpus()
    train, test, assignment = stratified_group_split(corpus, 0.25, seed=42)
    clf, metrics, rows = evaluate_strategies(train, test, seed=42)  # noqa: F841

    assert set(metrics["strategies"]) == {"keyword_baseline", "pure_svm", "online_hybrid"}
    for strategy in metrics["strategies"].values():
        assert set(strategy) >= {"occupation", "seniority", "overall_macro_f1",
                                 "occupation_errors", "seniority_errors", "total_errors"}
        assert 0.0 <= strategy["occupation"]["macro_f1"] <= 1.0
        assert strategy["total_errors"] == (
            strategy["occupation_errors"] + strategy["seniority_errors"])


def test_online_hybrid_prefers_baseline_rule_match(restore_global_classifier):
    """The hybrid keeps a rule match even when the SVM disagrees, so its
    per-row predictions differ from the pure-SVM strategy somewhere."""
    from scripts.train_and_eval_classifier import evaluate_strategies

    corpus = _corpus()
    train, test, assignment = stratified_group_split(corpus, 0.25, seed=42)
    clf, metrics, rows = evaluate_strategies(train, test, seed=42)
    assert rows["online_hybrid"]["y_pred_occ"] != rows["pure_svm"]["y_pred_occ"]

    # Isolated check of one production-rule interaction: baseline authority wins.
    # Both targets need >= 2 classes or the underlying SVC refuses to fit.
    trained = OccupationSeniorityClassifier()
    trained.fit([
        {"title": "Data Wrangler", "description": "warehouse pallet scanning.", "occupation": "warehouse", "seniority": "mid"},
        {"title": "Data Wrangler", "description": "kitchen food prep.", "occupation": "chef", "seniority": "senior"},
    ])
    set_global_classifier(trained)
    assert classify_occupation("Registered Nurse", "ANY description", use_ml=True) == "registered-nurse"


# ---------------------------------------------------------------------------
# The report must be a pure function of computed metrics.


HARDCODED_FABRICATED_VALUES = (
    "0.6720",
    "0.6912",
    "0.6816",
    "0.8435",
    "0.8390",
    "0.8413",
)


def _report_with_metrics(base_overall: float, svm_overall: float,
                         baseline_total_errors: int, svm_total_errors: int,
                         hybrid_overall: float) -> EvaluationReport:
    def strategy(overall: float, total_errors: int):
        return {
            "occupation": {"macro_f1": overall, "error_count": total_errors, "errors": []},
            "seniority": {"macro_f1": overall, "error_count": 0, "errors": []},
            "overall_macro_f1": overall,
            "occupation_errors": total_errors,
            "seniority_errors": 0,
            "total_errors": total_errors,
        }

    return EvaluationReport(
        baseline_occupation_macro_f1=base_overall,
        svm_occupation_macro_f1=svm_overall,
        baseline_seniority_macro_f1=base_overall,
        svm_seniority_macro_f1=svm_overall,
        overall_baseline_macro_f1=base_overall,
        overall_svm_macro_f1=svm_overall,
        hybrid_occupation_macro_f1=hybrid_overall,
        hybrid_seniority_macro_f1=hybrid_overall,
        overall_hybrid_macro_f1=hybrid_overall,
        detailed_metrics={
            "train_count": 300, "test_count": 100, "seed": 42,
            "dataset_sha256": "deadbeef",
            "baseline_total_errors": baseline_total_errors,
            "svm_total_errors": svm_total_errors,
            "hybrid_total_errors": svm_total_errors,
            "label_provenance": {"templates": "synthetic"},
            "human_ground_truth_present": False,
        },
        misclassification_analysis={
            "summary": "synthetic summary",
            "svm_vs_baseline_error_delta": svm_total_errors - baseline_total_errors,
            "hybrid_vs_baseline_error_delta": svm_total_errors - baseline_total_errors,
        },
        meta={
            "seed": 42,
            "test_fraction": 0.25,
            "dataset_sha256": "deadbeef",
            "train_count": 300,
            "test_count": 100,
            "group_strategy": "grouped",
            "label_provenance": {"hand_authored_template": "synthetic", "rule_pseudo_label": "pseudo"},
            "human_ground_truth_present": False,
            "generalisation_status": "pending",
            "tfidf_fit_scope": "training_split_only",
            "versions": {"python": "3.12"},
            "splits": {"occupation_support_test": {"chef": 2, "data-analyst": 3}},
            "strategies": {
                "keyword_baseline": strategy(base_overall, baseline_total_errors),
                "pure_svm": strategy(svm_overall, svm_total_errors),
                "online_hybrid": strategy(hybrid_overall, svm_total_errors),
            },
        },
    )


def test_generated_report_is_dynamic(tmp_path):
    md_a = tmp_path / "A.md"
    md_b = tmp_path / "B.md"
    generate_evaluation_markdown(_report_with_metrics(0.5, 0.72, 30, 10, 0.7), md_a)
    generate_evaluation_markdown(_report_with_metrics(0.55, 0.93, 12, 44, 0.61), md_b)
    text_a = md_a.read_text(encoding="utf-8")
    text_b = md_b.read_text(encoding="utf-8")

    assert "0.5000" in text_a and "0.7200" in text_a
    assert "0.5500" in text_b and "0.9300" in text_b
    assert text_a != text_b
    # error-increase must be called out honestly
    assert "went UP" in text_b
    assert "+32" in text_b or "32" in text_b


def test_generated_report_has_no_hardcoded_resume_metrics(tmp_path):
    md = tmp_path / "report.md"
    generate_evaluation_markdown(_report_with_metrics(0.31, 0.47, 88, 91, 0.44), md)
    text = md.read_text(encoding="utf-8")
    for value in HARDCODED_FABRICATED_VALUES:
        assert value not in text
    # the old static error counts 42/65 (fabricated baseline/SVM errors) may not resurface
    assert "| 42 |" not in text and "| 65 |" not in text


def test_report_honest_when_resume_not_reproduced(tmp_path):
    md = tmp_path / "report.md"
    generate_evaluation_markdown(_report_with_metrics(0.31, 0.47, 88, 91, 0.44), md)
    text = md.read_text(encoding="utf-8")
    assert "The measured values do not match the resume claim." in text
    assert "Suggested honest resume wording" in text
    assert "Human-labelled holdout evaluation pending." in text
