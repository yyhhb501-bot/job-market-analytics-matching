"""Build the set of collectors that should run for a given configuration."""

from __future__ import annotations

from apps.api.config import Settings
from collectors.base import BaseCollector

# Sources that are implemented but gated behind an explicit opt-in flag.
KNOWN_COLLECTORS: tuple[str, ...] = (
    "greenhouse",
    "lever",
    "ashby",
    "workable",
    "smartrecruiters",
    "recruitee",
    "breezy",
    "workday",
    "personio",
    "teamtailor",
    "bamboohr",
    "jazzhr",
    "pinpoint",
    "rippling",
    "jobvite",
    "usajobs",
    "jobspy",
    "adzuna",
    "remoteok",
    "seek",
)


def build_collectors(settings: Settings, names: list[str] | None = None) -> list[BaseCollector]:
    """Instantiate the enabled collectors (optionally filtered by ``names``)."""
    collectors: dict[str, BaseCollector] = {}

    if settings.enable_ats:
        from collectors.ats_adapters.ashby import AshbyCollector
        from collectors.ats_adapters.bamboohr import BambooHRCollector
        from collectors.ats_adapters.breezy import BreezyCollector
        from collectors.ats_adapters.greenhouse import GreenhouseCollector
        from collectors.ats_adapters.jazzhr import JazzHRCollector
        from collectors.ats_adapters.jobvite import JobviteCollector
        from collectors.ats_adapters.lever import LeverCollector
        from collectors.ats_adapters.personio import PersonioCollector
        from collectors.ats_adapters.pinpoint import PinpointCollector
        from collectors.ats_adapters.recruitee import RecruiteeCollector
        from collectors.ats_adapters.rippling import RipplingCollector
        from collectors.ats_adapters.smartrecruiters import SmartRecruitersCollector
        from collectors.ats_adapters.teamtailor import TeamtailorCollector
        from collectors.ats_adapters.workable import WorkableCollector
        from collectors.ats_adapters.workday import WorkdayCollector

        for factory in (
            GreenhouseCollector,
            LeverCollector,
            AshbyCollector,
            WorkableCollector,
            SmartRecruitersCollector,
            RecruiteeCollector,
            BreezyCollector,
            WorkdayCollector,
            PersonioCollector,
            TeamtailorCollector,
            BambooHRCollector,
            JazzHRCollector,
            PinpointCollector,
            RipplingCollector,
            JobviteCollector,
        ):
            collector = factory(settings)
            collectors[collector.name] = collector

    if settings.enable_usajobs:
        from collectors.usajobs_adapter import USAJobsCollector

        collector = USAJobsCollector(settings)
        collectors[collector.name] = collector

    if settings.enable_jobspy:
        from collectors.jobspy_adapter import JobSpyCollector

        collector = JobSpyCollector(settings)
        collectors[collector.name] = collector

    if settings.enable_adzuna:
        from collectors.adzuna_adapter import AdzunaCollector

        collector = AdzunaCollector(settings)
        collectors[collector.name] = collector

    if settings.enable_remoteok:
        from collectors.remoteok_adapter import RemoteOKCollector

        collector = RemoteOKCollector(settings)
        collectors[collector.name] = collector

    if settings.enable_seek:
        from collectors.seek_adapter import SeekCollector

        collector = SeekCollector(settings)
        collectors[collector.name] = collector

    if names:
        wanted = {name.lower() for name in names}
        collectors = {k: v for k, v in collectors.items() if k in wanted}

    return list(collectors.values())


__all__ = ["KNOWN_COLLECTORS", "build_collectors"]
