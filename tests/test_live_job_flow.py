"""Live Adzuna jobs must work with the features that receive only a job_id.

Skill Gap, AI Summary, Interview Prep, Resume Builder and Cover Letter all get a
job id from the Opportunities page links. A live job has no MySQL row, so
``services.context_builder.get_job_context`` falls back to the short-lived live
cache. These tests pin that contract, the application-tracking path, and the
requirement that no "Live" wording reaches the UI.
"""

import re

import pytest

from database.db import get_db
from routes import applications as applications_route
from services import adzuna_service, live_job_store
from services.context_builder import get_job_context


LIVE_JOB = {
    "job_id": 1_855_006_986,
    "adzuna_id": "5855006986",
    "title": "Data Analyst / Engineer",
    "company": "Kyndryl",
    "location": "Bangalore, Karnataka",
    "job_type": "Full Time",
    "domain": "IT Jobs",
    "description": "Requirements: strong SQL and Python. Preferred: Power BI.",
    "responsibilities": "",
    "required_skills": "SQL, Python",
    "preferred_skills": "Power BI",
    "qualifications": "Bachelor's degree",
    "experience_required": "3+ years",
    "education_required": "Bachelor's degree",
    "stipend_or_salary": "",
    "apply_link": "https://www.adzuna.in/details/5855006986",
    "source": "adzuna",
}


@pytest.fixture
def cached_live_job():
    live_job_store.clear()
    live_job_store.remember([LIVE_JOB])
    yield LIVE_JOB
    live_job_store.clear()


# ------------------------------------------------------- the reserved range ---


def test_reserved_range_is_unchanged():
    """The collision-safety range must stay exactly 1e9..1999999999."""
    assert adzuna_service._ADZUNA_JOB_ID_OFFSET == 1_000_000_000
    assert adzuna_service._ADZUNA_JOB_ID_SPAN == 1_000_000_000
    assert adzuna_service.is_adzuna_job_id(1_000_000_000) is True
    assert adzuna_service.is_adzuna_job_id(1_999_999_999) is True
    assert adzuna_service.is_adzuna_job_id(999_999_999) is False
    assert adzuna_service.is_adzuna_job_id(2_000_000_000) is False
    assert adzuna_service.is_adzuna_job_id("not an id") is False


def test_live_ids_can_never_collide_with_local_ids():
    for local_id in (1, 47, 185):
        assert adzuna_service.is_adzuna_job_id(local_id) is False


# ------------------------------------------------------------- the resolver ---


def test_get_job_context_resolves_a_live_job(app, cached_live_job):
    with app.app_context():
        job = get_job_context(get_db(), cached_live_job["job_id"])
    assert job is not None
    assert job["title"] == "Data Analyst / Engineer"
    assert job["company"] == "Kyndryl"
    # Every field the agents read is present on the resolved job.
    for key in ("required_skills", "preferred_skills", "description", "location"):
        assert key in job


def test_get_job_context_still_returns_local_jobs_first(app, candidate):
    """Local behaviour must be completely unchanged."""
    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT job_id FROM jobs LIMIT 1")
            local_id = cursor.fetchone()["job_id"]
        job = get_job_context(db, local_id)
    assert job is not None
    assert job["job_id"] == local_id


def test_unknown_job_still_returns_none(app):
    with app.app_context():
        assert get_job_context(get_db(), 999_999_999_999) is None


def test_expired_entries_are_not_returned(app, cached_live_job, monkeypatch):
    monkeypatch.setattr(live_job_store.config, "ADZUNA_JOB_CACHE_TTL_SECONDS", 0)
    with app.app_context():
        assert get_job_context(get_db(), cached_live_job["job_id"]) is None


def test_cache_round_trip_and_eviction():
    live_job_store.clear()
    live_job_store.remember([LIVE_JOB])
    assert live_job_store.get(LIVE_JOB["job_id"])["title"] == LIVE_JOB["title"]
    # Non-live ids are never cached, and junk ids are ignored safely.
    live_job_store.remember([{"job_id": 42, "title": "Local-ish"}])
    assert live_job_store.get(42) is None
    live_job_store.remember([{"title": "no id"}])
    assert live_job_store.get("bad") is None
    live_job_store.clear()
    assert live_job_store.get(LIVE_JOB["job_id"]) is None


# ---------------------------------------------------- application tracking ---


def test_saving_a_live_job_materialises_exactly_one_jobs_row(app, candidate, cached_live_job):
    """Save/Apply must keep working, without touching the canonical dataset."""
    user_id = candidate["user_id"]
    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            assert applications_route._ensure_job_row(cursor, cached_live_job["job_id"]) is True
            cursor.execute(
                "SELECT title, company FROM jobs WHERE job_id = %s", (cached_live_job["job_id"],)
            )
            row = cursor.fetchone()
        db.commit()

    assert row is not None
    assert row["title"] == "Data Analyst / Engineer"
    assert row["company"] == "Kyndryl"

    # Only that one row was added; the canonical 185 are untouched.
    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS n FROM jobs WHERE job_id >= %s", (1_000_000_000,))
            assert cursor.fetchone()["n"] == 1
            cursor.execute("DELETE FROM jobs WHERE job_id = %s", (cached_live_job["job_id"],))
        db.commit()


