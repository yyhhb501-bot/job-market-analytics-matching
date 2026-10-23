"""Rule-based and ML-based occupation grouping and seniority detection.

Supports:
1. Keyword-rule baseline (`classify_occupation_baseline`, `classify_seniority_baseline`)
2. Machine-learning classifier (TF-IDF + Linear SVM) with keyword baseline fallback.
"""

from __future__ import annotations

# group -> keyword phrases matched against the (normalised) job title.
OCCUPATION_GROUPS: dict[str, tuple[str, ...]] = {
    "data-analyst": (
        "data analyst",
        "analytics analyst",
        "reporting analyst",
        "bi analyst",
        "business intelligence analyst",
        "analytics specialist",
    ),
    "data-engineer": ("data engineer", "analytics engineer", "etl developer", "big data engineer"),
    "data-scientist": ("data scientist", "machine learning scientist", "research scientist"),
    "software-engineer": (
        "software engineer",
        "software developer",
        "backend engineer",
        "back-end engineer",
        "frontend engineer",
        "front-end engineer",
        "full stack",
        "full-stack",
        "application developer",
        "web developer",
        "programmer",
        "developer",
    ),
    "devops-sre": ("devops", "site reliability", "sre", "platform engineer", "cloud engineer"),
    "cybersecurity": ("cybersecurity", "cyber security", "security analyst", "soc analyst", "infosec"),
    "product-manager": ("product manager", "product owner", "technical product manager"),
    "project-manager": ("project manager", "program manager", "delivery manager"),
    "business-analyst": ("business analyst", "systems analyst"),
    "registered-nurse": ("registered nurse", "enrolled nurse", "staff nurse", "nurse"),
    "aged-care": ("aged care", "disability support", "support worker", "care assistant"),
    "teacher": ("teacher", "instructor", "lecturer", "educator", "tutor"),
    "accountant": ("accountant", "accounting", "bookkeeper", "auditor", "accounts payable"),
    "financial-analyst": ("financial analyst", "finance analyst", "investment analyst"),
    "marketing": ("marketing", "seo", "content marketing", "growth marketing", "brand manager"),
    "sales": ("sales", "account executive", "business development", "account manager"),
    "customer-service": ("customer service", "customer support", "call center", "call centre", "help desk"),
    "warehouse": ("warehouse", "picker", "packer", "forklift", "storeperson", "logistics"),
    "truck-driver": ("truck driver", "delivery driver", "courier", "cdl driver", "hgv driver"),
    "chef": ("chef", "cook", "kitchen hand"),
    "retail": ("retail", "store manager", "sales assistant", "cashier", "shop assistant"),
    "security-officer": ("security officer", "security guard", "loss prevention"),
    "electrician": ("electrician",),
    "mechanic": ("mechanic", "automotive technician", "diesel technician"),
    "construction": ("construction", "carpenter", "labourer", "plumber", "site supervisor"),
    "hr": ("human resources", "recruiter", "talent acquisition", "people partner"),
    "admin": ("administrative", "admin assistant", "office manager", "receptionist", "executive assistant"),
    "legal": ("lawyer", "solicitor", "paralegal", "legal counsel"),
    "healthcare-allied": ("physiotherapist", "occupational therapist", "radiographer", "pharmacist"),
}

# Order matters: longer phrases win so e.g. "data engineer" isn't caught by a
# shorter generic term.
_SORTED_GROUPS = sorted(
    ((group, phrase) for group, phrases in OCCUPATION_GROUPS.items() for phrase in phrases),
    key=lambda item: len(item[1]),
    reverse=True,
)

SENIORITY_SENIOR = ("principal", "staff", "lead", "senior", "head of", "director", "manager", "vp")
SENIORITY_JUNIOR = ("junior", "graduate", "intern", "entry level", "trainee", "assistant")


def _normalise(text: str | None) -> str:
    return (text or "").lower().replace("_", " ").replace("-", " ")


def classify_occupation_baseline(*values: str | None) -> str | None:
    """Return the best-matching occupation group using pure keyword rules."""
    for value in values:
        haystack = _normalise(value)
        if not haystack:
            continue
        for group, phrase in _SORTED_GROUPS:
            if phrase in haystack:
                return group
    return None


def classify_seniority_baseline(title: str | None) -> str | None:
    """Return the seniority level using keyword rules."""
    text = _normalise(title)
    if not text:
        return None
    if any(word in text for word in SENIORITY_SENIOR):
        return "senior"
    if any(word in text for word in SENIORITY_JUNIOR):
        return "junior"
    return "mid"


def classify_occupation(*values: str | None, use_ml: bool = True) -> str | None:
    """Return the best-matching occupation group across title (first) and text.

    Uses TF-IDF + Linear SVM when available; falls back to the keyword baseline.
    """
    if not any(values):
        return None

    baseline_match = classify_occupation_baseline(*values)

    if not use_ml:
        return baseline_match

    # If title is unknown or ambiguous to the keyword rules, try ML classifier
    try:
        from packages.enrichment.classifier import get_classifier
        clf = get_classifier()
        if clf.is_trained:
            title = values[0] if values else None
            desc = values[1] if len(values) > 1 else None
            pred_occ, conf = clf.predict_occupation(title, desc)
            if pred_occ and conf >= 0.2:
                # If baseline matched a high confidence title, keep it unless ambiguous
                if baseline_match:
                    return baseline_match
                return pred_occ
    except Exception:
        pass

    return baseline_match


def classify_seniority(title: str | None, use_ml: bool = True) -> str | None:
    """Return seniority level ('junior', 'mid', 'senior')."""
    if not title:
        return None

    baseline_match = classify_seniority_baseline(title)

    if not use_ml:
        return baseline_match

    try:
        from packages.enrichment.classifier import get_classifier
        clf = get_classifier()
        if clf.is_trained:
            pred_sen, conf = clf.predict_seniority(title)
            if pred_sen and conf >= 0.3:
                return pred_sen
    except Exception:
        pass

    return baseline_match


__all__ = [
    "OCCUPATION_GROUPS",
    "classify_occupation",
    "classify_occupation_baseline",
    "classify_seniority",
    "classify_seniority_baseline",
]
