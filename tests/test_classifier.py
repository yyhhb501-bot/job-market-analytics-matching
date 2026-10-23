from __future__ import annotations

import pytest

from packages.enrichment.classifier import OccupationSeniorityClassifier, get_classifier
from packages.enrichment.occupations import (
    classify_occupation,
    classify_occupation_baseline,
    classify_seniority,
    classify_seniority_baseline,
)


def test_classifier_loaded():
    clf = get_classifier()
    assert clf is not None
    assert clf.is_trained is True
    assert len(clf.occupation_classes) > 0
    assert len(clf.seniority_classes) > 0


def test_svm_prediction_standard():
    clf = get_classifier()
    res = clf.predict("Senior Data Analyst", "SQL queries, dashboards, and KPI reporting.")
    assert res.occupation == "data-analyst"
    assert res.seniority == "senior"
    assert res.method == "svm"
    # Over 29 classes, random baseline is ~0.034; 0.15+ indicates strong signal
    assert res.occupation_confidence > 0.15


def test_svm_prediction_ambiguous_title():
    clf = get_classifier()
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
    clf = get_classifier()
    res = clf.predict(
        "Technical Product Manager",
        "Own API roadmaps, bridge engineering and business teams, define telemetry user stories.",
    )
    assert res.occupation == "product-manager"


def test_seniority_modifier_inversion():
    clf = get_classifier()
    # Baseline rule checks SENIORITY_SENIOR first, so "vp" triggers false-positive 'senior'
    assert classify_seniority_baseline("Assistant to VP") == "senior"

    # SVM correctly identifies "junior"
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
