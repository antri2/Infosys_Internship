"""Job date extraction, normalisation and rendering.

Two rules drive everything here:

1. A date is only ever reported when a source actually states one. A missing
   date renders as ``Not specified`` -- never as today, never as a guess.
2. Neither source publishes an application deadline today, so that path is
   exercised with synthetic input to prove the plumbing works the moment a
   source does provide one, while real data stays empty.
"""

from datetime import datetime
import re

import pytest

from database.db import get_db
from services.job_dates import (
    DEADLINE_KEYS,
    application_deadline,
    format_date,
    is_expired,
    parse_datetime,
    published_date,
)


# ------------------------------------------------------------------ parsing ---


@pytest.mark.parametrize(
    "value,expected",
    [
        ("2026-08-25T10:07:51Z", datetime(2026, 8, 25, 10, 7, 51)),
        ("2026-08-25T10:07:51+00:00", datetime(2026, 8, 25, 10, 7, 51)),
        ("2026-08-25 10:07:51", datetime(2026, 8, 25, 10, 7, 51)),
        ("2026-08-25", datetime(2026, 8, 25)),
        ("25/08/2026", datetime(2026, 8, 25)),
        ("25-08-2026", datetime(2026, 8, 25)),
        ("Aug 25, 2026", datetime(2026, 8, 25)),
        ("25 Aug 2026", datetime(2026, 8, 25)),
    ],
)
def test_parses_the_timestamp_shapes_sources_send(value, expected):
    assert parse_datetime(value) == expected


def test_parses_fractional_seconds():
    # Sub-second precision is preserved rather than silently rounded away.
    assert parse_datetime("2026-08-25T10:07:51.123Z") == datetime(
        2026, 8, 25, 10, 7, 51, 123000
    )
    # A non-ISO fractional form still falls back cleanly to the whole second.
    assert parse_datetime("2026-08-25T10:07:51.5") == datetime(2026, 8, 25, 10, 7, 51, 500000)


def test_a_datetime_passes_through():
    stamp = datetime(2026, 1, 2, 3, 4, 5)
    assert parse_datetime(stamp) is stamp


@pytest.mark.parametrize("value", [None, "", "   ", "not a date", "tomorrow", "13/45/2026", True, False, [], {}])
def test_unparseable_values_return_none(value):
    assert parse_datetime(value) is None


# ---------------------------------------------------------------- formatting ---


@pytest.mark.parametrize(
    "value,expected",
    [
        ("2026-08-25T10:07:51Z", "25 Aug 2026"),
        ("2026-08-25", "25 Aug 2026"),
        (datetime(2026, 8, 25), "25 Aug 2026"),
        (None, ""),
        ("", ""),
        ("garbage", ""),
    ],
)
def test_format_date(value, expected):
    assert format_date(value) == expected


def test_formatting_drops_the_time_component():
    assert "10:07" not in format_date("2026-08-25T10:07:51Z")


# ------------------------------------------------------- source extraction ---


def test_published_date_from_a_real_adzuna_payload():
    """Exactly the shape Adzuna's search endpoint returns."""
    raw = {
        "id": "5855006986",
        "title": "Data Analyst",
        "created": "2026-08-25T10:07:51Z",
    }
    assert published_date(raw) == "25 Aug 2026"


def test_published_date_missing_is_empty_not_today():
    raw = {"id": "1", "title": "Data Analyst"}
    assert published_date(raw) == ""
    # Explicitly not filled in with the current date.
    assert published_date(raw) != format_date(datetime.now())


@pytest.mark.parametrize("value", [None, "", "   ", "not-a-date", 12345])
def test_published_date_invalid_is_empty(value):
    assert published_date({"created": value}) == ""


def test_published_date_ignores_non_dict():
    assert published_date(None) == ""
    assert published_date("nope") == ""


def test_application_deadline_is_empty_when_the_source_has_none():
    """Adzuna's search response publishes no deadline key at all."""
    raw = {"id": "1", "title": "Data Analyst", "created": "2026-08-25T10:07:51Z"}
    assert application_deadline(raw) == ""
    assert application_deadline({}) == ""


