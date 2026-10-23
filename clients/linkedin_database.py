"""Local staging database for LinkedIn JSON exports; no external connections."""
import argparse
import datetime as dt
import hashlib
import json
import sqlite3
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parents[1] / 'data/linkedin/positions.sqlite3'


def connect(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA journal_mode=WAL')
    db.executescript('''
    CREATE TABLE IF NOT EXISTS batches (
      id INTEGER PRIMARY KEY, sha256 TEXT UNIQUE NOT NULL, filename TEXT NOT NULL,
      imported_at TEXT NOT NULL, raw_json TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS positions (
      job_id TEXT PRIMARY KEY, title TEXT NOT NULL, company TEXT, description TEXT,
      location TEXT, search_country TEXT, search_state TEXT, search_city TEXT,
      occupation_group TEXT, occupation_soc TEXT, occupation_anzsco TEXT,
      url TEXT, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
      lifecycle_status TEXT NOT NULL DEFAULT 'active', possibly_closed_at TEXT);
    CREATE TABLE IF NOT EXISTS observations (
      batch_id INTEGER NOT NULL REFERENCES batches(id), job_id TEXT NOT NULL REFERENCES positions(job_id),
      raw_json TEXT NOT NULL, PRIMARY KEY(batch_id,job_id));
    CREATE TABLE IF NOT EXISTS coverage_queries (
      batch_id INTEGER NOT NULL REFERENCES batches(id), query_id TEXT NOT NULL,
      status TEXT NOT NULL, country TEXT, location_id TEXT, location_name TEXT,
      state TEXT, occupation_group TEXT, keyword TEXT, workplace TEXT,
      result_count INTEGER, saved_count INTEGER, last_error TEXT,
      started_at TEXT, finished_at TEXT, raw_json TEXT NOT NULL,
      PRIMARY KEY(batch_id, query_id));
    CREATE INDEX IF NOT EXISTS positions_country ON positions(search_country);
    CREATE INDEX IF NOT EXISTS positions_last_seen ON positions(last_seen);
    PRAGMA user_version=2;
    ''')
    # Existing staging databases predate the coverage fields.  Upgrade them
    # in place without dropping any local data.
    columns = {row[1] for row in db.execute('PRAGMA table_info(positions)')}
    additions = {
        'search_state': 'TEXT', 'search_city': 'TEXT', 'occupation_group': 'TEXT',
        'occupation_soc': 'TEXT', 'occupation_anzsco': 'TEXT',
        'lifecycle_status': "TEXT NOT NULL DEFAULT 'active'", 'possibly_closed_at': 'TEXT'
    }
    for name, definition in additions.items():
        if name not in columns:
            db.execute(f'ALTER TABLE positions ADD COLUMN {name} {definition}')
    db.execute('CREATE INDEX IF NOT EXISTS positions_possible_closed ON positions(possibly_closed_at)')
    db.commit()
    return db


def timestamp(value, fallback):
    if not value:
        return fallback
    parsed = dt.datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('collected_at must include timezone')
    return parsed.astimezone(dt.UTC).isoformat()


def ingest(db, path):
    content = Path(path).read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    if db.execute('SELECT 1 FROM batches WHERE sha256=?', (digest,)).fetchone():
        return {'file': str(path), 'already_imported': True}
    raw = content.decode('utf-8-sig')
    payload = json.loads(raw)
    jobs = payload if isinstance(payload, list) else payload.get('jobs')
    if not isinstance(jobs, list):
        raise ValueError('Expected a jobs array or an object containing jobs')
    config = payload.get('config', {}) if isinstance(payload, dict) else {}
    now = dt.datetime.now(dt.UTC).isoformat()
    added = 0
    with db:
        batch = db.execute('INSERT INTO batches(sha256,filename,imported_at,raw_json) VALUES(?,?,?,?)',
                           (digest, str(Path(path).resolve()), now, raw)).lastrowid
        for job in jobs:
            job_id = str(job.get('source_job_id', job.get('job_id', '')))
            title = job.get('title')
            if not job_id.isdigit() or not isinstance(title, str) or not title.strip():
                raise ValueError(f'Invalid job id/title: {job_id}; batch rolled back')
            seen = timestamp(job.get('collected_at'), now)
            extra = job.get('raw_payload') or {}
            country = {'usa': 'US', 'australia': 'AU', 'melbourne': 'AU', 'sydney': 'AU', 'austin': 'US'}.get(config.get('location'))
            country = country or {'103644278':'US','101452733':'AU','100992797':'AU'}.get(str(extra.get('linkedin_geo_id')))
            country = country or extra.get('search_country') or job.get('country')
            state = job.get('state') or extra.get('search_state')
            city = job.get('city') or extra.get('search_city')
            occupation = job.get('occupation_group') or extra.get('occupation_group')
            soc = job.get('occupation_soc') or extra.get('soc_major')
            anzsco = job.get('occupation_anzsco') or extra.get('anzsco_major')
            observed_lifecycle = job.get('lifecycle_status') or (
                'possibly_closed' if job.get('possibly_closed_at') else
                'closed' if job.get('closed') is True else
                'active' if job.get('closed') is False else None)
            lifecycle = observed_lifecycle or 'active'
            possibly_closed = job.get('possibly_closed_at')
            old = db.execute('SELECT * FROM positions WHERE job_id=?', (job_id,)).fetchone()
            if not old:
                db.execute('''INSERT INTO positions
                    (job_id,title,company,description,location,search_country,search_state,search_city,
                     occupation_group,occupation_soc,occupation_anzsco,url,first_seen,last_seen,
                     lifecycle_status,possibly_closed_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (job_id,title,job.get('company'),job.get('description'),job.get('location') or extra.get('search_location'),
                     country,state,city,occupation,soc,anzsco,job.get('canonical_url'),seen,seen,lifecycle,possibly_closed))
                added += 1
            else:
                newer = seen >= old['last_seen']
                db.execute('''UPDATE positions SET title=?,company=?,description=?,location=?,search_country=?,search_state=?,search_city=?,
                    occupation_group=?,occupation_soc=?,occupation_anzsco=?,url=?,first_seen=?,last_seen=?,
                    lifecycle_status=?,possibly_closed_at=? WHERE job_id=?''', (
                    title if newer else old['title'],
                    (job.get('company') or old['company']) if newer else old['company'],
                    (job.get('description') or old['description']) if newer or not old['description'] else old['description'],
                    (job.get('location') or extra.get('search_location') or old['location']) if newer else old['location'],
                    country or old['search_country'], state or old['search_state'], city or old['search_city'],
                    occupation or old['occupation_group'], soc or old['occupation_soc'], anzsco or old['occupation_anzsco'],
                    job.get('canonical_url') or old['url'], min(seen,old['first_seen']),max(seen,old['last_seen']),
                    lifecycle if newer and observed_lifecycle else old['lifecycle_status'],
                    (None if lifecycle == 'active' else possibly_closed) if newer and observed_lifecycle else old['possibly_closed_at'], job_id))
            db.execute('INSERT OR REPLACE INTO observations VALUES(?,?,?)',(batch,job_id,json.dumps(job,ensure_ascii=False)))
        query_rows = payload.get('queries', []) if isinstance(payload, dict) else []
        for query in query_rows:
            if not isinstance(query, dict) or not query.get('id'):
                continue
            db.execute('''INSERT OR REPLACE INTO coverage_queries
                (batch_id,query_id,status,country,location_id,location_name,state,occupation_group,keyword,workplace,
                 result_count,saved_count,last_error,started_at,finished_at,raw_json)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (
                batch, str(query['id']), str(query.get('status') or 'unknown'), query.get('country'), query.get('locationId'),
                query.get('locationName'), query.get('state'), query.get('occupationId'), query.get('keyword'), query.get('workplace'),
                query.get('resultCount'), query.get('savedCount'), query.get('lastError'), query.get('startedAt'), query.get('finishedAt'),
                json.dumps(query, ensure_ascii=False)))
    return {'file':str(path),'records':len(jobs),'new':added,'existing':len(jobs)-added,'coverage_queries':len(query_rows) if isinstance(payload, dict) else 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', default=str(DEFAULT_DB))
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('init')
    imp = sub.add_parser('import')
    imp.add_argument('files', nargs='+')
    query = sub.add_parser('query')
    query.add_argument('--country', choices=['US','AU'])
    query.add_argument('--keyword', default='')
    query.add_argument('--limit', type=int, default=20)
    sub.add_parser('stats')
    args = parser.parse_args()
    db = connect(args.db)
    try:
        if args.command == 'import':
            result = [ingest(db, path) for path in args.files]
        elif args.command == 'query':
            result = [dict(r) for r in db.execute('SELECT * FROM positions WHERE (? IS NULL OR search_country=?) AND title LIKE ? ORDER BY last_seen DESC LIMIT ?', (args.country,args.country,'%'+args.keyword+'%',max(1,min(args.limit,1000))))]
        elif args.command == 'stats':
            result = {'jobs':db.execute('SELECT count(*) FROM positions').fetchone()[0], 'batches':db.execute('SELECT count(*) FROM batches').fetchone()[0],
                      'coverage_queries':db.execute('SELECT count(*) FROM coverage_queries').fetchone()[0],
                      'possibly_closed':db.execute("SELECT count(*) FROM positions WHERE lifecycle_status='possibly_closed' OR possibly_closed_at IS NOT NULL").fetchone()[0]}
        else:
            result = {'database':str(Path(args.db).resolve())}
        print(json.dumps(result,ensure_ascii=False,indent=2))
    finally:
        db.close()


if __name__ == '__main__':
    main()
