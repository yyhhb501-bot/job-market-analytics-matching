"""Daily, locally persisted LinkedIn collection using a manually signed-in browser."""
import argparse
import datetime as dt
import fcntl
import json
import logging
import os
import re
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import schedule_state
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

ROOT = Path(os.environ.get('DATA_DIR', '/data'))
LOG = logging.getLogger('linkedin_daily')


def browser():
    options = webdriver.ChromeOptions()
    options.add_argument('--user-data-dir=/home/seluser/linkedin-profile')
    options.add_argument('--window-size=1440,1000')
    driver = webdriver.Remote(os.environ.get('SELENIUM_URL', 'http://browser:4444'), options=options)
    driver.set_page_load_timeout(60)
    return driver


def guard(driver):
    if re.search(r'/(login|checkpoint|authwall|challenge|uas)(/|\?|$)', driver.current_url):
        raise RuntimeError('LOGIN_REQUIRED: run login and complete sign-in at localhost:7900')
    body = driver.find_element(By.TAG_NAME, 'body').text[:5000]
    if re.search(r'quick security check|verify you.re a human|安全验证|安全检查', body, re.I):
        raise RuntimeError('LOGIN_REQUIRED: manual verification required')


def wait(driver, fn):
    def checked(d):
        guard(d)
        return fn(d)
    return WebDriverWait(driver, 30).until(checked)


def text(parent, selector):
    found = parent.find_elements(By.CSS_SELECTOR, selector)
    return found[0].text.strip() if found else ''


def database():
    db = sqlite3.connect(ROOT / 'jobs.sqlite3')
    db.execute('CREATE TABLE IF NOT EXISTS jobs (target TEXT, id TEXT, payload TEXT, PRIMARY KEY(target,id))')
    return db


def collect(driver, db, config, target):
    count = 0
    visited = set()
    for keyword in target['keywords']:
        for page in range(config['pages_per_keyword']):
            params = dict(keywords=keyword, geoId=target['geo_id'], start=page * 25,
                          sortBy='DD', f_TPR=f"r{config['lookback_days'] * 86400}")
            driver.get('https://www.linkedin.com/jobs/search/?' + urlencode(params))
            wait(driver, lambda d: d.find_elements(By.CSS_SELECTOR, 'li[data-occludable-job-id]') or
                 re.search(r'No matching jobs|No results found|没有找到符合|未找到.*职位', d.find_element(By.TAG_NAME, 'body').text, re.I))
            ids = [e.get_attribute('data-occludable-job-id') for e in driver.find_elements(By.CSS_SELECTOR, 'li[data-occludable-job-id]')]
            for job_id in ids:
                if not job_id or not job_id.isdigit() or job_id in visited:
                    continue
                visited.add(job_id)
                if db.execute('SELECT 1 FROM jobs WHERE target=? AND id=?', (target['name'], job_id)).fetchone():
                    continue
                selector = f'li[data-occludable-job-id="{job_id}"]'
                card = driver.find_element(By.CSS_SELECTOR, selector)
                driver.execute_script('arguments[0].scrollIntoView({block:"center"})', card)
                link = wait(driver, lambda d: d.find_element(By.CSS_SELECTOR, selector).find_elements(By.CSS_SELECTOR, 'a.job-card-list__title--link'))[0]
                title = text(link, 'strong') or link.text.strip()
                if not re.search(target['title_pattern'], title, re.I) or (target.get('exclude_pattern') and re.search(target['exclude_pattern'], title, re.I)):
                    continue
                job = dict(source='linkedin', source_job_id=job_id, title=title,
                           company=text(card, '.artdeco-entity-lockup__subtitle'),
                           location=text(card, '.artdeco-entity-lockup__caption'),
                           canonical_url=f'https://www.linkedin.com/jobs/view/{job_id}/',
                           target=target['name'], keyword=keyword)
                old_id = driver.find_elements(By.CSS_SELECTOR, 'h1 a')
                old_url = old_id[0].get_attribute('href') if old_id else ''
                old_description = text(driver, '#job-details')
                link.click()
                def detail(d):
                    anchors = d.find_elements(By.CSS_SELECTOR, 'h1 a')
                    description = text(d, '#job-details')
                    correct = anchors and f'/jobs/view/{job_id}' in anchors[0].get_attribute('href')
                    return description if correct and len(description) > 80 and (f'/jobs/view/{job_id}' in old_url or description != old_description) else False
                job['description'] = wait(driver, detail)
                job['collected_at'] = dt.datetime.now(dt.UTC).isoformat()
                with db:
                    db.execute('INSERT OR IGNORE INTO jobs VALUES (?,?,?)', (target['name'], job_id, json.dumps(job, ensure_ascii=False)))
                count += 1
                LOG.info('%s: saved %s %s', target['name'], count, title)
                if count >= config['max_jobs_per_target']:
                    return count
                time.sleep(config['delay_seconds'])
            next_buttons = driver.find_elements(By.CSS_SELECTOR, 'button[aria-label="View next page"],button[aria-label="查看下一页"]')
            if not ids or (next_buttons and not next_buttons[0].is_enabled()):
                break
            time.sleep(config['delay_seconds'])
    return count


