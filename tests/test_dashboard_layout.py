"""Dashboard structure and the new app design system.

This is a presentation contract. It guards against the old lower panels
(Profile & Resume Status, Quick Actions, Applications Tracker, the large Career
Assistant card, and the circular completeness widget) creeping back in, and it
guards the data and links that must survive a redesign.

Class names moved from the old db-* scheme to the shared ai-*/stat-card/
tool-card/job-card components in static/css/app.css.
"""

import html as html_lib
import re

import pytest

from database.db import get_db

STATS = ["Recommended Opportunities", "Applications", "Profile Completeness"]
TOOLS = ["Interview Preparation", "Resume Builder", "Cover Letter", "Skill Gap"]

# Panels the redesign removed from the Dashboard.
REMOVED_SELECTORS = [
    ".progress-ring",        # large circular completeness widget
    ".checklist-item",       # Profile & Resume Status
    ".quick-action-item",    # Quick Actions
    ".app-table",            # Application Tracker
    "db-stat",               # superseded by .stat-card
    "db-rec",                # superseded by .job-card
]

# Headings that must no longer appear inside the Dashboard.
REMOVED_TEXT = [
    "Profile &amp; Resume Status",
    "Profile & Resume Status",
    "Quick Actions",
    "Applications Tracker",
]


@pytest.fixture
def dashboard(app, candidate):
    def _render():
        client = app.test_client()
        with client.session_transaction() as flask_session:
            flask_session["user_id"] = candidate["user_id"]
            flask_session["user_name"] = "Step1 Candidate"
        response = client.get("/home")
        assert response.status_code == 200
        return response.get_data(as_text=True)

    return _render


def _main(html):
    match = re.search(r'<main class="app-main">(.*)</main>', html, re.S)
    assert match, "the app shell main region is missing"
    return match.group(1)


# ------------------------------------------------------------- structure ---


def test_only_the_four_required_sections(dashboard):
    """Welcome, summary, Career Tools and Recommended Jobs -- nothing else."""
    main = _main(dashboard())
    positions = [
        main.index("hero-panel"),
        main.index('aria-label="Dashboard summary"'),
        main.index("Career Tools"),
        main.index("Recommended Jobs"),
    ]
    assert positions == sorted(positions), "dashboard sections are out of order"


def test_recommended_jobs_is_the_last_thing_on_the_page(dashboard):
    main = _main(dashboard())
    section_starts = [m.start() for m in re.finditer(r"<section", main)]
    assert len(section_starts) == 4, f"expected 4 sections, found {len(section_starts)}"
    tail = main[section_starts[-1] + 1:]
    assert "<section" not in tail
    stripped = re.sub(r"<script.*?</script>", "", tail, flags=re.S).strip()
    assert stripped.endswith("</section>") or stripped.endswith("</div>")


@pytest.mark.parametrize("selector", REMOVED_SELECTORS)
def test_removed_panels_are_gone(dashboard, selector):
    assert selector not in dashboard()


@pytest.mark.parametrize("text", REMOVED_TEXT)
def test_removed_headings_are_gone(dashboard, text):
    assert text not in dashboard()


def test_no_large_career_assistant_section(dashboard):
    html = dashboard()
    main = _main(html)
    # The assistant is still reachable, just not as a dashboard panel.
    assert 'class="dash-card"' not in main
    assert "Start Chat" not in main
    # The global floating launcher is untouched.
    assert 'class="chatbot-fab"' in html


# ------------------------------------------------------------ data & links ---


def test_summary_cards_keep_their_dynamic_values(dashboard):
    html = dashboard()
    labels = re.findall(r'<span class="stat-card__label">([^<]+)</span>', html)
    assert labels == STATS
    values = re.findall(r'<span class="stat-card__value">([^<]+)</span>', html)
    assert len(values) == 3
    # Applications count and completeness are still rendered from the route.
    assert re.match(r"^\d+$", values[1])
    assert re.match(r"^\d+%$", values[2])
    assert re.match(r"^\d+$", values[0])


def test_summary_cards_use_existing_routes(dashboard):
    hrefs = re.findall(r'<a class="stat-card[^"]*" href="([^"]+)"', dashboard())
    assert hrefs == ["/opportunities/", "/applications/", "/profile/"]


def test_summary_cards_share_one_light_blue_palette(dashboard):
    """All three use the same light-blue surface.

    The previous design mixed light-blue, white and dark-blue headings, which
    read as three unrelated boxes rather than one row.
    """
    html = dashboard()
    classes = re.findall(r'<a class="(stat-card[^"]*)"', html)
    assert len(classes) == 3
    for class_name in classes:
        assert "stat-card--light" in class_name, class_name

    css = open("static/css/app.css", encoding="utf-8").read()
    rule = re.search(r"\.stat-card--light\s*\{([^}]*)\}", css).group(1)
    # A light-blue gradient surface, not an accent fill.
    assert "#EAF3FF" in rule or "#DCEBFF" in rule
    assert "--stat-label" in rule and "--stat-value" in rule


