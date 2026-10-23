from datetime import timedelta

from apps.api.models import utcnow
from tests.test_import_gateway import auth, create_device, sample_job


def test_observations_are_scoped_ordered_and_replay_cannot_reopen(client):
    device = create_device(client)
    other = create_device(client, name='other')
    job = sample_job(source_job_id='123', canonical_url='https://www.linkedin.com/jobs/view/123/')
    client.post('/api/v1/import/jobs', headers=auth(device['token']), json={'jobs':[job]})
    now = utcnow()
    observation = {'source':'linkedin_user_import', 'source_job_id':'123', 'status':'closed',
        'url':job['canonical_url'], 'checked_at':now.isoformat(), 'evidence':'No longer accepting applications'}

    def send(item, token=device['token']):
        return client.post('/api/v1/import/observations', headers=auth(token), json={'observations':[item]})

    assert send(observation, other['token']).json()['updated'] == 0
    assert send({**observation, 'evidence':'page load timed out'}).status_code == 422
    assert send({**observation, 'url':'https://www.linkedin.com/jobs/view/999/'}).status_code == 422
    assert send(observation).json()['updated'] == 1
    assert client.get('/api/v1/import/admin').json()['jobs']['total'] == 0
    closed = client.get('/api/v1/import/admin?job_status=closed').json()['jobs']['items'][0]['job']
    assert closed['is_active'] is False
    assert closed['review_status'] == 'closed'
    assert closed['last_checked_at']
    client.post('/api/v1/import/jobs', headers=auth(device['token']), json={'jobs':[job]})
    assert client.get('/api/v1/import/admin?job_status=closed').json()['jobs']['total'] == 1
    active = {**observation, 'status':'active', 'evidence':'detail-and-apply:Senior Data Analyst'}
    assert send({**active, 'checked_at':(now-timedelta(seconds=1)).isoformat()}).json()['updated'] == 0
    assert send({**active, 'checked_at':(now+timedelta(seconds=1)).isoformat()}).json()['updated'] == 1
    assert client.get('/api/v1/import/admin').json()['jobs']['total'] == 1
    assert send({**observation, 'status':'unknown', 'evidence':'blank page',
        'checked_at':(now+timedelta(seconds=2)).isoformat()}).json()['updated'] == 1
    assert client.get('/api/v1/import/admin?job_status=pending').json()['jobs']['total'] == 1
    assert client.get('/api/v1/import/admin').json()['jobs']['total'] == 1


def test_observation_requires_device_token(client):
    assert client.post('/api/v1/import/observations', json={'observations':[]}).status_code == 401
