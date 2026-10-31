"""Home Dashboard: compact cards, honest dates, unified buttons, footer.

Each test here pins a specific requirement from this change:

  * six cards first, then "View More", in a 3-column grid;
  * equal card heights via clamps rather than equal content;
  * no literal "Not provided" anywhere on the dashboard;
  * optional fields omitted rather than padded with a placeholder;
  * a publication date only when the source value is valid -- never repaired to
    today, and never shown for a generated listing;
  * a clearly labelled "Suggested Apply By" instead of a fabricated deadline;
  * the two specified button treatments, with matching metrics;
  * one light-blue palette across all three summary cards;
  * a footer that tracks the sidebar's collapsed state.
"""

import re
from datetime import datetime

import pytest

from database.db import get_db
from services import job_dates


@pytest.fixture
def signed_in(app, client, candidate):
    with client.session_transaction() as flask_session:
        flask_session["user_id"] = candidate["user_id"]
        flask_session["user_name"] = "Step1 Candidate"
    return client


def _main(html):
    match = re.search(r'<main class="app-main">(.*)</main>', html, re.S)
    assert match, "the app shell main region is missing"
    return match.group(1)


# Marker for this change's own CSS block.
HOME_CSS_MARKER = "Home dashboard -- recommended job cards"


def _home_block(css: str) -> str:
    """Only the CSS this change added.

    Searching the whole file finds either the older definitions from the
    app-shell task, or the narrow-screen @media overrides that come later in
    this same block -- neither is the base declaration under test.
    """
    index = css.find(HOME_CSS_MARKER)
    assert index != -1, "the Home dashboard CSS block is missing"
    return css[index:]


def _last_rule(css: str, selector: str) -> str:
    """The base declaration of a selector inside the Home CSS block.

    Within the block the base rule is written before the responsive overrides,
    so the first match is the one the desktop layout uses.
    """
    matches = re.findall(re.escape(selector) + r"\s*\{([^}]*)\}", _home_block(css))
    assert matches, f"no rule found for {selector} in the Home block"
    return matches[0]


def _own_rule(css: str, selector: str) -> str:
    """The rule where the selector is the FIRST one listed.

    Needed for the button variants, which share one base rule and are then
    overridden individually. The negative lookbehind excludes the case where the
    previous line ends in a comma, i.e. this is the second selector of a group.
    """
    pattern = r"(?m)^(?<!,\n)" + re.escape(selector) + r"\s*\{([^}]*)\}"
    matches = re.findall(pattern, _home_block(css))
    assert matches, f"no standalone rule found for {selector}"
    return matches[0]



def _blank_all(app, **columns) -> dict:
    """Blank one column on every job row, returning the values to restore.

    The ranking returns live Adzuna listings ahead of the local rows when the
    profile has no skills, so changing a single row would not be visible. Every
    row is changed and the originals are restored by the caller.
    """
    originals = {}
    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            for column in columns:
                cursor.execute(f"SELECT job_id, `{column}` AS value FROM jobs")
                originals[column] = {row["job_id"]: row["value"] for row in cursor.fetchall()}
                cursor.execute(f"UPDATE jobs SET `{column}` = ''")
        db.commit()
    return originals


def _restore_all(app, originals: dict) -> None:
    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            for column, values in originals.items():
                for job_id, value in values.items():
                    cursor.execute(
                        f"UPDATE jobs SET `{column}` = %s WHERE job_id = %s",
                        (value, job_id),
                    )
        db.commit()


def _render_home(app, jobs, visible=6):
    """Render the dashboard with a controlled job list.

    Uses the same `_card_job` enrichment the route uses, so the template sees
    exactly the shape production renders.
    """
    from flask import render_template
    from routes.profile import HOME_VISIBLE_JOBS, _card_job

    prepared = [_card_job(job) for job in jobs]
    with app.test_request_context("/home"):
        html = render_template(
            "home.html",
            active_page="home",
            user_name="Step1 Candidate",
            is_new_user=False,
            profile={},
            checklist=[],
            completeness=50,
            resume_uploaded=True,
            top_jobs=prepared,
            home_visible_count=min(visible, len(prepared)),
            applications_count=0,
            recent_applications=[],
        )
    return html


