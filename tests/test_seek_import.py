from __future__ import annotations

import datetime as dt


def test_seek_live_progress_requires_device_identity_and_does_not_import(client, session):
    from sqlalchemy import select, func
    from apps.api.models import ImportBatch
    assert client.get('/api/v1/import/seek/progress').status_code == 401
    devices=[client.post('/api/v1/import/devices',json={'name':name,'owner':name}).json()
             for name in ['live-a','live-b']]
    for index, device in enumerate(devices):
        client.post('/api/v1/import/jobs',headers={'Authorization':f"Bearer {device['token']}"},
                    json={'source':'seek_user_import','jobs':[_daily_job(900001001+index)]})
    headers={'Authorization':f"Bearer {devices[0]['token']}"}
    client.post('/api/v1/import/jobs',headers=headers,json={'source':'linkedin_user_import',
                'jobs':[_daily_job(800001001,'linkedin_user_import')]})
    before=session.scalar(select(func.count()).select_from(ImportBatch))
    result=client.get('/api/v1/import/seek/progress',headers=headers)
    assert result.status_code == 200
    progress=result.json()
    assert progress['today_valid'] == progress['hour_valid'] == 1
    assert progress['today_target'] == 600
    assert progress['hour_limit'] == 50
    assert progress['timezone'] == 'Asia/Shanghai'
    assert dt.datetime.fromisoformat(progress['checked_at'].replace('Z','+00:00')).tzinfo is not None
    assert session.scalar(select(func.count()).select_from(ImportBatch)) == before


def test_seek_live_progress_is_fresh_across_beijing_midnight(client, session, monkeypatch):
    from sqlalchemy import select
    from apps.api.models import Job
    import apps.api.routers.import_jobs as router
    device=client.post('/api/v1/import/devices',json={'name':'live-midnight','owner':'local'}).json()
    headers={'Authorization':f"Bearer {device['token']}"}
    client.post('/api/v1/import/jobs',headers=headers,json={'source':'seek_user_import','jobs':[_daily_job(900001003)]})
    boundary=dt.datetime(2026,10,21,16,tzinfo=dt.UTC)
    job=session.scalar(select(Job))
    job.first_seen_at=boundary-dt.timedelta(minutes=2)
    session.commit()
    monkeypatch.setattr(router,'utcnow',lambda:boundary-dt.timedelta(minutes=1))
    assert client.get('/api/v1/import/seek/progress',headers=headers).json()['today_valid']==1
    monkeypatch.setattr(router,'utcnow',lambda:boundary+dt.timedelta(minutes=1))
    progress=client.get('/api/v1/import/seek/progress',headers=headers).json()
    assert progress['today_valid']==progress['hour_valid']==0
    assert progress['today_target']==600


def _daily_job(job_id, source="seek_user_import"):
    return {"source":source,"source_job_id":str(job_id),"title":f"Registered Nurse - Unit {job_id}",
        "company":f"Hospital {job_id}","country":"AU","state":"NSW","city":"Sydney",
        "description":"Provide clinical care and maintain accurate patient documentation. " * 5,
        "posted_at":dt.datetime.now(dt.UTC).isoformat(),
        "canonical_url":f"https://au.seek.com/job/{job_id}" if source=="seek_user_import" else f"https://www.linkedin.com/jobs/view/{job_id}/"}


def test_seek_quota_ignores_linkedin_from_same_device_and_isolates_other_devices(client):
    from packages.seek_policy import SEEK_DAILY_TARGET
    assert SEEK_DAILY_TARGET == 600
    device=client.post('/api/v1/import/devices',json={'name':'mixed','owner':'local'}).json()
    headers={'Authorization':f"Bearer {device['token']}"}
    linkedin=client.post('/api/v1/import/jobs',headers=headers,json={'source':'linkedin_user_import',
        'jobs':[_daily_job(800000000+i,'linkedin_user_import') for i in range(50)]}).json()
    assert linkedin['accepted_count']==50
    seek=client.post('/api/v1/import/jobs',headers=headers,json={'source':'seek_user_import','jobs':[_daily_job(900000001)]}).json()
    assert seek['accepted_count']==1
    assert seek['progress']['today_target']==600
    other=client.post('/api/v1/import/devices',json={'name':'other','owner':'other'}).json()
    client.post('/api/v1/import/jobs',headers={'Authorization':f"Bearer {other['token']}"},
        json={'source':'seek_user_import','jobs':[_daily_job(900000002)]})
    # A duplicate on the first device returns its own progress, not another device's hour.
    again=client.post('/api/v1/import/jobs',headers=headers,json={'source':'seek_user_import','jobs':[_daily_job(900000001)]}).json()
    assert again['duplicate_count']==1
    assert again['progress']['today_valid']==1
    assert again['progress']['hour_valid']==1


