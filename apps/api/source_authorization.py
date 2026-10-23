from __future__ import annotations

from datetime import datetime

from sqlalchemy import and_, func, or_, select

from apps.api.models import Job, SourceAuthorization, utcnow


def public_job_condition(job=Job, *, now: datetime | None = None):
    at = now if now is not None else utcnow()
    authorization = (
        select(SourceAuthorization.id)
        .where(
            SourceAuthorization.source == job.source,
            or_(
                SourceAuthorization.source_board_id.is_(None),
                SourceAuthorization.source_board_id == job.source_board_id,
            ),
            SourceAuthorization.approved.is_(True),
            SourceAuthorization.commercial_display.is_(True),
            func.length(func.trim(SourceAuthorization.evidence_ref)) > 0,
            SourceAuthorization.valid_from <= at,
            or_(SourceAuthorization.valid_until.is_(None), SourceAuthorization.valid_until > at),
        )
        .correlate(job)
        .exists()
    )
    return and_(job.visibility == "public", authorization)
