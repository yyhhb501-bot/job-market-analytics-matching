from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from apps.api.config import Settings
from collectors.adzuna_adapter import AdzunaCollector
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
from collectors.ats_adapters.workday import WorkdayCollector
from collectors.base import CollectorError
from collectors.remoteok_adapter import RemoteOKCollector
from collectors.seek_adapter import SeekCollector
from collectors.usajobs_adapter import USAJobsCollector
from collectors.utils import infer_country, parse_salary_range, split_location


def test_split_location_with_state_code():
    assert split_location("Sydney, NSW") == ("Sydney", "NSW")
    assert split_location("Melbourne VIC") == ("Melbourne", "VIC")
    assert split_location("Austin, TX") == ("Austin", "TX")


def test_infer_country():
    assert infer_country("Sydney, NSW") == "AU"
    assert infer_country("Austin, TX") == "US"
    assert infer_country("Remote") is None


def test_parse_salary_range_with_default_currency():
    assert parse_salary_range("$120k - $140k", default_currency="AUD") == (
        120000.0,
        140000.0,
        "AUD",
        None,
    )
    assert parse_salary_range("USD 90,000 - 110,000 per year") == (
        90000.0,
        110000.0,
        "USD",
        "year",
    )


def test_greenhouse_parse():
    collector = GreenhouseCollector(Settings())
    job = collector._parse(
        "acme",
        {
            "id": 123,
            "title": "Backend Engineer",
            "location": {"name": "Sydney, NSW"},
            "absolute_url": "https://boards.greenhouse.io/acme/jobs/123",
            "content": "&lt;p&gt;Hello&lt;/p&gt;",
            "updated_at": "2026-01-01T00:00:00Z",
        },
    )
    assert job is not None
    assert job.source == "greenhouse"
    assert job.country == "AU"
    assert job.city == "Sydney"
    assert job.state == "NSW"
    assert job.description == "Hello"


def test_lever_parse():
    collector = LeverCollector(Settings())
    job = collector._parse(
        "acme",
        {
            "id": "lev-1",
            "text": "Data Scientist",
            "hostedUrl": "https://jobs.lever.co/acme/lev-1",
            "createdAt": 1735689600000,
            "categories": {"location": "Remote", "commitment": "Full-time"},
            "descriptionPlain": "Do data things",
            "salaryRange": {"min": 100000, "max": 130000, "currency": "USD", "interval": "per-year-salary"},
        },
    )
    assert job is not None
    assert job.salary_min == 100000
    assert job.salary_max == 130000
    assert job.salary_currency == "USD"


def test_seek_parse():
    collector = SeekCollector(Settings())
    job = collector._parse(
        {
            "id": "777",
            "title": "Data Analyst",
            "advertiser": {"description": "Acme"},
            "location": "Melbourne VIC",
            "salary": "$120k - $140k",
            "listingDate": "2026-02-01T00:00:00Z",
            "workType": "Full time",
            "teaser": "<b>Great</b> role",
        }
    )
    assert job is not None
    assert job.country == "AU"
    assert job.city == "Melbourne"
    assert job.salary_min == 120000
    assert job.salary_currency == "AUD"


def test_usajobs_requires_credentials():
    collector = USAJobsCollector(Settings(usajobs_email=None, usajobs_api_key=None))
    with pytest.raises(CollectorError):
        collector.validate()


def test_adzuna_parse():
    collector = AdzunaCollector(Settings())
    job = collector._parse(
        "US",
        {
            "id": "3916209483",
            "title": "Senior Data Engineer",
            "company": {"display_name": "Acme"},
            "location": {"area": ["US", "Texas", "Austin"], "display_name": "Austin, Texas"},
            "description": "<strong>Great</strong> role",
            "redirect_url": "https://www.adzuna.com/land/ad/3916209483",
            "created": "2026-02-01T12:00:00Z",
            "salary_min": 120000,
            "salary_max": 150000,
            "contract_time": "full_time",
            "contract_type": "permanent",
        },
    )
    assert job is not None
    assert job.source == "adzuna"
    assert job.country == "US"
    assert job.city == "Austin"
    assert job.state == "Texas"
    assert job.salary_currency == "USD"
    assert job.employment_type == "full_time"
    assert job.description == "Great role"


def test_smartrecruiters_parse():
    collector = SmartRecruitersCollector(Settings())
    job = collector._parse(
        "Acme",
        {
            "id": "744000012345",
            "name": "Senior Backend Engineer",
            "company": {"name": "Acme"},
            "location": {"city": "Austin", "region": "TX", "country": "us", "remote": False},
            "releasedDate": "2026-01-01T00:00:00.000Z",
            "typeOfEmployment": {"label": "Full-time"},
        },
        detail={"jobAd": {"sections": {"jobDescription": {"text": "<p>Build APIs</p>"}}}},
    )
    assert job is not None
    assert job.source == "smartrecruiters"
    assert job.country == "US"
    assert job.city == "Austin"
    assert job.state == "TX"
    assert job.employment_type == "full_time"
    assert job.description == "Build APIs"