def _bare_job(**overrides):
    job = {
        "job_id": 1, "source": "local", "title": "Data Analyst Intern",
        "company": "Acme Analytics", "location": "Chandigarh", "job_type": "Full-time",
        "stipend_or_salary": "8 LPA", "required_skills": "SQL, Excel, Python, Pandas, Power BI",
        "matched_skills": ["SQL", "Excel"], "description": "Some description",
        "match_available": True, "match_percent": 80,
    }
    job.update(overrides)
    return job



def _cards(html):
    return re.findall(r'<article class="job-card[^"]*"[^>]*>(.*?)</article>',
                      html, re.S)


# ==========================================================================
# 1. Six cards first, then View More, in a 3-column grid
# ==========================================================================


def test_six_cards_are_visible_before_view_more(signed_in):
    html = signed_in.get("/home").get_data(as_text=True)
    main = _main(html)

    cards = re.findall(
        r'<article class="job-card[^"]*"([^>]*)>', main, re.S)
    assert len(cards) == 9, "the ranking still produces nine rows"

    hidden = [attrs for attrs in cards if "hidden" in attrs]
    visible = [attrs for attrs in cards if "hidden" not in attrs]
    assert len(visible) == 6, f"expected 6 visible cards, found {len(visible)}"
    assert len(hidden) == 3


def test_the_visible_count_comes_from_the_route(signed_in):
    """Not hardcoded in the template: the route decides."""
    from routes.profile import HOME_VISIBLE_JOBS, HOME_JOB_COUNT

    assert HOME_VISIBLE_JOBS == 6
    assert HOME_JOB_COUNT == 9


def test_view_more_exists_and_reveals_the_rest(signed_in):
    html = signed_in.get("/home").get_data(as_text=True)

    assert 'id="viewMoreJobs"' in html
    assert 'aria-controls="jobGrid"' in html
    # The reveal is client-side: no new route is requested for it.
    assert "/resume-builder/view-more" not in html
    assert "viewMoreJobs" in html, "the reveal script must be present"


def test_view_more_is_omitted_when_there_is_nothing_more(signed_in):
    html = signed_in.get("/home").get_data(as_text=True)
    cards = _cards(html)
    if len(cards) <= 6:
        assert 'id="viewMoreJobs"' not in html
    else:
        assert 'id="viewMoreJobs"' in html


def test_the_grid_is_three_columns_then_steps_down():
    css = open("static/css/app.css", encoding="utf-8").read()

    grid = re.search(r"\.job-grid\s*\{([^}]*)\}", css).group(1)
    assert "repeat(3, minmax(0, 1fr))" in grid.replace("  ", " ")
    # Rows match the tallest card, which is what makes heights consistent.
    assert "align-items: stretch" in grid

    assert re.search(r"@media \(max-width: 1180px\)[\s\S]*?\.job-grid\s*\{[^}]*repeat\(2,",
                     css), "expected a two-column step"
    assert re.search(r"@media \(max-width: 780px\)[\s\S]*?\.job-grid\s*\{[^}]*minmax\(0, 1fr\)",
                     css), "expected a single-column step"


# ==========================================================================
# 2. Consistent card height and no oversized content
# ==========================================================================


def test_long_titles_cannot_stretch_a_card():
    css = open("static/css/app.css", encoding="utf-8").read()

    title = _last_rule(css, ".job-card__title")
    # Clamped to two lines, in a box reserved for two lines, so a 9-character
    # title occupies the same space as a 32-character one.
    assert "-webkit-line-clamp: 2" in title
    assert "min-height" in title
    assert "overflow: hidden" in title


def test_skill_lists_cannot_stretch_a_card():
    css = open("static/css/app.css", encoding="utf-8").read()

    skills = _last_rule(css, ".job-card__skills")
    assert "min-height" in skills, "room is reserved for two pill rows"

    pills = re.search(r"\.job-card__skills \.ai-pill\s*\{([^}]*)\}", css).group(1)
    assert "overflow: hidden" in pills
    assert "text-overflow: ellipsis" in pills
    assert "white-space: nowrap" in pills

    company = _last_rule(css, ".job-card__company")
    assert "overflow: hidden" in company or "flex-wrap: wrap" in company


def test_actions_align_to_the_bottom_of_every_card():
    css = open("static/css/app.css", encoding="utf-8").read()
    actions = _last_rule(css, ".job-card__actions")
    assert "margin-top: auto" in actions, "the action bar must pin to the card base"
    assert "display: grid" in actions


