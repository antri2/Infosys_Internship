"""Adzuna live job source, and the fallback that must survive it.

Two required cases are covered here:

* CASE 1 -- Adzuna works: live jobs are returned, normalized, and scored by the
  existing profile matcher.
* CASE 2 -- Adzuna fails (missing creds, disabled, network error, timeout, HTTP
  error, non-JSON, empty results, malformed entries): the local 185-job
  pipeline is used instead and behaves exactly as before.

No test in this file touches the real network or MySQL: httpx is stubbed.
"""

import logging

import pytest

from services import adzuna_service, opportunity_service


RAW_ADZUNA_JOB = {
    "id": "12345678",
    "title": "Machine Learning Engineer",
    "company": {"display_name": "Infosys"},
    "location": {"display_name": "Bengaluru, Karnataka"},
    "description": "Build and ship recommendation models.",
    "category": {"label": "Engineering Jobs", "term": "engineering"},
    "contract_type": "Full time",
    "salary_min": 1200000,
    "salary_max": 1800000,
    "redirect_url": "https://www.adzuna.com/jobs/12345678",
    "created": "2026-09-01T00:00:00Z",
}


class _Response:
    def __init__(self, status_code=200, payload=None, raises=None):
        self.status_code = status_code
        self.reason_phrase = "OK"
        self._payload = payload
        self._raises = raises
        self.content = b"{}"

    def json(self):
        if self._raises is not None:
            raise self._raises
        return self._payload


@pytest.fixture
def fake_httpx(monkeypatch):
    """Replace httpx.get with a recording stub. Returns a config dict."""
    calls = {"get": []}
    box = {"response": _Response(payload={"count": 1, "results": [RAW_ADZUNA_JOB]})}

    def _get(url, params=None, timeout=None, follow_redirects=None):
        calls["get"].append({"url": url, "params": dict(params or {}), "timeout": timeout})
        result = box["response"]
        if isinstance(result, Exception):
            raise result
        return result

    fake = type("FakeHttpx", (), {"get": staticmethod(_get), "HTTPError": Exception})
    monkeypatch.setitem(__import__("sys").modules, "httpx", fake)
    return {"calls": calls, "box": box}


@pytest.fixture
def credentials(monkeypatch):
    monkeypatch.setattr(adzuna_service.config, "ADZUNA_ENABLED", True)
    monkeypatch.setattr(adzuna_service.config, "ADZUNA_APP_ID", "test-id")
    monkeypatch.setattr(adzuna_service.config, "ADZUNA_APP_KEY", "test-key")
    monkeypatch.setattr(adzuna_service.config, "ADZUNA_COUNTRY_CODE", "in")


# ------------------------------------------------------------- credentials ---


def test_not_configured_without_credentials(monkeypatch):
    monkeypatch.setattr(adzuna_service.config, "ADZUNA_ENABLED", True)
    monkeypatch.setattr(adzuna_service.config, "ADZUNA_APP_ID", "")
    monkeypatch.setattr(adzuna_service.config, "ADZUNA_APP_KEY", "")
    assert adzuna_service.is_configured() is False
    assert adzuna_service.search_jobs("ai engineer") == []


def test_not_configured_when_disabled(monkeypatch):
    monkeypatch.setattr(adzuna_service.config, "ADZUNA_ENABLED", False)
    monkeypatch.setattr(adzuna_service.config, "ADZUNA_APP_ID", "id")
    monkeypatch.setattr(adzuna_service.config, "ADZUNA_APP_KEY", "key")
    assert adzuna_service.is_configured() is False


def test_missing_credential_makes_no_network_call(monkeypatch):
    """Half-configured must not fire a request that could only 401."""
    monkeypatch.setattr(adzuna_service.config, "ADZUNA_ENABLED", True)
    monkeypatch.setattr(adzuna_service.config, "ADZUNA_APP_ID", "id")
    monkeypatch.setattr(adzuna_service.config, "ADZUNA_APP_KEY", "")
    called = []
    monkeypatch.setitem(__import__("sys").modules, "httpx",
                        type("H", (), {"get": staticmethod(lambda *a, **k: called.append(1))}))
    assert adzuna_service.search_jobs("ai engineer") == []
    assert called == []


