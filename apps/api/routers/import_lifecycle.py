"""Device-scoped observations from original job detail pages."""
import re
from datetime import datetime, timedelta
from typing import Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.database import get_db
from apps.api.models import CollectorDevice, Job, utcnow
from apps.api.security import require_device_token

router = APIRouter(prefix="/import", tags=["import"])
CLOSED = re.compile(r"no longer accepting applications|job is no longer available|job has expired|job has closed|position has been filled|this job is no longer advertised|不再接受.{0,5}申请|停止招聘|职位已关闭", re.I)


class Observation(BaseModel):
    source: Literal['seek_user_import', 'linkedin_user_import']
    source_job_id: str = Field(pattern=r'^\d+$', max_length=80)
    status: Literal['active', 'closed', 'unknown']
    checked_at: datetime
    url: str = Field(max_length=2000)
    evidence: str = Field(default='', max_length=2000)


class Observations(BaseModel):
    observations: list[Observation] = Field(min_length=1, max_length=100)


@router.post('/observations')
def observe(payload: Observations, device: CollectorDevice = Depends(require_device_token),
            db: Session = Depends(get_db)):
    updated = ignored = 0
    for item in payload.observations:
        if item.checked_at.tzinfo is None or item.checked_at > utcnow() + timedelta(minutes=5):
            raise HTTPException(422, 'invalid observation time')
        url = urlparse(item.url)
        hosts = {'www.linkedin.com'} if item.source == 'linkedin_user_import' else {'au.seek.com', 'www.seek.com.au', 'seek.com.au'}
        path = f'/jobs/view/{item.source_job_id}' if item.source == 'linkedin_user_import' else f'/job/{item.source_job_id}'
        if url.scheme != 'https' or url.hostname not in hosts or url.path.rstrip('/') != path:
            raise HTTPException(422, 'observation must match the original job URL')
        if item.status == 'closed' and not CLOSED.search(item.evidence):
            raise HTTPException(422, 'explicit closed evidence is required')
        if item.status == 'active' and not item.evidence.startswith('detail-and-apply:'):
            raise HTTPException(422, 'active detail and apply evidence is required')
        row = db.scalar(select(Job).where(Job.source == item.source,
            Job.source_job_id == item.source_job_id, Job.owner_device_id == device.id,
            Job.visibility == 'private'))
        if row is None:
            ignored += 1
            continue
        raw = dict(row.raw_payload or {})
        previous = raw.get('lifecycle') or {}
        prior = datetime.fromisoformat(previous['checked_at']) if previous.get('checked_at') else None
        if prior and item.checked_at <= prior:
            ignored += 1
            continue
        raw['lifecycle'] = item.model_dump(mode='json')
        row.raw_payload = raw
        if item.status == 'closed':
            row.is_active = False
            row.closed_at = item.checked_at
            row.inactive_reason = 'source_confirmed_closed'
        elif item.status == 'active':
            row.is_active = True
            row.closed_at = None
            row.inactive_reason = None
            row.last_seen_at = item.checked_at
        row.updated_at = utcnow()
        updated += 1
    db.commit()
    return {'updated': updated, 'ignored': ignored}
