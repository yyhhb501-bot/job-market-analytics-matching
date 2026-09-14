"""Worker CLI / scheduler.

Usage::

    python -m apps.worker.main init-db
    python -m apps.worker.main collect --source greenhouse --source lever
    python -m apps.worker.main collect --all --keywords "data engineer" --country US
    python -m apps.worker.main schedule --interval-minutes 60
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from apps.api.alerts import notify_saved_searches, run_active_saved_searches
from apps.api.config import get_settings
from apps.api.database import create_all, get_session_factory
from apps.worker.pipeline import RunStats, run_collector
from collectors.base import SearchParams
from collectors.registry import KNOWN_COLLECTORS, build_collectors

logger = logging.getLogger("jobagg.worker")


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _make_params(args: argparse.Namespace) -> SearchParams:
    extra: dict = {}
    if getattr(args, "sites", None):
        extra["sites"] = [site.strip() for site in args.sites.split(",") if site.strip()]
    return SearchParams(
        keywords=getattr(args, "keywords", None),
        location=getattr(args, "location", None),
        country=getattr(args, "country", None),
        results_wanted=getattr(args, "results", 50),
        remote_only=getattr(args, "remote_only", False),
        extra=extra,
    )


async def _run(args: argparse.Namespace) -> list[RunStats]:
    from apps.worker.tasks import expand_collector_specs, params_from_dict

    settings = get_settings()
    names = None if getattr(args, "all", False) else (args.source or None)
    collector_map = {c.name: c for c in build_collectors(settings, names)}
    if not collector_map:
        logger.warning(
            "No collectors available. Enable one via env flags "
            "(ENABLE_ATS/USAJOBS/JOBSPY/SEEK) and check --source names. Known: %s",
            ", ".join(KNOWN_COLLECTORS),
        )
        return []
    specs = [
        (name, spec)
        for name, spec in expand_collector_specs(
            settings, _make_params_dict(args), only_names=list(collector_map)
        )
    ]
    logger.info("running %s collection task(s)", len(specs))
    session_factory = get_session_factory()
    per_source: list[RunStats] = []
    total = RunStats(source="total")
    for name, spec in specs:
        stats = await run_collector(collector_map[name], params_from_dict(spec), session_factory)
        per_source.append(stats)
        total.merge(stats)
    for stats in per_source:
        logger.info("  %s: %s", stats.source, stats.as_dict())
    logger.info("TOTAL: %s", total.as_dict())
    return per_source


def _cmd_init_db(args: argparse.Namespace) -> int:
    create_all()
    logger.info("database schema created / verified")
    return 0


def _cmd_alerts(args: argparse.Namespace) -> int:
    settings = get_settings()
    with get_session_factory()() as session:
        results = run_active_saved_searches(session, lookback_hours=args.lookback_hours)
        for row in results:
            logger.info(
                "alert %s (#%s, %s): %s new / %s total",
                row["name"],
                row["saved_search_id"],
                row["frequency"],
                row["new_matches"],
                row["total_matches"],
            )
        notified = notify_saved_searches(session, settings, results)
    logger.info(
        "evaluated %s saved searches, sent %s email(s) and %s webhook(s)",
        len(results),
        notified.get("emails_sent", 0),
        notified.get("webhooks_sent", 0),
    )
    return 0


def _cmd_collect(args: argparse.Namespace) -> int:
    stats = asyncio.run(_run(args))
    failed = [s for s in stats if s.error]
    return 1 if stats and len(failed) == len(stats) else 0


def _cmd_schedule(args: argparse.Namespace) -> int:
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger

    settings = get_settings()

    def job() -> None:
        try:
            asyncio.run(_run(args))
        except Exception:  # noqa: BLE001
            logger.exception("scheduled collection failed")
        try:
            _cmd_alerts(args)
        except Exception:  # noqa: BLE001
            logger.exception("scheduled saved-search alert evaluation failed")

    create_all()
    scheduler = BlockingScheduler(timezone=settings.timezone)

    if args.interval_minutes is not None:
        trigger = IntervalTrigger(minutes=args.interval_minutes, timezone=settings.timezone)
        logger.info(
            "scheduler started: every %s minutes (%s)", args.interval_minutes, settings.timezone
        )
    elif str(settings.collect_schedule).lower() == "interval":
        trigger = IntervalTrigger(
            minutes=settings.collect_interval_minutes, timezone=settings.timezone
        )
        logger.info(
            "scheduler started: every %s minutes (%s)",
            settings.collect_interval_minutes,
            settings.timezone,
        )
    else:
        trigger = CronTrigger(
            hour=settings.collect_hour,
            minute=settings.collect_minute,
            timezone=settings.timezone,
        )
        logger.info(
            "scheduler started: daily at %02d:%02d (%s)",
            settings.collect_hour,
            settings.collect_minute,
            settings.timezone,
        )

    scheduler.add_job(job, trigger)
    job()
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("scheduler stopped")
    return 0


def _make_params_dict(args: argparse.Namespace) -> dict:
    params = _make_params(args)
    return {
        "keywords": params.keywords,
        "location": params.location,
        "country": params.country,
        "results_wanted": params.results_wanted,
        "remote_only": params.remote_only,
        "extra": params.extra,
    }


def _cmd_enqueue(args: argparse.Namespace) -> int:
    from apps.worker.tasks import collect_all, collect_source

    params = _make_params_dict(args)
    if args.all or not args.source:
        result = collect_all.delay(params)
        logger.info("enqueued collect_all: task id %s", result.id)
    else:
        for name in args.source:
            result = collect_source.delay(name, params)
            logger.info("enqueued collect_source(%s): task id %s", name, result.id)
    return 0


def _cmd_enrich(args: argparse.Namespace) -> int:
    from apps.worker.tasks import enrich_jobs_sync

    total = 0
    embedded = 0
    for _ in range(100):  # safety cap so a pathological batch can't loop forever
        result = enrich_jobs_sync(batch_size=args.batch_size)
        total += result["enriched"]
        embedded += result["embedded"]
        if result["enriched"] == 0 and result["embedded"] == 0:
            break
    logger.info("enriched %s jobs, embedded %s", total, embedded)
    return 0


def _cmd_enqueue_enrich(args: argparse.Namespace) -> int:
    from apps.worker.tasks import enrich_jobs

    result = enrich_jobs.delay(batch_size=args.batch_size)
    logger.info("enqueued enrich_jobs: task id %s", result.id)
    return 0


def _cmd_summaries(args: argparse.Namespace) -> int:
    from apps.worker.tasks import generate_summaries_sync

    total = 0
    while True:
        result = generate_summaries_sync(batch_size=args.batch_size)
        total += result["summarized"]
        if result["summarized"] < args.batch_size:
            break
    logger.info("generated %s LLM summaries", total)
    return 0


def _cmd_enqueue_summaries(args: argparse.Namespace) -> int:
    from apps.worker.tasks import generate_summaries

    result = generate_summaries.delay(batch_size=args.batch_size)
    logger.info("enqueued generate_summaries: task id %s", result.id)
    return 0


def _cmd_seed_demo(args: argparse.Namespace) -> int:
    """Insert a handful of sample jobs so the UI can be previewed offline."""
    import datetime as dt

    from apps.api.database import create_all
    from apps.worker.pipeline import persist_job
    from packages.job_schema import NormalizedJob

    create_all()
    now = dt.datetime.now(dt.UTC)
    samples = [
        ("greenhouse", "gh-1", "Senior Data Engineer", "Acme", "Build Python and Spark data pipelines on AWS.", "Austin", "TX", "US", "remote", "full_time", 140000, 180000, "USD", "year"),
        ("lever", "lv-2", "Backend Engineer (Go)", "Globex", "Design Go microservices on Kubernetes.", "Seattle", "WA", "US", "hybrid", "full_time", 130000, 160000, "USD", "year"),
        ("seek", "sk-3", "Data Analyst", "Oz Corp", "SQL dashboards and reporting for the Sydney team.", "Sydney", "NSW", "AU", "onsite", "full_time", 100000, 120000, "AUD", "year"),
        ("indeed", "in-4", "Frontend Engineer", "Initech", "React and TypeScript product work, fully remote.", "Remote", None, "US", "remote", "full_time", 120000, 150000, "USD", "year"),
        ("remoteok", "rk-5", "ML Engineer", "Hooli", "PyTorch models for recommendation systems.", "Remote", None, "US", "remote", "full_time", 150000, 190000, "USD", "year"),
        ("ashby", "as-6", "Product Manager", "Pied Piper", "Own the roadmap for our compression platform.", "Palo Alto", "CA", "US", "hybrid", "full_time", None, None, None, None),
        ("seek", "sk-7", "DevOps Engineer", "Woolworths Group", "Terraform and AWS platform engineering.", "Melbourne", "VIC", "AU", "hybrid", "full_time", 130000, 150000, "AUD", "year"),
        ("bamboohr", "bb-8", "Marketing Manager", "Vandelay", "Own growth marketing and SEO.", "New York", "NY", "US", "onsite", "full_time", 95000, 115000, "USD", "year"),
    ]
    session = get_session_factory()()
    try:
        for index, row in enumerate(samples):
            (
                source, source_id, title, company, description, city, state,
                country, remote, employment, smin, smax, currency, period,
            ) = row
            persist_job(
                session,
                NormalizedJob(
                    source=source,
                    source_job_id=source_id,
                    title=title,
                    company=company,
                    description=description,
                    city=city,
                    state=state,
                    country=country,
                    remote_type=remote,
                    employment_type=employment,
                    salary_min=smin,
                    salary_max=smax,
                    salary_currency=currency,
                    salary_period=period,
                    apply_url=f"https://example.com/jobs/{source_id}",
                    posted_at=now - dt.timedelta(days=index),
                ),
            )
        session.commit()
    finally:
        session.close()
    logger.info("seeded %s demo jobs", len(samples))
    return 0


def _cmd_boards_import(args: argparse.Namespace) -> int:
    from apps.api.boards import import_boards_from_json

    settings = get_settings()
    with get_session_factory()() as session:
        created = import_boards_from_json(session, settings)
    logger.info("imported %s boards from %s", created, settings.ats_companies_file)
    return 0


def _cmd_boards_verify(args: argparse.Namespace) -> int:
    from apps.api.boards import verify_all_boards

    settings = get_settings()
    with get_session_factory()() as session:
        result = asyncio.run(verify_all_boards(session, settings))
    logger.info("boards verify: %s", result)
    return 0


def _cmd_discover(args: argparse.Namespace) -> int:
    from sqlalchemy import select

    from apps.api.boards import discover_and_verify
    from apps.api.models import Board

    settings = get_settings()
    with get_session_factory()() as session:
        results = asyncio.run(discover_and_verify(args.domain, settings))
        created = 0
        for candidate in results:
            logger.info(
                "  %s/%s jobs=%s verified=%s",
                candidate["provider"],
                candidate["board_token"],
                candidate.get("job_count"),
                candidate.get("verified"),
            )
            if args.create and candidate.get("verified"):
                exists = session.scalar(
                    select(Board).where(
                        Board.provider == candidate["provider"],
                        Board.board_token == candidate["board_token"],
                    )
                )
                if exists is None:
                    session.add(
                        Board(
                            provider=candidate["provider"],
                            board_token=candidate["board_token"],
                            careers_url=candidate.get("careers_url"),
                            config=candidate.get("config") or {},
                            enabled=True,
                            discovery_source="discover",
                        )
                    )
                    created += 1
        session.commit()
    logger.info("discovered %s candidate(s), created %s", len(results), created)
    return 0


def _cmd_sweep(args: argparse.Namespace) -> int:
    from apps.worker.tasks import sweep_stale_jobs_sync

    result = sweep_stale_jobs_sync(days=args.days)
    logger.info("sweep: %s", result)
    return 0


def _cmd_enqueue_sweep(args: argparse.Namespace) -> int:
    from apps.worker.tasks import sweep_stale_jobs

    result = sweep_stale_jobs.delay(days=args.days)
    logger.info("enqueued sweep_stale_jobs: task id %s", result.id)
    return 0


def _cmd_reindex(args: argparse.Namespace) -> int:
    from apps.worker.tasks import reindex_jobs_sync

    result = reindex_jobs_sync(batch_size=args.batch_size)
    logger.info("reindex: %s", result)
    return 0


def _cmd_enqueue_reindex(args: argparse.Namespace) -> int:
    from apps.worker.tasks import reindex_jobs

    result = reindex_jobs.delay(batch_size=args.batch_size)
    logger.info("enqueued reindex_jobs: task id %s", result.id)
    return 0


def _cmd_enqueue_alerts(args: argparse.Namespace) -> int:
    from apps.worker.tasks import evaluate_alerts

    result = evaluate_alerts.delay(lookback_hours=args.lookback_hours)
    logger.info("enqueued evaluate_alerts: task id %s", result.id)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jobagg", description="Job aggregation worker")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="create database tables").set_defaults(func=_cmd_init_db)

    def add_collect_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--source", action="append", help="collector name (repeatable)")
        p.add_argument("--all", action="store_true", help="run every enabled collector")
        p.add_argument("--keywords", help="search keywords")
        p.add_argument("--location", help="location filter")
        p.add_argument("--country", help="US or AU (used by Indeed/JobSpy)")
        p.add_argument("--results", type=int, default=50, help="results wanted per source")
        p.add_argument("--sites", help="comma-separated JobSpy sites")
        p.add_argument("--remote-only", action="store_true")

    collect = sub.add_parser("collect", help="run a one-off collection")
    add_collect_args(collect)
    collect.set_defaults(func=_cmd_collect)

    schedule = sub.add_parser("schedule", help="run collections on an interval")
    add_collect_args(schedule)
    schedule.add_argument("--interval-minutes", type=int, default=None)
    schedule.add_argument("--lookback-hours", type=int, default=24)
    schedule.set_defaults(func=_cmd_schedule)

    alerts = sub.add_parser("alerts", help="evaluate saved searches for new matches")
    alerts.add_argument("--lookback-hours", type=int, default=24)
    alerts.set_defaults(func=_cmd_alerts)

    enqueue = sub.add_parser("enqueue", help="dispatch a collection to Celery/Redis")
    add_collect_args(enqueue)
    enqueue.set_defaults(func=_cmd_enqueue)

    enqueue_alerts = sub.add_parser(
        "enqueue-alerts", help="dispatch alert evaluation to Celery/Redis"
    )
    enqueue_alerts.add_argument("--lookback-hours", type=int, default=24)
    enqueue_alerts.set_defaults(func=_cmd_enqueue_alerts)

    enrich = sub.add_parser("enrich", help="backfill skills/summary for existing jobs")
    enrich.add_argument("--batch-size", type=int, default=500)
    enrich.set_defaults(func=_cmd_enrich)

    enqueue_enrich = sub.add_parser(
        "enqueue-enrich", help="dispatch enrichment to Celery/Redis"
    )
    enqueue_enrich.add_argument("--batch-size", type=int, default=500)
    enqueue_enrich.set_defaults(func=_cmd_enqueue_enrich)

    summaries = sub.add_parser("summaries", help="generate LLM summaries for jobs")
    summaries.add_argument("--batch-size", type=int, default=50)
    summaries.set_defaults(func=_cmd_summaries)

    enqueue_summaries = sub.add_parser(
        "enqueue-summaries", help="dispatch LLM summarization to Celery/Redis"
    )
    enqueue_summaries.add_argument("--batch-size", type=int, default=50)
    enqueue_summaries.set_defaults(func=_cmd_enqueue_summaries)

    seed_demo = sub.add_parser("seed-demo", help="insert sample jobs for previewing the UI")
    seed_demo.set_defaults(func=_cmd_seed_demo)

    boards_import = sub.add_parser(
        "boards-import", help="import config/ats_companies.json into the boards table"
    )
    boards_import.set_defaults(func=_cmd_boards_import)

    boards_verify = sub.add_parser("boards-verify", help="verify all boards and update status")
    boards_verify.set_defaults(func=_cmd_boards_verify)

    discover = sub.add_parser("discover", help="discover ATS boards for a company domain")
    discover.add_argument("--domain", required=True)
    discover.add_argument("--create", action="store_true")
    discover.set_defaults(func=_cmd_discover)

    sweep = sub.add_parser("sweep", help="mark stale jobs inactive")
    sweep.add_argument("--days", type=int, default=None)
    sweep.set_defaults(func=_cmd_sweep)

    enqueue_sweep = sub.add_parser(
        "enqueue-sweep", help="dispatch the stale-job sweep to Celery/Redis"
    )
    enqueue_sweep.add_argument("--days", type=int, default=None)
    enqueue_sweep.set_defaults(func=_cmd_enqueue_sweep)

    reindex = sub.add_parser("reindex", help="(re)index jobs into OpenSearch")
    reindex.add_argument("--batch-size", type=int, default=1000)
    reindex.set_defaults(func=_cmd_reindex)

    enqueue_reindex = sub.add_parser(
        "enqueue-reindex", help="dispatch reindexing to Celery/Redis"
    )
    enqueue_reindex.add_argument("--batch-size", type=int, default=1000)
    enqueue_reindex.set_defaults(func=_cmd_enqueue_reindex)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(getattr(args, "verbose", False))
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
