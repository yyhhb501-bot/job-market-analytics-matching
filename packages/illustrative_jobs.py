"""Fictional teaching examples, never persisted or counted as collected jobs."""

from apps.api.models import Job


def illustrative_jobs() -> list[Job]:
    rows = [
        (
            "Data Analyst",
            "US",
            "Austin",
            "remote",
            "Python SQL pandas Tableau statistics dashboards A/B testing business analysis.",
        ),
        (
            "Data Engineer",
            "US",
            "Seattle",
            "hybrid",
            "Python SQL ETL Airflow dbt AWS data warehouse pipelines.",
        ),
        (
            "Software Engineer",
            "US",
            "Boston",
            "onsite",
            "Python TypeScript React FastAPI Docker PostgreSQL backend development.",
        ),
        (
            "Data Analyst",
            "AU",
            "Sydney",
            "hybrid",
            "SQL Python Tableau Power BI statistics reporting business analysis.",
        ),
        (
            "Registered Nurse",
            "AU",
            "Melbourne",
            "onsite",
            "Registered Nurse AHPRA patient assessment acute care medication infection control.",
        ),
        (
            "Registered Nurse - Critical Care",
            "AU",
            "Sydney",
            "onsite",
            "Registered Nurse AHPRA ICU monitoring triage clinical documentation critical care.",
        ),
    ]
    return [
        Job(
            id=-(index + 1),
            source="illustrative_example",
            source_job_id=f"example-{index + 1}",
            title=title,
            company="虚构示例团队（非真实招聘）",
            country=country,
            city=city,
            remote_type=remote,
            description=description,
            is_active=True,
            visibility="public",
            collection_mode="illustrative",
            raw_payload={},
        )
        for index, (title, country, city, remote, description) in enumerate(rows)
    ]