def run(config, login=False, state=None):
    """Run one collection pass (or the interactive login).

    ``state`` must be the caller's CollectState (or None to load from disk):
    success/failure is recorded on that shared object and persisted here, so
    the caller never overwrites it with a stale copy.
    """
    # Kernel lock is released on process exit, including container crashes.
    with (ROOT / 'run.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another collection/login session is running')
        driver = browser()
        db = database()
        if state is None:
            state = schedule_state.load_state(ROOT)
        status = {'started_at': dt.datetime.now(dt.UTC).isoformat(), 'targets': {}}
        try:
            driver.get('https://www.linkedin.com/feed/')
            if login:
                LOG.info('Open http://localhost:7900 to sign in manually. Waiting up to 15 minutes.')
                WebDriverWait(driver, 900).until(lambda d: '/feed' in d.current_url and d.find_elements(By.ID, 'global-nav'))
                LOG.info('Login verified; browser profile saved.')
                schedule_state.record_success(state, dt.datetime.now(dt.UTC))
                return
            wait(driver, lambda d: d.find_elements(By.ID, 'global-nav'))
            for target in config['targets']:
                status['targets'][target['name']] = collect(driver, db, config, target)
            status['status'] = 'success'
            schedule_state.record_success(state, dt.datetime.now(dt.UTC))
        except Exception as exc:
            status.update(status='failed', error=str(exc))
            schedule_state.record_failure(state, dt.datetime.now(dt.UTC), str(exc))
            raise
        finally:
            for target in config['targets']:
                rows = [json.loads(row[0]) for row in db.execute('SELECT payload FROM jobs WHERE target=? ORDER BY id', (target['name'],))]
                out = ROOT / (target['name'] + '.json')
                temp = out.with_suffix('.tmp')
                try:
                    temp.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
                    temp.replace(out)
                except OSError:
                    LOG.exception('failed to write export %s', out)
            status['finished_at'] = dt.datetime.now(dt.UTC).isoformat()
            try:
                with (ROOT / 'runs.jsonl').open('a', encoding='utf-8') as f:
                    f.write(json.dumps(status, ensure_ascii=False) + '\n')
            except OSError:
                LOG.exception('failed to append runs.jsonl')
            try:
                schedule_state.save_state(ROOT, state)
            except OSError:
                LOG.exception('failed to persist collect-state.json')
            db.close()
            driver.quit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['schedule', 'once', 'login'])
    args = parser.parse_args()
    ROOT.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    config = json.loads(Path('config.json').read_text(encoding='utf-8'))
    if args.mode != 'schedule':
        # A manual run shares one state object end to end: success clears a
        # challenge pause, failure keeps the checkpoint and the pause reason.
        state = schedule_state.load_state(ROOT)
        schedule_state.record_attempt(state, dt.datetime.now(dt.UTC))
        schedule_state.save_state(ROOT, state)
        run(config, login=args.mode == 'login', state=state)
        return
    tz = ZoneInfo(config['timezone'])
    while True:
        now = dt.datetime.now(tz)
        state = schedule_state.load_state(ROOT)
        snapshot = state.to_dict()
        try:
            ran, reason = schedule_state.scheduled_cycle(
                state,
                now_local=now,
                now_utc=dt.datetime.now(dt.UTC),
                start_hour=config['hour'],
                start_minute=config['minute'],
                run_fn=lambda shared: run(config, state=shared),
            )
        except Exception:
            # run() already recorded the failure on the shared state and
            # saved it; keep the scheduler alive for the next backoff window.
            LOG.exception('Daily run failed; use once after resolving the problem')
            ran, reason = False, 'failed'
        if not ran and reason not in ('not due yet', 'already succeeded today'):
            LOG.info('collection held: %s', reason)
        if state.to_dict() != snapshot:
            # Write only when this tick changed something, so a manual run
            # landing inside this tick can never be clobbered by a stale copy.
            schedule_state.save_state(ROOT, state)
        time.sleep(30)


if __name__ == '__main__':
    main()