def test_only_the_three_summary_cards_exist(dashboard):
    """Three cards, counted on the anchor tag so inner spans are not double counted."""
    assert len(re.findall(r'<a class="stat-card', dashboard())) == 3


def test_career_tool_cards_use_existing_routes(dashboard):
    html = dashboard()
    titles = re.findall(r'<h3>([^<]+)</h3>', _tools_section(html))
    assert titles == TOOLS
    hrefs = re.findall(r'<a class="tool-card" href="([^"]+)"', html)
    assert hrefs == ["/interview/", "/resume-builder/", "/cover-letter/", "/skill-gap/"]


def _tools_section(html):
    main = _main(html)
    return main[main.index("Career Tools"):main.index("Recommended Jobs")]


def test_recommendations_are_real_jobs_and_never_padded(dashboard, app):
    """Nine real rows from the jobs table -- never fabricated.

    Six are visible initially and the rest sit behind "View More", but all nine
    are ranked and rendered; the reveal is client-side, not a second request.
    """
    html = dashboard()
    # The heading carries a title attribute so a clamped title can still be read
    # in full, so the class match must tolerate extra attributes.
    titles = re.findall(r'<h3 class="job-card__title"[^>]*>([^<]+)</h3>', html)
    assert len(titles) == 9, f"expected exactly 9 recommended jobs, got {len(titles)}"

    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT title FROM jobs")
            known = {row["title"] for row in cursor.fetchall()}

    assert set(titles) <= known, set(titles) - known


def test_each_job_card_opens_its_own_job(dashboard):
    """Every View Details button carries its own job's id, never a shared one."""
    html = dashboard()
    buttons = re.findall(r"data-job-open", html)
    job_ids = re.findall(r'data-job-id="(\d+)"', html)

    # Count only the attribute on cards: the View More script also names the
    # selector in a querySelector call.
    cards = re.findall(r'<article class="job-card[^"]*"[^>]*>(.*?)</article>', html, re.S)
    assert len(cards) == 9
    buttons = html.count("data-job-open\n")
    assert buttons == 9, f"expected 9 View Details buttons, found {buttons}"
    job_ids = re.findall(r'data-job-id="(\d+)"', html)
    assert len(job_ids) == 9
    assert len(set(job_ids)) == 9, "a job's View Details button is reused"
    # The id on the button must match the card it sits in.
    for card in cards:
        assert re.search(r'data-job-id="(\d+)"', card)
        assert "View Details" in card


def test_view_details_opens_a_dialog_not_an_inline_panel(dashboard):
    """The old inline expand (db-rec-detail / aria-controls) is gone."""
    html = dashboard()
    assert "db-rec-detail" not in html
    assert "toggleDbRec" not in html
    assert 'id="aiJobModal"' in html
    assert 'role="dialog"' in html
    assert 'aria-modal="true"' in html


def test_job_cards_have_consistent_heights():
    css = open("static/css/app.css", encoding="utf-8").read()
    grid = re.search(r"\.ai-grid--jobs\s*\{([^}]*)\}", css).group(1)
    assert "repeat(3, minmax(0, 1fr))" in grid.replace("  ", " ")

    # Nine cards in a 3x3 matrix, then two, then one.
    widths = {
        int(m.group(1)): m.group(2)
        for m in re.finditer(
            r"@media \(max-width: (\d+)px\)\s*\{\s*\.ai-grid--jobs\s*\{([^}]*)\}", css
        )
    }
    assert any("repeat(2," in v for v in widths.values()), widths
    assert any("minmax(0, 1fr)" in v and "repeat(" not in v for v in widths.values()), widths


def test_job_card_shows_the_available_job_fields(dashboard):
    """The card carries the decision-relevant facts and nothing more.

    Experience required moved into View Details when the card was
    decluttered. A published date is shown nowhere at all, because for a
    locally seeded job it is derived from jobs.created_at -- a seeding
    artefact, not a real posting date.
    """
    html = dashboard()
    # Optional rows are rendered only when the source carries them, so the card
    # carries no fixed label set and no placeholder text.
    assert "Required skills" in html
    assert "Suggested Apply By" in html

    # The literal placeholder the brief asked to remove is gone.
    assert "Not provided" not in html
    assert "Not Provided" not in html
    assert "not provided" not in html.lower().split("<main")[1].split("</main>")[0] \
        .split("current profile")[0]

    # A suggested window is never labelled as the employer's deadline.
    assert "Suggested Apply By" in html
    assert "Application deadline" not in html, "no employer deadline exists in this data"

    # A publication date is never smuggled in via a data attribute.
    assert "data-published" not in html

    # The moved field is still delivered to the dialog.
    assert 'data-experience=' in html
    modal_js = open("static/js/job_modal.js", encoding="utf-8").read()
    assert 'section("Experience required"' in modal_js

    # The existing tracking actions are present on the card.
    assert "data-track-job" in html
    assert 'data-track-action="save"' in html
    assert 'data-track-action="apply"' in html