# ------------------------------------------------------------ normalization ---


def test_normalize_maps_the_expected_fields():
    job = adzuna_service.normalize_result(RAW_ADZUNA_JOB)
    assert job["title"] == "Machine Learning Engineer"
    assert job["company"] == "Infosys"
    assert job["location"] == "Bengaluru, Karnataka"
    assert job["description"] == "Build and ship recommendation models."
    assert job["job_type"] == "Full Time"
    assert job["apply_link"] == "https://www.adzuna.com/jobs/12345678"
    assert job["source"] == "adzuna"
    assert "1,200,000" in job["stipend_or_salary"]


def test_normalize_supplies_every_key_the_template_reads():
    """The Opportunities UI is unchanged, so the shape must not change."""
    job = adzuna_service.normalize_result(RAW_ADZUNA_JOB)
    for key in (
        "job_id", "title", "company", "location", "job_type", "domain", "description",
        "responsibilities", "required_skills", "preferred_skills", "qualifications",
        "experience_required", "education_required", "stipend_or_salary", "apply_link",
    ):
        assert key in job, key


def test_normalize_rejects_unusable_entries():
    assert adzuna_service.normalize_result({"title": "", "company": "X"}) is None
    assert adzuna_service.normalize_result({"title": "X", "company": ""}) is None
    assert adzuna_service.normalize_result({"title": "X"}) is None
    assert adzuna_service.normalize_result("not a dict") is None


def test_live_job_id_is_a_stable_int_that_cannot_collide():
    """The Opportunities route calls int(job["job_id"]) on every row."""
    first = adzuna_service.normalize_result(RAW_ADZUNA_JOB)["job_id"]
    again = adzuna_service.normalize_result(RAW_ADZUNA_JOB)["job_id"]
    assert isinstance(first, int) and first == again
    assert first >= adzuna_service._ADZUNA_JOB_ID_OFFSET
    # A non-numeric Adzuna id must still yield a usable int.
    weird = adzuna_service.normalize_result({**RAW_ADZUNA_JOB, "id": "abc-123"})["job_id"]
    assert isinstance(weird, int)
    assert weird == adzuna_service.normalize_result({**RAW_ADZUNA_JOB, "id": "abc-123"})["job_id"]
    # Missing id must not raise.
    assert isinstance(adzuna_service.normalize_result({**RAW_ADZUNA_JOB, "id": None})["job_id"], int)


def test_requirements_come_from_the_listing_text_never_invented():
    """"Machine Learning Engineer" names its own skill in the title."""
    job = adzuna_service.normalize_result(RAW_ADZUNA_JOB)
    assert job["required_skills"] == "Machine Learning"
    # The description ("Build and ship recommendation models.") names no further
    # skill, so nothing else is added.
    assert "Python" not in job["required_skills"]
    assert job["preferred_skills"] == ""


def test_a_posting_naming_no_requirement_reports_none():
    """The honest answer for a posting with no readable requirements."""
    job = adzuna_service.normalize_result(
        {
            **RAW_ADZUNA_JOB,
            "title": "Business Operations Associate",
            "description": "An inclusive employer. We run technology systems.",
        }
    )
    assert job["required_skills"] == ""
    assert job["preferred_skills"] == ""
    assert job["education_required"] == ""
    assert job["experience_required"] == ""


def test_education_is_never_taken_from_the_category():
    job = adzuna_service.normalize_result(
        {**RAW_ADZUNA_JOB, "description": "An inclusive employer."}
    )
    # RAW_ADZUNA_JOB has category "Engineering Jobs"; that must not become an
    # education requirement.
    assert job["education_required"] != "Engineering Jobs"
    assert job["education_required"] == ""
    # It stays available as the job family instead.
    assert job["domain"] == "Engineering Jobs"


def test_job_type_never_says_live_listing():
    for raw in (
        RAW_ADZUNA_JOB,
        {**RAW_ADZUNA_JOB, "contract_time": None, "contract_type": None},
        {**RAW_ADZUNA_JOB, "title": "Marketing Internship", "contract_time": None},
    ):
        job_type = adzuna_service.normalize_result(raw)["job_type"].lower()
        assert "live" not in job_type