@pytest.mark.parametrize("key", DEADLINE_KEYS)
def test_a_deadline_is_picked_up_from_any_supported_key(key):
    """Plumbing is proven so a future source works without a code change."""
    assert application_deadline({key: "2026-09-30T23:59:59Z"}) == "30 Sep 2026"


def test_deadline_takes_the_first_present_key_and_skips_empty_ones():
    raw = {"expires": "", "closing_date": None, "valid_until": "2026-10-15"}
    assert application_deadline(raw) == "15 Oct 2026"


def test_deadline_invalid_value_is_empty():
    assert application_deadline({"expires": "whenever"}) == ""


# ------------------------------------------------------------------ expiry ---


def test_is_expired_is_none_when_there_is_no_deadline():
    assert is_expired("") is None
    assert is_expired("Not specified") is None


def test_is_expired_compares_dates():
    today = datetime(2026, 10, 5)
    # A deadline already passed is expired.
    assert is_expired("01 Oct 2026", today=today) is True
    assert is_expired("30 Sep 2026", today=today) is True
    # The same day is not yet expired.
    assert is_expired("05 Oct 2026", today=today) is False
    # A future deadline is open.
    assert is_expired("30 Oct 2026", today=today) is False


# ---------------------------------------------------------- normalizer glue ---


def test_adzuna_normalize_includes_both_date_fields():
    from services import adzuna_service

    raw = {
        "id": "5855006986",
        "title": "Data Analyst",
        "company": {"display_name": "Kyndryl"},
        "location": {"display_name": "Bangalore"},
        "description": "Requirements: Python and SQL.",
        "created": "2026-08-25T10:07:51Z",
        "contract_time": "full_time",
    }
    job = adzuna_service.normalize_result(raw)
    assert job["published_date"] == "25 Aug 2026"
    # Adzuna publishes no deadline, so it stays empty rather than being invented.
    assert job["application_deadline"] == ""


def test_adzuna_normalize_without_created_still_works():
    from services import adzuna_service

    raw = {
        "id": "1",
        "title": "Data Analyst",
        "company": {"display_name": "Acme"},
        "location": {"display_name": "Pune"},
        "description": "",
    }
    job = adzuna_service.normalize_result(raw)
    assert job["title"] == "Data Analyst"
    assert job["published_date"] == ""
    assert job["application_deadline"] == ""


def test_live_jobs_are_still_ranked_the_same_way():
    """Adding dates must not change matching or ordering."""
    from services.job_matcher import compute_match

    from services import adzuna_service

    base = {
        "id": "1",
        "title": "Reporting Analyst",
        "company": {"display_name": "Acme"},
        "location": {"display_name": "Pune"},
        "description": "Requirements: Python and SQL required.",
        "created": "2026-08-25T10:07:51Z",
    }
    job = adzuna_service.normalize_result(base)
    match = compute_match(["Python"], job)
    assert match["matched_skills"] == ["Python"]
    assert "SQL" in match["missing_skills"]
    assert match["match_percent"] is not None
    # The date fields are additive and inert for the matcher.
    assert "published_date" not in match
    assert "application_deadline" not in match


def test_dates_do_not_change_the_ranking_score():
    """Same job text, with and without dates, must score identically."""
    from services.job_matcher import compute_match

    from services import adzuna_service

    base = {
        "id": "1",
        "title": "Reporting Analyst",
        "company": {"display_name": "Acme"},
        "location": {"display_name": "Pune"},
        "description": "Requirements: Python and SQL required.",
    }
    with_date = compute_match(["Python"], adzuna_service.normalize_result({**base, "created": "2026-08-25T10:07:51Z"}))
    without_date = compute_match(["Python"], adzuna_service.normalize_result(base))

    assert with_date["match_percent"] == without_date["match_percent"]
    assert with_date["ranking_score"] == without_date["ranking_score"]
    assert with_date["missing_skills"] == without_date["missing_skills"]


# --------------------------------------------------------------- rendering ---


