"""Deterministic, dependency-free job enrichment.

Provides skill extraction, extractive summaries, occupation classification,
and a résumé match score ranked by keyword coverage, title weight, and recency.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from packages.enrichment.occupations import classify_occupation, classify_seniority

# Canonical skill -> surface forms to look for (lower-cased).
SKILLS: dict[str, tuple[str, ...]] = {
    "Python": ("python",),
    "JavaScript": ("javascript", "js"),
    "TypeScript": ("typescript", "ts"),
    "Java": ("java",),
    "Go": ("golang", "go"),
    "C++": ("c++", "cpp"),
    "C#": ("c#", "csharp"),
    "Ruby": ("ruby",),
    "PHP": ("php",),
    "Scala": ("scala",),
    "Kotlin": ("kotlin",),
    "Swift": ("swift",),
    "Rust": ("rust",),
    "SQL": ("sql",),
    "React": ("react", "react.js", "reactjs"),
    "Vue": ("vue", "vue.js", "vuejs"),
    "Angular": ("angular",),
    "Next.js": ("next.js", "nextjs"),
    "Node.js": ("node.js", "nodejs", "node"),
    "Django": ("django",),
    "Flask": ("flask",),
    "FastAPI": ("fastapi",),
    "Spring": ("spring boot", "spring"),
    ".NET": (".net", "dotnet", "asp.net"),
    "REST APIs": ("rest", "restful", "rest api"),
    "GraphQL": ("graphql",),
    "gRPC": ("grpc",),
    "PostgreSQL": ("postgresql", "postgres"),
    "MySQL": ("mysql",),
    "MongoDB": ("mongodb", "mongo"),
    "Redis": ("redis",),
    "Elasticsearch": ("elasticsearch", "elastic search", "opensearch"),
    "Kafka": ("kafka",),
    "RabbitMQ": ("rabbitmq",),
    "Docker": ("docker",),
    "Kubernetes": ("kubernetes", "k8s"),
    "Terraform": ("terraform",),
    "AWS": ("aws", "amazon web services"),
    "Azure": ("azure",),
    "GCP": ("gcp", "google cloud"),
    "CI/CD": ("ci/cd", "cicd", "continuous integration", "continuous delivery"),
    "Git": ("git",),
    "Linux": ("linux",),
    "Spark": ("spark", "apache spark"),
    "Airflow": ("airflow",),
    "dbt": ("dbt",),
    "Snowflake": ("snowflake",),
    "Databricks": ("databricks",),
    "Pandas": ("pandas",),
    "NumPy": ("numpy",),
    "PyTorch": ("pytorch",),
    "TensorFlow": ("tensorflow",),
    "Machine Learning": ("machine learning", "ml"),
    "Data Engineering": ("data engineering", "data engineer"),
    "Data Analysis": ("data analysis", "data analyst", "analytics"),
    "ETL": ("etl", "elt"),
    "Tableau": ("tableau",),
    "Power BI": ("power bi", "powerbi"),
    "Looker": ("looker",),
    "Excel": ("excel",),
    "Salesforce": ("salesforce",),
    "HubSpot": ("hubspot",),
    "SEO": ("seo",),
    "Agile": ("agile", "scrum"),
    "Product Management": ("product management", "product manager"),
    "Project Management": ("project management",),
    "Stakeholder Management": ("stakeholder management", "stakeholders"),
    "Communication": ("communication",),
    "English": ("english",),
    "Mandarin": ("mandarin", "chinese"),
}

_STOPWORDS = {
    "the", "and", "for", "with", "you", "your", "our", "are", "will", "that", "this",
    "have", "has", "from", "they", "their", "them", "who", "what", "when", "where",
    "which", "while", "work", "working", "role", "team", "teams", "job", "jobs", "about",
    "into", "over", "more", "than", "not", "but", "all", "any", "can", "use", "using",
    "years", "year", "experience", "strong", "good", "great", "well", "must", "should",
    "including", "include", "across", "within", "other", "also", "able", "new",
}

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9+#.\-']+")

MAX_SKILLS = 25


def extract_skills(text: str | None) -> list[str]:
    if not text:
        return []
    lowered = text.lower()
    found: list[str] = []
    for canonical, forms in SKILLS.items():
        for form in forms:
            pattern = re.compile(r"(?<![a-z0-9])" + re.escape(form) + r"(?![a-z0-9])")
            if pattern.search(lowered):
                found.append(canonical)
                break
    return found[:MAX_SKILLS]


def _tokens(text: str | None) -> list[str]:
    if not text:
        return []
    return [
        token.lower()
        for token in _WORD_RE.findall(text)
        if len(token) > 2 and token.lower() not in _STOPWORDS
    ]


def summarize(description: str | None, max_sentences: int = 3) -> str | None:
    """Small extractive summary: rank sentences by term frequency, keep order."""
    if not description:
        return None
    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(description) if s.strip()]
    if len(sentences) <= max_sentences:
        return " ".join(sentences) or None

    frequency = Counter(_tokens(description))
    scored: list[tuple[float, int, str]] = []
    for index, sentence in enumerate(sentences):
        words = _tokens(sentence)
        if not words:
            continue
        score = sum(frequency[word] for word in words) / (len(words) ** 0.5)
        scored.append((score, index, sentence))
    top = sorted(scored, key=lambda item: item[0], reverse=True)[:max_sentences]
    ordered = [sentence for _, _, sentence in sorted(top, key=lambda item: item[1])]
    return " ".join(ordered) or None


def _compute_recency_score(job: Any) -> float:
    """Freshness score (0-100) based on posting age."""
    posted = getattr(job, "posted_at", None) or getattr(job, "first_seen_at", None)
    if not posted:
        return 50.0
    if posted.tzinfo is None:
        posted = posted.replace(tzinfo=UTC)
    now = datetime.now(UTC)
    age = now - posted
    if age <= timedelta(days=2):
        return 100.0
    if age <= timedelta(days=7):
        return 85.0
    if age <= timedelta(days=14):
        return 70.0
    if age <= timedelta(days=30):
        return 50.0
    return 30.0


def match_resume(job: Any, resume_text: str) -> dict:
    """Score a job against a résumé (0-100) ranked by keyword coverage, title weight, and recency."""
    job_text = " ".join(
        str(part)
        for part in (
            getattr(job, "title", ""),
            getattr(job, "description", ""),
            " ".join(getattr(job, "skills", None) or []),
        )
        if part
    )
    job_skills = set(getattr(job, "skills", None) or extract_skills(job_text))
    resume_skills = set(extract_skills(resume_text))
    matched_skills = sorted(job_skills & resume_skills)
    missing_skills = sorted(job_skills - resume_skills)

    job_tokens = set(_tokens(job_text))
    resume_tokens = set(_tokens(resume_text))
    shared_keywords = sorted(job_tokens & resume_tokens)

    # 1. Keyword coverage: skills match + general keywords
    skill_coverage = len(matched_skills) / len(job_skills) if job_skills else (1.0 if not resume_skills else 0.0)
    kw_coverage = len(shared_keywords) / len(job_tokens) if job_tokens else 0.0
    keyword_coverage_score = round(100 * (0.65 * skill_coverage + 0.35 * kw_coverage), 1)

    # 2. Title weight: how strongly job title matches candidate skills & terms
    title = getattr(job, "title", "")
    title_tokens = set(_tokens(title))
    title_weight_score = (
        round(100 * (len(title_tokens & resume_tokens) / len(title_tokens)), 1)
        if title_tokens
        else 0.0
    )

    # 3. Recency score
    recency_score = _compute_recency_score(job)

    # Ranked combined score
    ranked_score = round(
        0.55 * keyword_coverage_score + 0.25 * title_weight_score + 0.20 * recency_score
    )
    score = min(max(ranked_score, 0), 100)

    return {
        "score": score,
        "matched_skills": matched_skills,
        "missing_skills": missing_skills[:10],
        "shared_keywords": shared_keywords[:15],
        "keyword_coverage_score": keyword_coverage_score,
        "title_weight_score": title_weight_score,
        "recency_score": recency_score,
    }


def enrich_job(job: Any) -> dict[str, Any]:
    """Compute stored enrichment fields for a job."""
    text = " ".join(
        str(part) for part in (getattr(job, "title", ""), getattr(job, "description", "")) if part
    )
    title = getattr(job, "title", None)
    return {
        "skills": extract_skills(text),
        "summary": summarize(getattr(job, "description", None)),
        "occupation_group": classify_occupation(title, getattr(job, "description", None)),
        "seniority": classify_seniority(title),
    }


__all__ = [
    "SKILLS",
    "classify_occupation",
    "classify_seniority",
    "enrich_job",
    "extract_skills",
    "match_resume",
    "summarize",
]