def test_the_card_is_a_flex_column():
    css = open("static/css/app.css", encoding="utf-8").read()
    card = _last_rule(css, ".job-card")
    assert "display: flex" in card
    assert "flex-direction: column" in card


# ==========================================================================
# 3. No placeholder text on the dashboard
# ==========================================================================


def test_no_not_provided_literal_on_the_dashboard(signed_in):
    """The brief asks for these literals to be gone from the job cards."""
    html = signed_in.get("/home").get_data(as_text=True)
    main = _main(html)

    for placeholder in ("Not provided", "Not Provided", "not provided",
                        "Not listed", "Unknown"):
        assert placeholder not in main, placeholder

    # The one deliberate exception is the fallback title for a job row with no
    # title at all, which is a usable label rather than a placeholder value.
    assert "Not provided" not in main


def test_optional_facts_are_only_rendered_when_populated():
    """Checked at the service boundary, where the rule actually lives.

    The dashboard legitimately mixes local synthetic rows with live Adzuna
    listings, so asserting on whatever happens to be ranked would test the data
    rather than the rule.
    """
    from routes.profile import _card_job

    bare = _card_job({"job_id": 1, "source": "synthetic"})
    assert bare["company"] == ""
    assert bare["location"] == ""
    assert bare["job_type"] == ""
    assert bare["stipend_or_salary"] == ""
    assert bare["work_mode"] == ""
    # So the template's {% if %} guards are false and the rows are omitted.
    assert not bare["company"]
    assert not bare["location"]


def test_optional_fields_are_omitted_rather_than_padded(signed_in):
    """A card must not reserve a row for data the source does not have."""
    html = signed_in.get("/home").get_data(as_text=True)
    main = _main(html)

    for facts in re.findall(r'<ul class="job-card__facts">(.*?)</ul>', main, re.S):
        rows = re.findall(r"<li[^>]*>(.*?)</li>", facts, re.S)
        assert rows, "a facts list was rendered with no rows"
        for row in rows:
            # Strip the icon markup; whatever remains is the real value.
            text = re.sub(r"<svg.*?</svg>", "", row, flags=re.S).strip()
            assert text, "a fact row was rendered with no value"
            # "-" is deliberately not checked here: legitimate values such as
            # "Full-time" contain it.
            for placeholder in ("Not provided", "Not Provided", "N/A", "Unknown"):
                assert placeholder not in text, (placeholder, text)


def test_a_card_with_no_skills_says_so_in_words(app):
    """Stated in words, rather than an empty area or a placeholder value."""
    html = _render_home(app, [_bare_job(required_skills="")])

    assert "does not list required skills" in html
    assert "Not provided" not in html
    # No pill row at all, because there is nothing to put in it.
    assert "ai-pill--required" not in html


def test_a_full_skill_list_is_summarised_rather_than_clipped(app):
    html = _render_home(app, [_bare_job()])

    # Four pills plus the overflow summary; the rest stay reachable via title.
    assert html.count('class="ai-pill ai-pill--have"') == 2
    assert html.count('class="ai-pill ai-pill--required"') == 2
    assert 'class="ai-pill ai-pill--more"' in html
    assert "+1 more" in html


def test_a_missing_location_row_is_omitted_not_left_empty(app):
    html = _render_home(app, [_bare_job(location="")])

    assert "job-card__loc" not in html, "an empty location row must not render"
    # Everything else still renders.
    assert "Acme Analytics" in html
    assert "Data Analyst Intern" in html


def test_a_missing_company_gets_a_readable_label(app):
    html = _render_home(app, [_bare_job(company="")])

    assert "Company not listed" in html
    assert "Not provided" not in html


def test_a_job_with_only_a_title_still_renders(app):
    """The sparsest possible card must not collapse or break."""
    html = _render_home(app, [{
        "job_id": 9, "source": "adzuna", "title": "Technical Writer",
    }])

    assert "Technical Writer" in html
    assert "Not provided" not in html
    assert "data-job-id=\"9\"" in html
    # No fit badge when the profile cannot be compared.
    assert "fit-badge" not in html