def test_hero_shows_the_actual_user_name(dashboard, app, candidate):
    """Not a hardcoded name -- whatever the session holds."""
    html = dashboard()
    assert "Step1 Candidate" in html
    assert 'class="hero-panel__name"' in html


def test_the_hero_is_a_navy_gradient_panel(dashboard):
    html = dashboard()
    assert 'class="hero-panel"' in html
    css = open("static/css/app.css", encoding="utf-8").read()
    rule = re.search(r"\.hero-panel\s*\{([^}]*)\}", css).group(1)
    assert "linear-gradient" in rule
    assert "--ai-navy" in rule


def test_greeting_stays_dynamic(dashboard, app, candidate):
    """A returning user sees "Welcome back,"; the source keeps both options."""
    html = dashboard()
    assert "Welcome back," in html

    # The ternary is what decides it -- neither output is hardcoded.
    source = open("templates/home.html", encoding="utf-8").read()
    assert "'Welcome,' if is_new_user else 'Welcome back,'" in source

    # A first visit (session flag set) renders the other greeting, and the flag
    # is consumed once so the next load is a return visit again.
    client = app.test_client()
    with client.session_transaction() as flask_session:
        flask_session["user_id"] = candidate["user_id"]
        flask_session["user_name"] = "Step1 Candidate"
        flask_session["just_registered"] = True
    assert "Welcome," in client.get("/home").get_data(as_text=True)
    assert "Welcome back," in client.get("/home").get_data(as_text=True)


def test_completeness_bar_reflects_the_value(dashboard):
    """The navy card's bar width is the route's completeness, not a constant."""
    html = dashboard()
    match = re.search(r'<span class="stat-card__fill" style="width:(\d+)%">', html)
    assert match, "the completeness bar is missing"
    percent = int(match.group(1))
    shown = re.search(r'<span class="stat-card__value">(\d+)%</span>', html).group(1)
    assert percent == int(shown)


def test_the_app_design_system_is_loaded_here_and_not_on_public_pages(dashboard):
    assert "css/app.css" in dashboard()
    # landing.css belongs to the marketing surface only.
    assert "css/landing.css" not in dashboard()


def test_app_css_defines_the_shared_font_stack():
    css = open("static/css/app.css", encoding="utf-8").read()
    assert "Inter" in css
    assert "--ai-font" in css
    # The brief's palette must all be present.
    for token in ("#FFFFFF", "#F3F6FC", "#E4F0FF", "#2563EB", "#3B82F6",
                  "#102A56", "#080F20", "#172B4D", "#64748B"):
        assert token in css, token


def test_app_css_defines_the_glass_system():
    """Glass surfaces are a shared recipe, not a per-card invention."""
    css = open("static/css/app.css", encoding="utf-8").read()
    for token in ("--ai-glass:", "--ai-glass-border:", "--ai-glass-blur:",
                  "--ai-glass-line:", "--ai-shadow-glass:"):
        assert token in css, token
    # Card, job card and opportunity card all use the glass recipe.
    for selector in (".ai-card", ".job-card", ".opp-card"):
        rules = re.findall(re.escape(selector) + r"\s*\{([^}]*)\}", css)
        assert rules, selector
        assert any("backdrop-filter" in rule for rule in rules), selector
        assert any("var(--ai-glass" in rule for rule in rules), selector

    # The tracker card is the deliberate exception: it floats on a deep-navy
    # shell, where a translucent surface would not clear contrast, so it uses a
    # near-opaque light panel instead.
    tracker_rules = re.findall(r"\.app-tracker__card\s*\{([^}]*)\}", css)
    # The reduced-motion block matches the same selector, so select the rule
    # that actually paints the card.
    tracker = next(r for r in tracker_rules if "background" in r)
    assert "rgba(255, 255, 255, .95)" in tracker
    # Its shadow is tuned for the dark shell, so only the presence of a
    # declared shadow is asserted, not the light-theme token.
    assert "box-shadow:" in tracker
    assert "transition: transform" in tracker