# ---------------------------------------------------------------- transport ---


def test_request_shape_uses_the_documented_url_and_params(fake_httpx, credentials):
    adzuna_service.search_jobs("AI Engineer", location="India", results_per_page=5)
    call = fake_httpx["calls"]["get"][0]
    assert call["url"] == "https://api.adzuna.com/v1/api/jobs/in/search/1"
    assert call["params"]["app_id"] == "test-id"
    assert call["params"]["app_key"] == "test-key"
    assert call["params"]["what"] == "AI Engineer"
    assert call["params"]["where"] == "India"
    assert call["params"]["results_per_page"] == 5
    assert call["timeout"] == adzuna_service.config.ADZUNA_TIMEOUT_SECONDS


def test_country_is_configurable(fake_httpx, credentials, monkeypatch):
    monkeypatch.setattr(adzuna_service.config, "ADZUNA_COUNTRY_CODE", "gb")
    adzuna_service.search_jobs("AI Engineer")
    assert fake_httpx["calls"]["get"][0]["url"].startswith(
        "https://api.adzuna.com/v1/api/jobs/gb/"
    )


def test_query_is_never_hardcoded(fake_httpx, credentials):
    adzuna_service.search_jobs("data scientist")
    assert fake_httpx["calls"]["get"][0]["params"]["what"] == "data scientist"


def test_blank_location_is_omitted(fake_httpx, credentials):
    adzuna_service.search_jobs("python", location="")
    assert "where" not in fake_httpx["calls"]["get"][0]["params"]


# ------------------------------------------------- CASE 2: every failure ---


@pytest.mark.parametrize(
    "response",
    [
        _Response(status_code=401),
        _Response(status_code=403),
        _Response(status_code=429),
        _Response(status_code=500),
        _Response(status_code=200, payload={"count": 0, "results": []}),
        _Response(status_code=200, payload={}),
        _Response(status_code=200, payload=[]),
        _Response(status_code=200, payload="nope"),
        _Response(status_code=200, payload={"results": "not-a-list"}),
        _Response(status_code=200, payload={"results": [{"title": "", "company": ""}]}),
        _Response(status_code=200, payload={"results": ["junk", 5, None]}),
        _Response(status_code=200, raises=ValueError("bad json")),
        RuntimeError("network down"),
        TimeoutError("timed out"),
    ],
)
def test_every_failure_mode_returns_empty_list(fake_httpx, credentials, response):
    fake_httpx["box"]["response"] = response
    assert adzuna_service.search_jobs("ai engineer") == []


def test_failures_never_leak_the_api_key(fake_httpx, credentials, caplog):
    """httpx can embed the credential-bearing URL in exception text."""
    fake_httpx["box"]["response"] = RuntimeError(
        "boom for https://api.adzuna.com/v1/api/jobs/in/search/1?app_id=test-id&app_key=SUPERSECRET"
    )
    with caplog.at_level(logging.DEBUG):
        assert adzuna_service.search_jobs("ai engineer") == []

    logged = caplog.text
    assert "SUPERSECRET" not in logged
    assert "test-key" not in logged
    assert "app_key" not in logged


def test_failures_never_leak_the_key_on_http_error(fake_httpx, credentials, caplog):
    fake_httpx["box"]["response"] = _Response(status_code=401)
    with caplog.at_level(logging.DEBUG):
        adzuna_service.search_jobs("ai engineer")
    assert "test-key" not in caplog.text
    assert "app_key" not in caplog.text


# ------------------------------------- CASE 1 + CASE 2 at the service level ---