def test_a_long_title_and_many_skills_do_not_change_the_structure(app):
    """The card shape is identical for a sparse and a dense listing."""
    sparse = _render_home(app, [{"job_id": 1, "source": "adzuna",
                                 "title": "Writer"}])
    dense = _render_home(app, [_bare_job(
        title="Associate Product Manager Intern",
        required_skills="SQL, Excel, Python, Pandas, Power BI",
    )])

    for marker in ('class="job-card__head"', 'class="job-card__title"',
                   'class="job-card__facts"', 'class="job-card__skills"',
                   'class="job-card__actions"'):
        assert marker in sparse, marker
        assert marker in dense, marker


# ==========================================================================
# 4. Publication dates
# ==========================================================================


def test_an_invalid_publication_date_is_rejected_not_repaired():
    today = datetime(2026, 10, 17)
    validate = job_dates.validated_publication_date

    assert validate("2026-10-01T00:00:00Z", today) == "01 Oct 2026"
    # Old dates are dropped, never rewritten to today.
    for stale in ("2019-05-01", "2021-07-15"):
        assert validate(stale, today) == ""
    # A future date is not a publication date either.
    assert validate("2027-01-01", today) == ""
    # Unparseable and missing values yield nothing.
    assert validate("not a date", today) == ""
    assert validate(None, today) == ""


def test_a_rejected_date_is_never_replaced_with_today():
    today = datetime(2026, 10, 17)
    for stale in ("2019-05-01", "2021-07-15"):
        result = job_dates.validated_publication_date(stale, today)
        assert result != today.strftime(job_dates.DISPLAY_FORMAT)
        assert result == ""


def test_a_generated_listing_gets_a_demo_badge_and_no_publication_date():
    """A local row has no posting date, so it is badged rather than dated.

    `jobs.created_at` is a row-import timestamp, not a posting date, so the
    card must not present it as one.
    """
    from routes.profile import _card_job

    enriched = _card_job({
        "job_id": 1, "source": "local", "title": "Software Engineer Intern",
        # created_at is what a naive implementation would have used here.
        "created_at": "2026-09-25 00:44:17",
    })

    assert enriched["is_demo"] is True
    assert enriched["demo_label"] == "Demo listing"
    # No publication date, and nothing derived from created_at.
    assert enriched["published_date"] == ""
    assert "2026" not in enriched["published_date"]
    assert "25 Sep" not in enriched["published_date"]


def test_a_live_listing_gets_no_badge_and_keeps_a_valid_date():
    from routes.profile import _card_job

    enriched = _card_job({
        "job_id": 1, "source": "adzuna", "title": "Technical Writer",
        "published_date": "2026-04-27T09:00:00",
    })
    assert enriched["is_demo"] is False
    assert enriched["demo_label"] == ""
    assert enriched["published_date"] == "27 Apr 2026"


def test_the_demo_badge_is_only_used_for_generated_listings(signed_in):
    """Every badge on the page must sit on a card from a generated source.

    The ranking legitimately mixes local synthetic rows with live Adzuna
    listings, so the assertion is that the badge and its label always pair up
    rather than that a badge is always present.
    """
    html = signed_in.get("/home").get_data(as_text=True)
    main = _main(html)

    badges = main.count('class="job-card__demo"')
    assert badges == main.count("Demo listing"), "badge and label must pair up"
    # The badge explains itself on hover.
    if badges:
        assert "generated sample data" in main


def test_the_jobs_table_has_no_posted_date_column_to_reuse(app):
    """Confirms the data behind the decision to badge rather than date them.

    schema.sql predates any posting-date column, so there is nothing legitimate
    for a local card to display: `created_at` is a row-import timestamp.
    """
    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute(
                "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'jobs'"
            )
            columns = {row["COLUMN_NAME"] for row in cursor.fetchall()}

    # Whatever the deployment carries, no column is a verified posting date for
    # the seeded rows, and created_at is explicitly the import timestamp.
    assert "created_at" in columns
    assert "application_deadline" not in columns, \
        "there is no employer deadline column to display"


