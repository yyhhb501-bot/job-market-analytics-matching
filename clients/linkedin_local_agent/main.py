"""CLI entrypoint for the local LinkedIn supplement collector.

Typical use::

    export JOBAGG_DEVICE_TOKEN=jagg_xxx
    python -m clients.linkedin_local_agent.main --config config.json

The collector:
1. reuses the user's logged-in Chrome profile (manual login on first run),
2. runs the city (onsite/hybrid) + country (remote) query matrix,
3. pre-filters by title and location *before* opening detail pages,
4. fetches full descriptions only for unseen, accepted jobs, and
5. uploads them to the platform import API (JSON), saving progress as it goes.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import random
import time
from pathlib import Path

from clients.linkedin_local_agent.browser.challenge import guard
from clients.linkedin_local_agent.browser.login import ensure_logged_in
from clients.linkedin_local_agent.browser.session import create_driver, open_url
from clients.linkedin_local_agent.config import AgentConfig, SearchConfig, load_config
from clients.linkedin_local_agent.filters.location import LocationFilter
from clients.linkedin_local_agent.filters.occupation import TitleFilter
from clients.linkedin_local_agent.models import CollectedJob, JobStub
from clients.linkedin_local_agent.parsing.job_detail import parse_detail
from clients.linkedin_local_agent.parsing.search_result import parse_search_results
from clients.linkedin_local_agent.search.geo_ids import validate_geo_id
from clients.linkedin_local_agent.search.pagination import (
    is_last_page,
    iter_start_offsets,
    page_key,
)
from clients.linkedin_local_agent.search.query_builder import Query, build_queries, build_search_url
from clients.linkedin_local_agent.storage.checkpoint import Checkpoint
from clients.linkedin_local_agent.storage.seen_jobs import (
    STATE_DISCOVERED,
    STATE_FAILED,
    STATE_FETCHED,
    STATE_FILTERED_LOCATION,
    STATE_FILTERED_TITLE,
    STATE_UPLOADED,
    SeenStore,
)
from clients.linkedin_local_agent.uploader.api_client import ImportClient, UploadError, chunked

logger = logging.getLogger("linkedin_agent")


def polite_sleep(search: SearchConfig) -> None:
    delay = max(search.delay_seconds, 0.0)
    jitter = max(search.delay_jitter_seconds, 0.0)
    time.sleep(delay + (random.random() * jitter if jitter else 0.0))


def _exclusions_by_group(config: AgentConfig) -> dict[str, list[str]]:
    return {group.name: group.exclusions for group in config.occupation_groups}


def config_problems(config: AgentConfig) -> list[str]:
    """Pre-flight checks that stop a run before it searches the wrong area."""
    problems: list[str] = []
    if not config.occupation_groups:
        problems.append("no occupation_groups configured")
    if not config.centers and not config.countries:
        problems.append("no locations.centers or locations.countries configured")
    for center in config.centers:
        if not validate_geo_id(center.geo_id):
            problems.append(
                f"center {center.city or center.state} has an invalid geo_id "
                f"{center.geo_id!r}; copy it from the LinkedIn jobs URL (geoId=...)"
            )
    for country in config.countries:
        if not validate_geo_id(country.geo_id):
            problems.append(f"country {country.country} has an invalid geo_id {country.geo_id!r}")
    return problems


class LocalCollector:
    def __init__(self, config: AgentConfig, *, dry_run: bool = False) -> None:
        self.config = config
        self.dry_run = dry_run
        data_dir = config.storage.resolved_data_dir
        data_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir = data_dir
        self.seen = SeenStore.load(data_dir / "seen.json")
        self.checkpoint = Checkpoint.load(data_dir / "checkpoint.json")
        self.exclusions = _exclusions_by_group(config)

    # -- crawling ---------------------------------------------------------
    def _fetch_html(self, driver, url: str) -> str:
        open_url(driver, url)
        guard(driver, self.config.browser.challenge_timeout)
        # Read the source *after* any challenge is cleared so we parse real content.
        return driver.page_source

    def collect(self, driver, max_queries: int | None = None) -> list[JobStub]:
        queries = build_queries(self.config)
        if max_queries:
            queries = queries[:max_queries]
        accepted: list[JobStub] = []
        run_keys: set[str] = set()

        for query in queries:
            location_filter = LocationFilter(
                country=query.country,
                state=query.state,
                city=query.city,
                channel=query.channel,
            )
            title_filter = TitleFilter(self.exclusions.get(query.occupation_group or "", []))
            logger.info("searching %s", query.label)
            for start in iter_start_offsets(
                self.config.search.results_per_page, self.config.search.max_pages_per_query
            ):
                key = page_key(query, start)
                if self.checkpoint.is_page_done(key):
                    continue
                html = self._fetch_html(driver, build_search_url(query, start, self.config.search))
                stubs = parse_search_results(html)
                self._process_page(query, stubs, location_filter, title_filter, accepted, run_keys)
                self.checkpoint.mark_page_done(key)
                self.checkpoint.save()
                self.seen.save()
                if is_last_page(len(stubs), self.config.search.results_per_page):
                    break
                polite_sleep(self.config.search)
        return accepted

    def _process_page(
        self,
        query: Query,
        stubs: list[JobStub],
        location_filter: LocationFilter,
        title_filter: TitleFilter,
        accepted: list[JobStub],
        run_keys: set[str],
    ) -> None:
        for stub in stubs:
            stub.geo_id = query.geo_id
            stub.channel = query.channel
            if self.seen.is_blocked(stub):
                continue
            if any(k in run_keys for k in stub.dedup_keys()):
                continue
            if title_filter.excluded(stub.title):
                self.seen.mark(stub, STATE_FILTERED_TITLE)
                continue
            if not location_filter.accepts(stub):
                self.seen.mark(stub, STATE_FILTERED_LOCATION)
                continue
            self.seen.mark(stub, STATE_DISCOVERED)
            run_keys.update(stub.dedup_keys())
            accepted.append(stub)
        self.checkpoint.bump("discovered", len(stubs))

    # -- detail + upload --------------------------------------------------
    def fetch_details(self, driver, stubs: list[JobStub]) -> list[CollectedJob]:
        collected: list[CollectedJob] = []
        budget = max(self.config.search.max_detail_fetches, 0)
        for stub in stubs:
            if budget and len(collected) >= budget:
                logger.info("detail fetch budget reached (%s)", budget)
                break
            try:
                html = self._fetch_html(driver, stub.url)
                collected.append(parse_detail(stub, html))
                self.seen.mark(stub, STATE_FETCHED)
            except Exception as exc:  # noqa: BLE001 - one page must not kill the run
                logger.warning("detail fetch failed for %s: %s", stub.job_id, exc)
                self.seen.mark(stub, STATE_FAILED)
            self.checkpoint.bump("fetched", 1)
            self.checkpoint.save()
            self.seen.save()
            polite_sleep(self.config.search)
        return collected

    def upload(self, collected: list[CollectedJob]) -> dict:
        if not collected:
            return {"accepted_count": 0, "duplicate_count": 0, "rejected_count": 0}
        payloads = [job.to_payload(self.config.source) for job in collected]
        if self.dry_run:
            out = self.data_dir / f"collected-{dt.datetime.now(dt.UTC):%Y%m%d-%H%M%S}.json"
            out.write_text(json.dumps(payloads, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info("dry run: wrote %s jobs to %s", len(payloads), out)
            return {"accepted_count": len(payloads), "duplicate_count": 0, "rejected_count": 0}

        token = self.config.resolve_token()
        if not token:
            raise RuntimeError(
                f"no device token; set {self.config.device_token_env} or device_token in config"
            )
        totals = {"accepted_count": 0, "duplicate_count": 0, "rejected_count": 0}
        by_id = {job.stub.job_id: job for job in collected}
        with ImportClient(self.config.api_base_url, token, source=self.config.source) as client:
            for batch in chunked(payloads):
                batch_ids = [payload["source_job_id"] for payload in batch]
                result = client.upload(batch)
                for name in totals:
                    totals[name] += int(result.get(name, 0))
                self.checkpoint.mark_uploaded(batch_ids)
                for job_id in batch_ids:
                    job = by_id.get(job_id)
                    if job is not None:
                        self.seen.mark(job.stub, STATE_UPLOADED)
                self.checkpoint.bump("uploaded", len(batch))
                self.checkpoint.save()
                self.seen.save()
        return totals


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local LinkedIn supplement collector")
    parser.add_argument(
        "--config",
        default=str(Path("~/.jobagg/linkedin-collector/config.json").expanduser()),
        help="path to the JSON config",
    )
    parser.add_argument("--dry-run", action="store_true", help="collect but do not upload")
    parser.add_argument("--max-queries", type=int, default=None, help="cap the query matrix")
    parser.add_argument("--list-queries", action="store_true", help="print queries and exit")
    parser.add_argument("--reset-checkpoint", action="store_true", help="clear resume state")
    parser.add_argument("--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    config = load_config(args.config)
    if args.list_queries:
        for query in build_queries(config):
            print(query.label)
        return 0

    problems = config_problems(config)
    if problems:
        for problem in problems:
            logger.error("config: %s", problem)
        return 2

    collector = LocalCollector(config, dry_run=args.dry_run)
    if args.reset_checkpoint:
        collector.checkpoint.reset()
        collector.checkpoint.save()

    driver = create_driver(config.browser)
    try:
        ensure_logged_in(driver, config.browser.challenge_timeout)
        accepted = collector.collect(driver, max_queries=args.max_queries)
        logger.info("discovered %s new accepted jobs", len(accepted))
        collected = collector.fetch_details(driver, accepted)
        logger.info("fetched %s full job descriptions", len(collected))
        try:
            totals = collector.upload(collected)
        except UploadError as exc:
            logger.error("%s", exc)
            return 2
        logger.info("upload totals: %s", totals)
    finally:
        driver.quit()
        collector.checkpoint.save()
        collector.seen.save()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
