"""Dashboard structure: only the four required sections, nothing below.

This is a presentation contract. It guards against the old lower panels
(Profile & Resume Status, Quick Actions, Applications Tracker, the large Career
Assistant card, and the circular completeness widget) creeping back in, and it
guards the data and links that must survive a redesign.
"""

import html as html_lib
import re

import pytest

from database.db import get_db

STATS = ["Recommended Opportunities", "Applications", "Profile Completeness"]
TOOLS = ["Interview Prep", "Resume Builder", "Cover Letter", "Skill Gap"]

# Panels the redesign removed from the Dashboard.
REMOVED_SELECTORS = [
    ".progress-ring",        # large circular completeness widget
    ".checklist-item",       # Profile & Resume Status
    ".quick-action-item",    # Quick Actions
    ".app-table",            # Application Tracker
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


# ------------------------------------------------------------- structure ---


def test_only_the_four_required_sections(dashboard):
    html = dashboard()
    main = re.search(r'<main class="app-main">(.*)</main>', html, re.S).group(1)
    sections = re.findall(r'<section class="db-[^"]*"', main)
    assert len(sections) == 4, f"expected 4 dashboard sections, found {len(sections)}"


def test_section_order_is_hero_stats_tools_recommended(dashboard):
    html = dashboard()
    positions = [
        html.index('class="db-hero"'),
        html.index('class="db-stats"'),
        html.index("Career Tools"),
        html.index("Recommended for You"),
    ]
    assert positions == sorted(positions), "dashboard sections are out of order"


def test_recommended_for_you_is_the_last_thing_on_the_page(dashboard):
    html = dashboard()
    main = re.search(r'<main class="app-main">(.*)</main>', html, re.S).group(1)
    # The Recommended section is the last one to open; nothing may follow it
    # except the Dashboard's own expand/collapse script.
    section_starts = [m.start() for m in re.finditer(r"<section", main)]
    assert len(section_starts) == 4
    tail = main[section_starts[-1] + 1 :]
    assert "<section" not in tail
    stripped = re.sub(r"<script>.*?</script>", "", tail, flags=re.S).strip()
    assert stripped.endswith("</section>")


@pytest.mark.parametrize("selector", REMOVED_SELECTORS)
def test_removed_panels_are_gone(dashboard, selector):
    assert selector not in dashboard()


@pytest.mark.parametrize("text", REMOVED_TEXT)
def test_removed_headings_are_gone(dashboard, text):
    assert text not in dashboard()


def test_no_large_career_assistant_section(dashboard):
    html = dashboard()
    main = re.search(r'<main class="app-main">(.*)</main>', html, re.S).group(1)
    # The assistant is still reachable, just not as a dashboard panel.
    assert 'class="dash-card"' not in main
    assert "Start Chat" not in main
    # The global floating launcher is untouched.
    assert 'class="chatbot-fab"' in html


# ------------------------------------------------------------ data & links ---


def test_summary_cards_keep_their_dynamic_values(dashboard):
    html = dashboard()
    labels = re.findall(r'<span class="db-stat-label">([^<]+)</span>', html)
    assert labels == STATS
    values = re.findall(r'<span class="db-stat-value">([^<]+)</span>', html)
    assert len(values) == 3
    # Applications count and completeness are still rendered from the route.
    assert re.match(r"^\d+$", values[1])
    assert re.match(r"^\d+%$", values[2])
    assert re.match(r"^\d+$", values[0])


def test_summary_cards_use_existing_routes(dashboard):
    html = dashboard()
    hrefs = re.findall(r'<a class="db-stat[^"]*" href="([^"]+)"', html)
    assert hrefs == ["/opportunities/", "/applications/", "/profile/"]


def test_summary_cards_show_only_a_gt_not_view_text(dashboard):
    for card in re.findall(r'<a class="db-stat.*?</a>', dashboard(), re.S):
        body = re.sub(r"<[^>]+>", " ", card)
        body = html_lib.unescape(re.sub(r"\s+", " ", body)).strip()
        assert "View" not in body
        assert "Open" not in body
        assert body.endswith(">"), body


def test_only_the_three_summary_cards_carry_an_indicator(dashboard):
    """Career Tools and the job cards must have no arrow / ">" / "->" glyph."""
    assert dashboard().count('class="db-stat-go"') == 3

    for tool in re.findall(r'<a class="db-tool.*?</a>', dashboard(), re.S):
        assert "db-tool-go" not in tool

    # No arrow glyph anywhere inside the recommended-jobs area.
    jobs_html = dashboard()[dashboard().index("Recommended for You") :]
    for glyph in ("db-rec-go", "&rarr;", "&#8594;", "→"):
        assert glyph not in jobs_html, glyph


def test_career_tool_cards_use_existing_routes(dashboard):
    html = dashboard()
    titles = re.findall(r'<span class="db-tool-title">([^<]+)</span>', html)
    assert titles == TOOLS
    hrefs = re.findall(r'<a class="db-tool[^"]*" href="([^"]+)"', html)
    assert hrefs == ["/interview/", "/resume-builder/", "/cover-letter/", "/skill-gap/"]


def test_recommendations_are_real_jobs_and_never_padded(dashboard, app):
    """Exactly eight real rows from the jobs table -- never fabricated."""
    titles = re.findall(r'<h3 class="db-rec-title" id="db-rec-title-\d+">([^<]+)</h3>', dashboard())
    assert len(titles) == 8, f"expected exactly 8 recommended jobs, got {len(titles)}"

    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT title FROM jobs")
            known = {row["title"] for row in cursor.fetchall()}

    assert set(titles) <= known, set(titles) - known


def test_each_job_card_has_its_own_view_details_target(dashboard):
    """Every button must open only its own job -- unique, matching panel id."""
    html = dashboard()
    controls = re.findall(r'aria-controls="(db-rec-detail-\d+)"', html)
    panels = re.findall(r'<div class="db-rec-detail" id="(db-rec-detail-\d+)">', html)
    buttons = re.findall(r'class="db-rec-btn"', html)

    assert len(buttons) == 8
    assert len(controls) == 8
    # Each button controls a distinct panel, and each panel has a match.
    assert len(set(controls)) == 8, "a job's View Details button is reused"
    assert set(controls) == set(panels)
    # The id must come from that card's own job_id.
    assert "onclick=\"toggleDbRec('db-rec-detail-" in html
    for panel_id in controls:
        job_id = panel_id.replace("db-rec-detail-", "")
        assert f'toggleDbRec(\'{panel_id}\'' in html, panel_id
        assert re.search(rf'aria-controls="{re.escape(panel_id)}"', html)
        assert f'id="db-rec-title-{job_id}"' in html


def test_expanding_one_card_does_not_stretch_its_row_mates(dashboard):
    """Grid items must keep their own natural height (align-items: start).

    Default grid behaviour is `align-items: stretch`, which made every card in
    the expanded card's row grow to match it.
    """
    css = open("static/css/style.css", encoding="utf-8").read()
    block = css[css.index("DASHBOARD") :]

    grid = re.search(r"\.db-recs\s*\{([^}]*)\}", block).group(1)
    assert "align-items: start" in grid.replace("  ", " "), grid

    card = re.search(r"\.db-rec\s*\{([^}]*)\}", block).group(1)
    assert "align-self: start" in card.replace("\n", " ").replace("  ", " "), card
    # No fixed height that would force every card to the same box.
    assert not re.search(r"(?<!min-)\bheight:", card), card

    # No breakpoint may re-introduce the stretch.
    for media in re.finditer(r"@media \(max-width: \d+px\) \{(.*?)\n\}", block, re.S):
        recs = re.search(r"\.db-recs\s*\{([^}]*)\}", media.group(1))
        if recs:
            assert "align-items" not in recs.group(1), media.group(0)


def test_view_details_panels_are_closed_by_default(dashboard):
    """No panel ships open, and none of them link out to the listing page."""
    html = dashboard()
    assert 'class="db-rec-detail open"' not in html
    assert html.count('aria-expanded="false"') == 8
    # Job cards must not just deep-link to the Opportunities listing.
    assert 'href="/opportunities/?q=' not in html
    # No fake "Apply" affordance: the chips are the existing deep links only.
    chips = set(re.findall(r'<a class="db-rec-chip"[^>]*>([^<]+)</a>', html))
    assert chips <= {"Skill Gap", "Prepare for Interview", "Apply"}


def test_job_grid_is_a_fixed_four_up_layout(dashboard):
    """Option A: a consistent 4-per-row grid, so no lonely 1-card last row."""
    css = open("static/css/style.css", encoding="utf-8").read()
    block_text = css[css.index("DASHBOARD") :]
    rule = re.search(r"\.db-recs\s*\{([^}]*)\}", block_text).group(1)
    assert "grid-template-columns: repeat(4, minmax(0, 1fr))" in rule.replace("  ", " ")

    # The step down to 3 / 2 / 1 columns happens only at narrower viewports.
    steps = {}
    for block in re.finditer(r"@media \(max-width: (\d+)px\) \{(.*?)\n\}", block_text, re.S):
        width, body = block.group(1), block.group(2)
        rule = re.search(r"\.db-recs\s*\{\s*grid-template-columns:\s*([^;]+);", body)
        if rule:
            steps[width] = rule.group(1)

    assert "3" in steps.get("1240", ""), steps
    assert "2" in steps.get("1000", ""), steps
    # Two columns stay usable down to phone width; one only at 560px.
    assert "800" not in steps, steps
    assert "1" in steps.get("560", ""), steps


def test_palette_is_cool_blue_lavender_not_pink(dashboard):
    """Guard the colour direction: cool blues/lavenders, no rose/pink family."""
    css = open("static/css/style.css", encoding="utf-8").read()
    block = css[css.index("DASHBOARD") :]

    for colour in ("#EFF4FF", "#F2F1FD", "#4C63D2", "#F7F9FE"):
        assert colour in block, colour

    # No pink/rose values from the previous palette may remain.
    for pink in ("FFF4EC", "FFF1F6", "FDEFF7", "D9638F", "F2A9C4", "FFF3EA"):
        assert pink not in block, pink


def test_hero_uses_a_blue_to_lavender_gradient(dashboard):
    html = dashboard()
    assert 'class="db-hero"' in html
    css = open("static/css/style.css", encoding="utf-8").read()
    hero = re.search(r"\.db-hero \{([^}]*)\}", css[css.index("DASHBOARD") :]).group(1)
    assert "linear-gradient(128deg, #EFF4FF" in hero
    assert "F2F1FD" in hero


def test_greeting_stays_dynamic(dashboard):
    html = dashboard()
    greeting = re.search(r'<p class="db-hero-greeting">([^<]+)</p>', html).group(1).strip()
    assert greeting in ("Welcome,", "Welcome back,")
    assert "Step1 Candidate" in html
    # No other user's name may be baked into the template.
    assert "Anchal Tripathi" not in html


def test_hero_carries_the_cool_palette(dashboard):
    css = open("static/css/style.css", encoding="utf-8").read()
    block = css[css.index("DASHBOARD REDESIGN" if "DASHBOARD REDESIGN" in css else "DASHBOARD") :]
    for colour in ("EFF4FF", "F2F1FD", "4C63D2"):
        assert colour in block, colour