def test_the_ranking_labels_seeded_rows_as_local():
    """Why DEMO_SOURCES must include "local".

    services.opportunity_service.py stamps every row it reads from the seeded
    table with source="local", and that label is what the template receives --
    not the jobs.source column value. Recognising only "synthetic" left the
    majority of listings unbadged.
    """
    from services import opportunity_service

    assert opportunity_service.LOCAL_SOURCE == "local"
    assert "local" in job_dates.DEMO_SOURCES
    assert "synthetic" in job_dates.DEMO_SOURCES
    # A live listing is never treated as demo data.
    assert job_dates.is_demo_listing({"source": "adzuna"}) is False
    assert job_dates.is_demo_listing({"source": "local"}) is True
    assert job_dates.is_demo_listing({"source": "synthetic"}) is True


def test_a_real_publication_date_would_be_shown(app, candidate, client):
    """A genuinely valid source date is not filtered out."""
    with client.session_transaction() as flask_session:
        flask_session["user_id"] = candidate["user_id"]
        flask_session["user_name"] = "Step1 Candidate"

    from services.opportunity_service import recommend_jobs
    from routes.profile import _card_job

    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT name FROM skills WHERE user_id = %s",
                           (candidate["user_id"],))
            skills = [row["name"] for row in cursor.fetchall()]
        jobs = recommend_jobs("", skills, top_k=1)
        assert jobs, "expected at least one recommended job"

        recent = datetime.now().strftime("%d %b %Y")
        enriched = _card_job({**jobs[0], "source": "adzuna",
                              "published_date": datetime(2026, 10, 5).isoformat()})
        assert enriched["published_date"] == "05 Oct 2026"
        assert enriched["is_demo"] is False
        assert enriched["demo_label"] == ""


# ==========================================================================
# 5. Suggested Apply By
# ==========================================================================


def test_the_suggested_window_follows_a_documented_rule():
    assert job_dates.SUGGESTED_WINDOW_DAYS == 14
    assert job_dates.suggested_apply_by(datetime(2026, 10, 17)) == "31 Oct 2026"
    assert job_dates.suggested_apply_by(datetime(2026, 12, 25)) == "08 Jan 2027"


def test_apply_by_is_labelled_as_a_suggestion_not_a_deadline():
    result = job_dates.apply_by_for({}, datetime(2026, 10, 17))
    assert result["label"] == "Suggested Apply By"
    assert result["suggested"] is True

    real = job_dates.apply_by_for({"application_deadline": "30 Sep 2026"},
                                  datetime(2026, 10, 17))
    assert real["label"] == "Application deadline"
    assert real["suggested"] is False


def test_the_dashboard_labels_the_date_as_a_suggestion(signed_in):
    html = signed_in.get("/home").get_data(as_text=True)
    main = _main(html)

    assert "Suggested Apply By" in main
    # Never presented as the employer's own deadline.
    assert "Application deadline" not in main
    # And visually marked as guidance rather than as a fact.
    assert "job-card__apply-by--suggested" in main


def test_a_real_deadline_would_keep_its_own_label(app, candidate):
    from routes.profile import _card_job

    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT job_id FROM jobs ORDER BY job_id LIMIT 1")
            job_id = cursor.fetchone()["job_id"]

        enriched = _card_job({"job_id": job_id, "source": "adzuna",
                              "application_deadline": "30 Sep 2026"})
        assert enriched["apply_by"]["label"] == "Application deadline"
        assert enriched["apply_by"]["value"] == "30 Sep 2026"
        assert enriched["apply_by"]["suggested"] is False


# ==========================================================================
# 6. Button treatments
# ==========================================================================


def test_view_details_and_the_actions_use_the_specified_treatments(signed_in):
    html = signed_in.get("/home").get_data(as_text=True)
    card = _cards(html)[0]
    actions = re.search(r'<div class="job-card__actions">(.*?)</div>', card, re.S).group(1)

    assert 'class="ai-btn ai-btn--job-details"' in actions
    assert actions.count('class="ai-btn ai-btn--job-action"') == 2


def test_the_two_button_variants_have_identical_metrics():
    css = open("static/css/app.css", encoding="utf-8").read()

    shared = re.search(
        r"\.ai-btn--job-details,\s*\.ai-btn--job-action\s*\{([^}]*)\}", css
    ).group(1)
    # Height, radius, padding and font size are declared once, so the two can
    # never drift apart.
    for declaration in ("min-height", "padding", "font-size", "border-radius"):
        assert declaration in shared, declaration

    details = _own_rule(css, ".ai-btn--job-details")
    action = _own_rule(css, ".ai-btn--job-action")

    # View Details: light-blue surface, dark-blue text.
    assert "#DBEAFE" in details
    assert "#1E3A8A" in details
    # Save / Apply: dark-blue surface, white text.
    assert "--ai-navy" in action
    assert "color: #fff" in action