def test_recruitee_parse():
    collector = RecruiteeCollector(Settings())
    job = collector._parse(
        "sendcloud",
        {
            "id": 42,
            "title": "Data Analyst",
            "city": "Sydney",
            "state_name": "New South Wales",
            "country_code": "AU",
            "description": "<p>Analyse things</p>",
            "created_at": "2026-02-01T10:00:00Z",
            "careers_url": "https://sendcloud.recruitee.com/o/data-analyst",
            "careers_apply_url": "https://sendcloud.recruitee.com/o/data-analyst/c/new",
            "employment_type_code": "fulltime",
            "remote": True,
            "salary": {"min": "90000", "max": "110000", "currency": "AUD", "period": "year"},
        },
    )
    assert job is not None
    assert job.source == "recruitee"
    assert job.country == "AU"
    assert job.city == "Sydney"
    assert job.remote_type == "remote"
    assert job.salary_min == 90000
    assert job.salary_currency == "AUD"


def test_breezy_parse():
    collector = BreezyCollector(Settings())
    job = collector._parse(
        "acme",
        {
            "_id": "abc123",
            "name": "Product Manager",
            "location": {
                "city": "Denver",
                "state": {"name": "Colorado"},
                "country": {"name": "United States"},
                "is_remote": False,
            },
            "type": {"name": "Full-Time"},
            "description": "<p>Own the roadmap</p>",
            "published_date": "2026-02-02T00:00:00Z",
            "url": "https://acme.breezy.hr/p/abc123",
        },
    )
    assert job is not None
    assert job.source == "breezy"
    assert job.country == "US"
    assert job.city == "Denver"
    assert job.state == "Colorado"
    assert job.employment_type == "full_time"
    assert job.description == "Own the roadmap"


def test_workday_parse():
    collector = WorkdayCollector(Settings())
    job = collector._parse(
        "nvidia",
        "wd5",
        "NVIDIAExternalCareerSite",
        {
            "title": "Software Engineer",
            "externalPath": "/job/Remote/Software-Engineer_JR1",
            "locationsText": "Remote, US",
        },
        {
            "jobPostingInfo": {
                "jobDescription": "<p>Build GPUs</p>",
                "location": "Santa Clara, CA",
                "externalUrl": "https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/job/Remote/Software-Engineer_JR1",
                "startDate": "2026-01-01",
                "timeType": "Full time",
                "remoteType": "Remote",
            }
        },
    )
    assert job is not None
    assert job.source == "workday"
    assert job.country == "US"
    assert job.remote_type == "remote"
    assert job.employment_type == "full_time"
    assert job.description == "Build GPUs"


def test_personio_parse():
    collector = PersonioCollector(Settings())
    position = ET.fromstring(
        """
        <position>
          <id>123</id>
          <subcompany>Acme GmbH</subcompany>
          <office>Berlin</office>
          <name>Backend Engineer</name>
          <employmentType>permanent</employmentType>
          <schedule>full-time</schedule>
          <createdAt>2026-01-01T00:00:00+00:00</createdAt>
          <jobDescriptions>
            <jobDescription>
              <name>Tasks</name>
              <value><![CDATA[<p>Build APIs</p>]]></value>
            </jobDescription>
          </jobDescriptions>
        </position>
        """
    )
    job = collector._parse("acme", "jobs.personio.de", position)
    assert job is not None
    assert job.source == "personio"
    assert job.title == "Backend Engineer"
    assert job.city == "Berlin"
    assert job.company == "Acme GmbH"
    assert job.description == "Build APIs"
    assert job.employment_type == "full_time"


def test_teamtailor_parse():
    collector = TeamtailorCollector(Settings())
    job = collector._parse(
        "acme",
        {
            "id": "987",
            "attributes": {
                "title": "DevOps Engineer",
                "body": "<p>Own the infra</p>",
                "city": "Austin",
                "country-code": "US",
                "careersite-job-url": "https://acme.teamtailor.com/jobs/987-devops-engineer",
                "created-at": "2026-01-05T08:00:00.000Z",
                "remote-status": "fully_remote",
                "employment-type": "full-time",
            },
        },
    )
    assert job is not None
    assert job.source == "teamtailor"
    assert job.country == "US"
    assert job.city == "Austin"
    assert job.remote_type == "remote"
    assert job.employment_type == "full_time"
    assert job.description == "Own the infra"