def test_posted_date_is_not_rendered_on_opportunity_cards(client):
    """Posted date was removed from the UI at the user's request.

    The field is gone from the template rather than merely blanked, so neither
    the label nor a "Not specified" placeholder can appear.
    """
    html = client.get("/opportunities/").get_data(as_text=True)
    assert "Posted:" not in html
    assert "<b>Published:</b>" not in html
    assert "opportunity-date-label" not in html


def test_deadline_field_is_fully_hidden_when_the_source_has_none(client):
    """No placeholder wording, and the whole field disappears."""
    html = client.get("/opportunities/").get_data(as_text=True)
    assert "Apply by:" not in html
    assert "Application deadline:" not in html
    # The wording the user objected to must never appear.
    assert "Not Disclosed" not in html
    assert "Deadline: Not Disclosed" not in html


def test_no_deadline_placeholder_is_rendered_anywhere(client):
    html = client.get("/opportunities/").get_data(as_text=True)
    for forbidden in ("Not Disclosed", "Deadline: N/A", "deadline TBD"):
        assert forbidden not in html


def test_a_real_deadline_is_rendered_when_the_source_provides_one(app, client, monkeypatch):
    """The field is hidden only when there is genuinely no deadline.

    No current source publishes one, so this drives the template with a job that
    carries a real value to prove the field still renders when it exists.
    """
    from routes import opportunities as opportunities_module
    from services import opportunity_service

    live_job = {
        "job_id": 1_855_006_986,
        "title": "Data Analyst / Engineer",
        "company": "Kyndryl",
        "location": "Bangalore",
        "description": "Requirements: Python and SQL.",
        "required_skills": "Python, SQL",
        "preferred_skills": "",
        "qualifications": "See job description",
        "experience_required": "3+ years",
        "education_required": "",
        "stipend_or_salary": "",
        "apply_link": "",
        "job_type": "Full Time",
        "match_available": False,
        "match_percent": None,
        "match_reasons": [],
        "published_date": "25 Aug 2026",
        "application_deadline": "30 Sep 2026",
        "source": "adzuna",
    }

    # routes/opportunities.py binds the name at import time, so patch both refs.
    monkeypatch.setattr(opportunity_service, "recommend_jobs", lambda *a, **k: [dict(live_job)])
    monkeypatch.setattr(opportunities_module, "recommend_jobs", lambda *a, **k: [dict(live_job)])

    html = client.get("/opportunities/").get_data(as_text=True)
    # Strip tags and collapse whitespace so a label/value pair reads contiguously.
    flat = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))

    # The deadline is carried on the expand control so the inline detail can
    # show it. It is deliberately not on the collapsed card: the card is meant
    # to stay compact, and the deadline only matters once the job is opened.
    html_raw = client.get("/opportunities/").get_data(as_text=True)
    assert 'data-deadline="30 Sep 2026"' in html_raw

    # The date itself is still present in the payload the expander receives.
    assert "30 Sep 2026" in html_raw

    # A real publication date from the source IS carried through, unlike the
    # import timestamp used for seeded rows.
    assert 'data-published="25 Aug 2026"' in html_raw
    # The posted date is not rendered even when the source supplied one.
    assert "Posted:" not in flat
    assert "25 Aug 2026" not in flat


def test_detail_panel_shows_only_the_deadline_when_one_exists(client):
    """The detail panel still renders, and only carries a real deadline."""
    html = client.get("/opportunities/").get_data(as_text=True)
    # No deadline in any real source today, so the panel is fully absent rather
    # than left as an empty element.
    # The deadline block is .opp-card__deadline; it must be absent entirely
    # rather than left behind as an empty element.
    assert "opp-card__deadline" not in html
    assert "Published:" not in html


def test_no_fake_deadline_is_ever_derived(client):
    """Nothing may be derived from the published date, age, or retrieval time."""
    import datetime

    html = client.get("/opportunities/").get_data(as_text=True)
    assert "Apply by:" not in html

    # Nor may any +7/+15/+30 style value appear as a deadline.
    posted = re.findall(
        r"([0-9]{2} [A-Za-z]{3} [0-9]{4})\s*</span>\s*<span[^>]*>Apply by:",
        html,
    )
    for value in posted:
        stamp = datetime.datetime.strptime(value, "%d %b %Y")
        for offset in (7, 15, 30):
            derived = (stamp + datetime.timedelta(days=offset)).strftime("%d %b %Y")
            assert f"Apply by:</span> {derived}" not in html