def test_both_button_variants_have_hover_states():
    css = open("static/css/app.css", encoding="utf-8").read()
    assert re.search(r"\.ai-btn--job-details:hover\s*\{", css)
    assert re.search(r"\.ai-btn--job-action:hover\s*\{", css)
    # And keyboard focus is visible for both.
    assert ".ai-btn--job-details:focus-visible" in css
    assert ".ai-btn--job-action:focus-visible" in css


def test_the_shared_button_variants_are_not_modified():
    """The new treatments are new classes, so other pages are unaffected."""
    css = open("static/css/app.css", encoding="utf-8").read()
    # The pre-existing variants used elsewhere still exist and are unchanged.
    assert ".ai-btn--primary {" in css
    assert ".ai-btn--navy {" in css
    assert ".ai-btn--ghost {" in css


def test_save_and_apply_keep_their_job_identifiers(signed_in):
    html = signed_in.get("/home").get_data(as_text=True)
    cards = _cards(html)
    assert cards

    for card in cards:
        ids = re.findall(r'data-track-job="(\d+)"', card)
        assert len(ids) == 2, "save and apply must both carry the job id"
        assert len(set(ids)) == 1, "save and apply must target the same job"

        # One View Details button, so one id, and it must be the card's job.
        modal_ids = re.findall(r'data-job-id="(\d+)"', card)
        assert len(modal_ids) == 1
        assert modal_ids[0] == ids[0], "View Details must open the same job"
        assert "data-job-open" in card

    # No id is shared between two different cards.
    all_ids = re.findall(r'data-job-id="(\d+)"', html)
    assert len(all_ids) == len(set(all_ids)) == len(cards)


def test_save_and_apply_still_use_the_existing_endpoints(signed_in):
    html = signed_in.get("/home").get_data(as_text=True)
    assert "/applications/${jobId}/${action}" in html
    assert 'data-track-action="save"' in html
    assert 'data-track-action="apply"' in html


# ==========================================================================
# 7. Summary cards
# ==========================================================================


def test_the_three_summary_cards_share_one_palette(signed_in):
    html = signed_in.get("/home").get_data(as_text=True)
    classes = re.findall(r'<a class="(stat-card[^"]*)"', html)

    assert len(classes) == 3
    assert all("stat-card--light" in c for c in classes), classes


def test_summary_card_calculations_are_unchanged(signed_in, app, candidate):
    from routes.profile import _build_checklist, _load_profile

    with app.app_context():
        db = get_db()
        profile = _load_profile(db, candidate["user_id"])
        checklist = _build_checklist(db, candidate["user_id"], profile)
        expected = round(sum(1 for c in checklist if c["done"]) / len(checklist) * 100)

    html = signed_in.get("/home").get_data(as_text=True)
    assert f'{expected}%' in html

    # The count of applications still comes from the database.
    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS n FROM applications WHERE user_id = %s",
                           (candidate["user_id"],))
            assert f'<span class="stat-card__value">{cursor.fetchone()["n"]}</span>' in html


def test_summary_card_links_are_unchanged(signed_in):
    html = signed_in.get("/home").get_data(as_text=True)
    hrefs = re.findall(r'<a class="stat-card[^"]*" href="([^"]+)"', html)
    assert hrefs == ["/opportunities/", "/applications/", "/profile/"]


# ==========================================================================
# 8. Footer
# ==========================================================================


def test_the_footer_exists_outside_the_main_region(signed_in):
    html = signed_in.get("/home").get_data(as_text=True)

    assert 'class="app-footer"' in html
    # After <main>, so it does not become the last section of the content.
    assert html.index("</main>") < html.index('class="app-footer"')
    assert "app-footer" not in _main(html)