def test_bamboohr_parse():
    collector = BambooHRCollector(Settings())
    job = collector._parse(
        "acme",
        "https://acme.bamboohr.com",
        {
            "id": "27",
            "jobOpeningName": "Sealing Specialist",
            "employmentStatusLabel": "Full-Time",
            "location": {"city": "Paducah", "state": "Kentucky"},
            "atsLocation": {
                "country": "United States",
                "state": "Kentucky",
                "province": None,
                "city": "Paducah",
            },
            "isRemote": None,
        },
        {
            "result": {
                "jobOpening": {
                    "description": "<p>Do sales</p>",
                    "requirements": "<p>2 years</p>",
                    "postedDate": "2026-01-01T00:00:00Z",
                }
            }
        },
    )
    assert job is not None
    assert job.source == "bamboohr"
    assert job.country == "US"
    assert job.city == "Paducah"
    assert job.state == "Kentucky"
    assert "Do sales" in job.description
    assert job.employment_type == "full_time"


def test_jazzhr_parse():
    collector = JazzHRCollector(Settings())
    job = collector._parse(
        {"api_key": "key", "board": "acme.applytojob.com"},
        {
            "id": "123",
            "title": "Fiber Technician",
            "description": "<p>Install fiber</p>",
            "city": "Austin",
            "state": "TX",
            "country_id": "US",
            "employment_type": "Full-Time",
            "board_code": "abc123",
            "original_open_date": "2026-01-01T00:00:00Z",
        },
    )
    assert job is not None
    assert job.source == "jazzhr"
    assert job.country == "US"
    assert job.city == "Austin"
    assert job.apply_url == "https://acme.applytojob.com/apply/abc123"
    assert job.description == "Install fiber"


def test_pinpoint_parse():
    collector = PinpointCollector(Settings())
    job = collector._parse(
        "workwithus",
        {
            "id": "53913",
            "title": "Senior Marketing Designer",
            "description": "<p>Design things</p>",
            "url": "https://workwithus.pinpointhq.com/en/postings/9447",
            "workplace_type": "remote",
            "location": {"id": "5495", "name": "United Kingdom"},
            "employment_type": "Full-Time",
            "created_at": "2026-01-01T00:00:00Z",
        },
    )
    assert job is not None
    assert job.source == "pinpoint"
    assert job.remote_type == "remote"
    assert job.city == "United Kingdom"
    assert job.description == "Design things"


def test_rippling_parse():
    collector = RipplingCollector(Settings())
    job = collector._parse(
        "spreeai",
        {
            "id": "abc",
            "name": "Frontend Engineer",
            "url": "https://ats.rippling.com/spreeai/jobs/abc",
            "locations": [
                {
                    "city": "San Francisco",
                    "stateCode": "CA",
                    "countryCode": "US",
                    "workplaceType": "HYBRID",
                }
            ],
        },
        {
            "description": {"company": "<p>About the company</p>", "role": "<p>Build the UI</p>"},
            "employmentType": {"id": "Salaried, Full-Time"},
            "createdOn": "2026-02-17T10:00:00-08:00",
            "companyName": "SpreeAI",
        },
    )
    assert job is not None
    assert job.source == "rippling"
    assert job.country == "US"
    assert job.city == "San Francisco"
    assert job.state == "CA"
    assert job.remote_type == "hybrid"
    assert job.employment_type == "full_time"
    assert "Build the UI" in job.description


def test_jobvite_parse():
    collector = JobviteCollector(Settings())
    job = collector._parse(
        {"api": "key", "sc": "secret", "site": "ezra"},
        {
            "id": "123",
            "title": "Account Manager",
            "description": "<p>Own accounts</p>",
            "city": "New York",
            "state": "NY",
            "country": "United States",
            "jobType": "Full-Time",
            "datePosted": "2026-01-01",
        },
    )
    assert job is not None
    assert job.source == "jobvite"
    assert job.apply_url == "https://jobs.jobvite.com/ezra/job/123/apply"
    assert job.country == "US"
    assert job.employment_type == "full_time"
    assert job.description == "Own accounts"


def test_remoteok_parse():
    collector = RemoteOKCollector(Settings())
    job = collector._parse(
        {
            "id": "123",
            "position": "Senior Backend Engineer",
            "company": "Acme",
            "location": "Worldwide",
            "description": "<p>Build things</p>",
            "salary_min": 120000,
            "salary_max": 160000,
            "date": "2026-02-01T00:00:00+00:00",
            "url": "https://remoteok.com/remote-jobs/123",
        }
    )
    assert job is not None
    assert job.source == "remoteok"
    assert job.remote_type == "remote"
    assert job.salary_currency == "USD"
    assert job.description == "Build things"


def test_adzuna_requires_credentials():
    collector = AdzunaCollector(Settings(adzuna_app_id=None, adzuna_app_key=None))
    with pytest.raises(CollectorError):
        collector.validate()
