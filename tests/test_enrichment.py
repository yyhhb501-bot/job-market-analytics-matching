from __future__ import annotations

from types import SimpleNamespace

from packages.enrichment import enrich_job, extract_skills, match_resume, summarize


def test_extract_skills():
    skills = extract_skills("We use Python, AWS and PostgreSQL every day")
    assert "Python" in skills
    assert "AWS" in skills
    assert "PostgreSQL" in skills


def test_extract_skills_empty():
    assert extract_skills(None) == []
    assert extract_skills("") == []


def test_summarize_limits_sentences():
    text = " ".join(f"Sentence {i} about engineering work." for i in range(10))
    summary = summarize(text, max_sentences=3)
    assert summary
    assert len([part for part in summary.split(".") if part.strip()]) <= 3


def test_match_resume_scores_overlap():
    job = SimpleNamespace(
        title="Python Engineer",
        description="Python AWS Docker",
        skills=["Python", "AWS", "Docker"],
    )
    result = match_resume(job, "I am a Python developer who knows AWS well")
    assert result["score"] > 0
    assert "Python" in result["matched_skills"]
    assert "Docker" in result["missing_skills"]


def test_enrich_job_fields():
    job = SimpleNamespace(title="Data Engineer", description="Python and Spark pipelines")
    enriched = enrich_job(job)
    assert "Python" in enriched["skills"]
    assert enriched["summary"]