def test_recommend_jobs_uses_live_results_when_available(fake_httpx, credentials, monkeypatch):
    monkeypatch.setattr(opportunity_service, "search_jobs", lambda *a, **k: pytest.fail("local pipeline must not run"))
    jobs = opportunity_service.recommend_jobs("machine learning", ["Python", "SQL"], top_k=5)
    assert len(jobs) == 1
    assert jobs[0]["source"] == "adzuna"
    assert jobs[0]["title"] == "Machine Learning Engineer"
    # Scored by the existing matcher, so the usual keys are present.
    for key in ("match_percent", "match_available", "matched_skills", "missing_skills", "match_reasons"):
        assert key in jobs[0]
    # The title names "Machine Learning", and the query skills include Python,
    # so fit is now calculable for a live job.
    assert jobs[0]["match_available"] is True
    assert "Machine Learning" in jobs[0]["missing_skills"]
    assert jobs[0]["match_percent"] is not None


@pytest.mark.parametrize(
    "response",
    [
        _Response(status_code=500),
        _Response(status_code=401),
        _Response(status_code=200, payload={"count": 0, "results": []}),
        _Response(status_code=200, raises=ValueError("bad json")),
        RuntimeError("network down"),
    ],
)
def test_recommend_jobs_falls_back_to_the_local_dataset(
    fake_httpx, credentials, monkeypatch, response
):
    """CASE 2: Adzuna is unusable, so the local pipeline must serve the results."""
    fake_httpx["box"]["response"] = response
    local_called = {}

    def _fake_local(query, top_k=20, min_score=None):
        local_called["query"] = query
        return [
            {
                "job_id": 7,
                "title": "Local Data Analyst Intern",
                "company": "Local Co",
                "location": "Pune",
                "required_skills": "SQL",
                "preferred_skills": "Python",
                "description": "d",
                "score": 0.8,
            }
        ]

    monkeypatch.setattr(opportunity_service, "search_jobs", _fake_local)

    jobs = opportunity_service.recommend_jobs("data analyst", ["SQL", "Python"], top_k=5)

    assert local_called, "the local FAISS pipeline was never used"
    assert len(jobs) == 1
    assert jobs[0]["title"] == "Local Data Analyst Intern"
    assert jobs[0]["source"] == "local"
    # Local jobs are still scored by the existing matcher.
    assert jobs[0]["match_percent"] is not None


def test_fallback_when_adzuna_is_not_configured(monkeypatch):
    monkeypatch.setattr(adzuna_service.config, "ADZUNA_ENABLED", False)
    monkeypatch.setattr(
        opportunity_service,
        "search_jobs",
        lambda *a, **k: [{
            "job_id": 1, "title": "T", "company": "C", "location": "L",
            "required_skills": "SQL", "description": "d",
        }],
    )
    jobs = opportunity_service.recommend_jobs("t", ["SQL"], top_k=3)
    assert jobs and jobs[0]["source"] == "local"


def test_local_results_are_unchanged_when_adzuna_is_off(monkeypatch):
    """Ranking of the 185-job pipeline must be identical to before."""
    monkeypatch.setattr(adzuna_service.config, "ADZUNA_ENABLED", False)
    candidates = [
        {"job_id": 1, "title": "A", "company": "C", "location": "L",
         "required_skills": "Python, SQL", "preferred_skills": "AWS", "description": "d", "score": 0.9},
        {"job_id": 2, "title": "B", "company": "C", "location": "L",
         "required_skills": "Java", "preferred_skills": "", "description": "d", "score": 0.7},
    ]
    monkeypatch.setattr(opportunity_service, "search_jobs", lambda *a, **k: candidates)
    jobs = opportunity_service.recommend_jobs("python", ["Python", "SQL"], top_k=5)
    assert [j["job_id"] for j in jobs] == [1, 2]
    assert jobs[0]["match_percent"] > jobs[1]["match_percent"]


def test_live_jobs_keep_provider_order_on_ties(fake_httpx, credentials):
    second = {**RAW_ADZUNA_JOB, "id": "222", "title": "Second"}
    third = {**RAW_ADZUNA_JOB, "id": "333", "title": "Third"}
    fake_httpx["box"]["response"] = _Response(
        payload={"count": 3, "results": [RAW_ADZUNA_JOB, second, third]}
    )
    jobs = opportunity_service.recommend_jobs("ml", [], top_k=10)
    assert [j["title"] for j in jobs] == ["Machine Learning Engineer", "Second", "Third"]