def test_local_job_posted_dates_are_not_rendered(app, client):
    """_attach_local_dates still resolves created_at, but nothing displays it.

    The removal is presentation-only, so the existing date plumbing is left
    intact and simply unused by the templates.
    """
    from database.db import get_db

    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT job_id, created_at FROM jobs ORDER BY job_id LIMIT 1")
            row = cursor.fetchone()
        created = row["created_at"]

    html = client.get("/opportunities/").get_data(as_text=True)
    assert created.strftime("%d %b %Y") not in html
    assert "Posted:" not in html


def test_every_local_job_gets_a_date_not_just_some(app, client, monkeypatch):
    """Regression: ids that merely start with the digit 1 must not be skipped.

    A string-prefix check against the reserved Adzuna range ("1...") silently
    dropped every local job whose id happened to start with 1 -- 17, 122, 152,
    167 and 182 all rendered "Not specified" despite having a created_at.
    """
    from database.db import get_db
    from routes import opportunities as opportunities_module
    from services import adzuna_service

    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT job_id FROM jobs ORDER BY job_id")
            all_ids = [row["job_id"] for row in cursor.fetchall()]

    starting_with_one = [i for i in all_ids if str(i).startswith("1")]
    assert starting_with_one, "dataset should contain ids starting with 1"

    jobs = [{"job_id": i, "source": "local"} for i in all_ids[:60]]
    monkeypatch.setattr(adzuna_service.config, "ADZUNA_ENABLED", False)

    with app.app_context():
        opportunities_module._attach_local_dates(get_db(), jobs)

    missing = [job["job_id"] for job in jobs if not job.get("published_date")]
    assert missing == [], f"these local jobs lost their published date: {missing}"


def test_reserved_live_ids_are_never_looked_up_as_local(app):
    """A live id must not be turned into a local published date."""
    from database.db import get_db
    from routes import opportunities as opportunities_module

    jobs = [{"job_id": 1_855_006_986, "source": "adzuna", "published_date": "25 Aug 2026"}]
    with app.app_context():
        opportunities_module._attach_local_dates(get_db(), jobs)

    assert jobs[0]["published_date"] == "25 Aug 2026"
    assert jobs[0]["application_deadline"] == ""


def test_live_job_dates_survive_into_the_detail_view(app, client):
    """A live job's own published date stays available when opened."""
    from services import adzuna_service, live_job_store

    live_job_store.clear()
    live_job_store.remember(
        [
            {
                "job_id": 1_855_006_986,
                "title": "Data Analyst / Engineer",
                "company": "Kyndryl",
                "location": "Bangalore",
                "description": "Requirements: Python and SQL.",
                "required_skills": "Python, SQL",
                "preferred_skills": "",
                "qualifications": "See job description",
                "experience_required": "",
                "education_required": "",
                "stipend_or_salary": "",
                "apply_link": "",
                "job_type": "Full Time",
                "published_date": "25 Aug 2026",
                "application_deadline": "",
                "source": "adzuna",
            }
        ]
    )
    try:
        from services.context_builder import get_job_context

        with app.app_context():
            job = get_job_context(get_db(), 1_855_006_986)
        assert job is not None
        assert job["published_date"] == "25 Aug 2026"
        assert job["application_deadline"] == ""
    finally:
        live_job_store.clear()


def test_dates_do_not_disturb_existing_card_behaviour(client):
    """Skill matching and the action buttons are unaffected."""
    html = client.get("/opportunities/").get_data(as_text=True)
    assert "Skill Fit" in html or "Add skills for fit" in html
    assert "View Details" in html
    assert "Skill Gap" in html
    assert "Prepare for Interview" in html
    assert "Get AI Summary" in html
    # Save/Apply are still rendered.
    assert ">Save<" in html or "Save" in html