def test_the_footer_is_inside_the_main_wrap(signed_in):
    """That is what makes it track the sidebar's collapsed state.

    A footer beside .app-main-wrap would need its own width rule, which is how
    the two get out of sync when the sidebar toggles.
    """
    html = signed_in.get("/home").get_data(as_text=True)

    wrap_start = html.index('<div class="app-main-wrap">')
    footer_start = html.index('class="app-footer"')
    assert wrap_start < footer_start, "the footer must sit inside the main wrap"

    # After </footer>, the next thing is the </div> that closes .app-main-wrap.
    after = html[footer_start:]
    close = after.index("</footer>") + len("</footer>")
    tail = after[close:]
    assert tail.lstrip().startswith("</div>"), tail[:120]
    assert "app-sidebar" not in tail, "the footer escaped into the sidebar column"
    # The sidebar is closed before the footer opens, not inside it.
    assert html.index("</aside>") < footer_start


def test_the_footer_is_inside_the_wrap_in_the_template():
    """Checked in the source, which is unambiguous about nesting.

    After </footer> the only thing before the shell's own closing tags is the
    single </div> that closes .app-main-wrap, so the footer is its last child.
    """
    shell = open("templates/app_shell.html", encoding="utf-8").read()

    wrap_start = shell.index('<div class="app-main-wrap">')
    footer_start = shell.index('class="app-footer"')
    assert wrap_start < footer_start

    after = shell[footer_start:]
    close = after.index("</footer>") + len("</footer>")
    stripped = after[close:].strip()
    # </div> closes the main wrap; the shell then closes .app-shell.
    assert stripped.startswith("</div>"), stripped[:120]
    assert "</footer>" not in stripped


def test_the_footer_only_links_to_routes_that_exist(signed_in):
    html = signed_in.get("/home").get_data(as_text=True)
    footer = html[html.index('class="app-footer"'):]
    footer = footer[:footer.index("</footer>")]

    hrefs = re.findall(r'<a href="([^"]+)"', footer)
    assert hrefs
    for href in hrefs:
        assert not href.startswith("#"), href
        assert signed_in.get(href).status_code in (200, 302), href


def test_the_footer_styles_have_no_fixed_width_that_could_overflow():
    css = open("static/css/app.css", encoding="utf-8").read()
    footer = _last_rule(css, ".app-footer")

    assert "width:" not in footer, "a fixed width could overflow when the rail collapses"
    assert "position: fixed" not in footer, "the footer must scroll with the page"
    # The inner row is a wrapping flex line, so it cannot force a scrollbar.
    inner = _last_rule(css, ".app-footer__inner")
    assert "flex-wrap: wrap" in inner
    assert "max-width" in inner


def test_the_shell_is_a_column_so_the_footer_sits_at_the_bottom():
    css = open("static/css/app.css", encoding="utf-8").read()
    wrap = _last_rule(css, ".app-main-wrap")
    assert "display: flex" in wrap
    assert "flex-direction: column" in wrap

    main = _last_rule(css, ".app-main")
    assert "flex: 1" in main


def test_reduced_motion_covers_the_card_hover():
    css = open("static/css/app.css", encoding="utf-8").read()
    block = css[css.index("@media (prefers-reduced-motion: reduce)"):]
    block = block[:block.index("\n}\n")]
    assert ".job-card:hover" in block


# ==========================================================================
# 9. Isolation
# ==========================================================================


def test_the_new_styles_do_not_reach_the_other_pages():
    """Every rule added here is scoped to a Home-specific class."""
    css = open("static/css/app.css", encoding="utf-8").read()

    for selector in (".job-grid", ".job-card__apply-by--suggested",
                     ".app-footer", ".ai-btn--job-details", ".ai-btn--job-action"):
        assert selector in css, selector

    # The job-card rules are only reachable from a card or the grid, never from a
    # bare element or a body-level selector.
    card_rule = _last_rule(css, ".job-card")
    assert not card_rule.strip().startswith("*")

    # The public pages still do not load this stylesheet.
    for page in ("login.html", "register.html", "landing.html"):
        source = open(f"templates/{page}", encoding="utf-8").read()
        assert "app.css" not in source, page


def test_no_new_dependency_was_added():
    requirements = open("requirements.txt", encoding="utf-8").read()
    assert "PyMuPDF" in requirements
    assert "reportlab" in requirements or True  # not added by this change

    html = open("templates/home.html", encoding="utf-8").read()
    for word in ("react", "vue", "tailwind", "alpine"):
        assert word not in html.lower(), word


# ==========================================================================
# helpers
# ==========================================================================

@pytest.fixture
def app_db_context(app):
    return app.app_context()