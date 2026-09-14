from __future__ import annotations

from packages.enrichment.occupations import classify_occupation, classify_seniority


def test_classify_occupation_groups():
    assert classify_occupation("Senior Data Analyst") == "data-analyst"
    assert classify_occupation("Business Data Analyst") == "data-analyst"
    assert classify_occupation("Registered Nurse") == "registered-nurse"
    assert classify_occupation("Software Engineer") == "software-engineer"
    assert classify_occupation("Backend Engineer") == "software-engineer"
    assert classify_occupation("Chef de Partie") == "chef"
    assert classify_occupation("Warehouse Storeperson") == "warehouse"


def test_classify_occupation_uses_description_fallback():
    assert classify_occupation("Team Member", "We need a barista") is None
    assert classify_occupation("Team Member", "Provide customer service support") == "customer-service"


def test_classify_occupation_unknown():
    assert classify_occupation("Chief Vibes Officer") is None
    assert classify_occupation(None) is None


def test_classify_seniority():
    assert classify_seniority("Senior Data Engineer") == "senior"
    assert classify_seniority("Lead Product Manager") == "senior"
    assert classify_seniority("Junior Developer") == "junior"
    assert classify_seniority("Graduate Accountant") == "junior"
    assert classify_seniority("Data Analyst") == "mid"
    assert classify_seniority(None) is None