def test_seek_quota_and_progress_roll_over_at_beijing_midnight(client,session,monkeypatch):
    from sqlalchemy import select
    from apps.api.models import Job,JobImportProvenance
    import apps.api.import_gateway as gateway
    import apps.api.routers.import_jobs as router
    device=client.post('/api/v1/import/devices',json={'name':'midnight','owner':'local'}).json()
    client.post('/api/v1/import/jobs',headers={'Authorization':f"Bearer {device['token']}"},
        json={'source':'seek_user_import','jobs':[_daily_job(900000003),_daily_job(900000004)]})
    boundary=dt.datetime(2026,10,19,16,tzinfo=dt.UTC)
    now=boundary+dt.timedelta(minutes=2)
    rows=session.scalars(select(Job).order_by(Job.id)).all()
    provenance=session.scalars(select(JobImportProvenance).order_by(JobImportProvenance.id)).all()
    for index in range(2):
        stamp=boundary+dt.timedelta(minutes=1 if index else -1)
        rows[index].first_seen_at=stamp;provenance[index].created_at=stamp
    session.commit()
    monkeypatch.setattr(router,'utcnow',lambda:now)
    assert gateway._seek_quota_counts(session,device['id'],now)==(1,1)
    assert router._seek_progress(session,device['id'])['today_valid']==1
    assert gateway._utc_bounds(now)[0]==boundary


def test_seek_accepts_600th_unique_job_and_defers_601st(client,monkeypatch):
    import apps.api.import_gateway as gateway
    # Simulate 599 prior unique admissions; exercise the real upload transaction
    # at the boundary without manufacturing unrelated database fixtures.
    monkeypatch.setattr(gateway,'_seek_quota_counts',lambda *args,**kwargs:(599,0))
    device=client.post('/api/v1/import/devices',json={'name':'boundary','owner':'local'}).json()
    result=client.post('/api/v1/import/jobs',headers={'Authorization':f"Bearer {device['token']}"},
        json={'source':'seek_user_import','jobs':[_daily_job(900000005),_daily_job(900000006)]}).json()
    assert result['accepted_count']==1
    assert result['rejected_count']==1
    assert 'daily_target_reached' in result['errors'][0]['reason']


def test_seek_import_accepts_all_search_result_titles_when_requested(client):
    device = client.post("/api/v1/import/devices", json={"name": "seek-all", "owner": "local"}).json()
    response = client.post("/api/v1/import/jobs",
        headers={"Authorization": f"Bearer {device['token']}"},
        json={"source": "seek_user_import", "jobs": [{
            "source": "seek_user_import", "source_job_id": "987654323",
            "title": "Clinical Assessor Delegate", "company": "Example Health",
            "description": "Assess client needs, coordinate care and maintain accurate documentation. " * 4,
            "country": "AU", "state": "QLD", "city": "Brisbane",
            "canonical_url": "https://au.seek.com/job/987654323",
            "posted_at": dt.datetime.now(dt.UTC).isoformat(),
            "raw_payload": {"collection_scope": "all_search_results"}
        }]})
    assert response.status_code == 200
    assert response.json()["accepted_count"] == 1
    assert response.json()["rejected_count"] == 0


def test_seek_import_applies_registered_nurse_policy_and_reports_progress(client):
    device = client.post(
        "/api/v1/import/devices", json={"name": "seek-edge", "owner": "nurse"}
    ).json()
    payload = {
        "source": "seek_user_import",
        "jobs": [
            {
                "source": "seek_user_import",
                "source_job_id": "987654321",
                "title": "Registered Nurse - Community Care",
                "company": "Example Health",
                "description": "Provide clinical assessments, medication management and person-centred nursing care in the community. Coordinate with families and the multidisciplinary team and maintain accurate clinical documentation for every visit.",
                "country": "AU",
                "state": "NSW",
                "city": "Sydney",
                "employment_type": "Full time",
                "canonical_url": "https://www.seek.com.au/job/987654321",
                "posted_at": (dt.datetime.now(dt.UTC) - dt.timedelta(days=2)).isoformat(),
                "raw_payload": {"detail_status": "complete", "shift_information": "day shift"},
            }
        ],
    }
    response = client.post(
        "/api/v1/import/jobs",
        headers={"Authorization": f"Bearer {device['token']}"},
        json=payload,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["accepted_count"] == 1
    assert body["rejected_count"] == 0
    assert body["progress"]["today_valid"] == 1
    assert body["progress"]["hour_valid"] == 1


def test_seek_import_rejects_incomplete_or_out_of_scope_job(client):
    device = client.post(
        "/api/v1/import/devices", json={"name": "seek-edge", "owner": "nurse"}
    ).json()
    response = client.post(
        "/api/v1/import/jobs",
        headers={"Authorization": f"Bearer {device['token']}"},
        json={
            "source": "seek_user_import",
            "jobs": [
                {
                    "source": "seek_user_import",
                    "source_job_id": "987654322",
                    "title": "Enrolled Nurse",
                    "company": "Example Health",
                    "description": "Short teaser",
                    "country": "AU",
                    "state": "NSW",
                    "city": "Sydney",
                    "canonical_url": "https://www.seek.com.au/job/987654322",
                }
            ],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["accepted_count"] == 0
    assert body["rejected_count"] == 1
    assert "SEEK validation failed" in body["errors"][0]["reason"]