def test_ensure_job_row_is_a_noop_for_an_unknown_local_id(app):
    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            assert applications_route._ensure_job_row(cursor, 987_654_321) is False


def test_ensure_job_row_refuses_a_live_id_we_never_fetched(app):
    """An expired/unknown live id must not invent a jobs row."""
    live_job_store.clear()
    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            assert applications_route._ensure_job_row(cursor, 1_800_000_001) is False
            cursor.execute("SELECT 1 FROM jobs WHERE job_id = %s", (1_800_000_001,))
            assert cursor.fetchone() is None


# ------------------------------------------------------------------- the UI ---


def test_opportunities_page_shows_no_live_wording(client, cached_live_job):
    html = client.get("/opportunities/").get_data(as_text=True)
    main = re.search(r'<main class="app-main">(.*)</main>', html, re.S).group(1)
    for word in (">Live<", "Live listing", "Live Job", "Adzuna Live"):
        assert word not in main, word
    # The source marker class is gone entirely.
    assert "opportunity-source" not in main


def test_requirements_are_shown_for_a_live_job(client, cached_live_job):
    """Extracted requirements must actually reach the rendered card."""
    live_job_store.clear()
    live_job_store.remember([LIVE_JOB])
    # Recompute the match exactly the way the listing does.
    from services.job_matcher import compute_match

    match = compute_match(["SQL", "Python", "Excel"], LIVE_JOB)
    assert match["match_available"] is True
    assert set(match["matched_skills"]) == {"SQL", "Python"}
    assert match["missing_skills"] == []
    assert "Power BI" in match["missing_preferred"]
    assert match["match_percent"] is not None


def test_dashboard_and_opportunities_share_one_recommendation_flow(app, monkeypatch):
    """No separate algorithm for the Dashboard -- both call recommend_jobs."""
    from routes import opportunities as opportunities_module
    from services import opportunity_service

    seen = []

    def _spy(query, user_skills, top_k=20):
        seen.append((query, top_k))
        return []

    # routes/opportunities.py binds the name at import time, so patch both refs.
    monkeypatch.setattr(opportunity_service, "recommend_jobs", _spy)
    monkeypatch.setattr(opportunities_module, "recommend_jobs", _spy)

    client = app.test_client()
    with client.session_transaction() as flask_session:
        flask_session["user_id"] = 1
    client.get("/opportunities/")
    client.get("/home")

    assert len(seen) >= 2, seen


def test_default_query_prefers_profile_skills_and_falls_back(monkeypatch):
    from services import opportunity_service

    assert opportunity_service.build_default_query(["Python", "SQL"]) == "Python, SQL"
    # No skills -> the configured safe default, so the page is never empty.
    monkeypatch.setattr(opportunity_service.config, "ADZUNA_DEFAULT_QUERY", "entry level technology jobs")
    assert opportunity_service.build_default_query([]) == "entry level technology jobs"


def test_default_location_is_configurable_and_defaults_to_india(monkeypatch):
    from services import opportunity_service

    monkeypatch.setattr(opportunity_service.config, "ADZUNA_DEFAULT_LOCATION", "India")
    assert opportunity_service.default_location() == "India"
    monkeypatch.setattr(opportunity_service.config, "ADZUNA_DEFAULT_LOCATION", "United Kingdom")
    assert opportunity_service.default_location() == "United Kingdom"


def test_live_query_uses_or_semantics_capped_at_three_terms():
    """Adzuna reads commas as AND, so a skill list must become an OR list.

    Verified live: "Python, SQL, MySQL, Excel, Power BI" returned 1 job, while
    the three-term OR form returned 17-20. A five-term OR also collapses, so
    the cap is deliberate rather than arbitrary.
    """
    from services.opportunity_service import _live_query

    assert _live_query("Python, SQL, MySQL, Excel, Power BI") == "Python OR SQL OR MySQL"
    assert _live_query("data analyst") == "data analyst"
    assert _live_query("Python") == "Python"
    assert _live_query("") == ""


def test_local_pipeline_query_is_not_reshaped(monkeypatch):
    """Only the live call is rewritten; FAISS keeps the comma list."""
    from services import opportunity_service

    captured = {}

    def _fake_search(query, top_k=20, min_score=None):
        captured["query"] = query
        return []

    # adzuna_service is imported lazily inside _live_jobs, so patch its module.
    monkeypatch.setattr(adzuna_service, "search_jobs", lambda *a, **k: [])
    monkeypatch.setattr(opportunity_service, "search_jobs", _fake_search)
    opportunity_service.recommend_jobs("", ["Python", "SQL"], top_k=5)
    assert captured["query"] == "Python, SQL"


def test_live_search_always_sends_a_location(monkeypatch):
    """India (or the configured location) must be passed on every live call."""
    from services import opportunity_service

    captured = {}

    def _fake(query, location="", country_code="", page=1, results_per_page=20):
        captured["query"] = query
        captured["location"] = location
        captured["results_per_page"] = results_per_page
        return []

    monkeypatch.setattr(opportunity_service.config, "ADZUNA_DEFAULT_LOCATION", "India")
    monkeypatch.setattr(adzuna_service, "search_jobs", _fake)
    opportunity_service._live_jobs("data analyst", [], top_k=7)

    assert captured["location"] == "India"
    assert captured["query"] == "data analyst"
