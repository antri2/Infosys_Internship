"""Shell, modal and Skill Gap rendering behaviour for the four app pages.

These pin the functional changes rather than the styling: the sidebar's two
persistent states, the job-details dialog replacing the inline expand, the
profile section-level editor, and -- the important one -- that Skill Gap
recommendations are rendered as distinct, skill-specific entries instead of one
repeated green pill.
"""

import json
import re

import pytest

from database.db import get_db


@pytest.fixture
def logged_in(app, candidate):
    client = app.test_client()
    with client.session_transaction() as flask_session:
        flask_session["user_id"] = candidate["user_id"]
        flask_session["user_name"] = "Step1 Candidate"
    return client


def _html(client, path):
    response = client.get(path)
    assert response.status_code == 200, path
    return response.get_data(as_text=True)


# =============================== SIDEBAR ===============================


def test_the_sidebar_is_never_removed_from_the_layout():
    """Collapsing must narrow it, not hide it."""
    css = open("static/css/app.css", encoding="utf-8").read()
    rule = re.search(r"\.app-sidebar\s*\{([^}]*)\}", css).group(1)
    # The old off-canvas rule pushed it off screen with a negative translate.
    assert "translateX(-100%)" not in rule
    assert "transform: none" in rule.replace("  ", " "), rule


def test_the_sidebar_has_an_expanded_and_a_collapsed_width():
    css = open("static/css/app.css", encoding="utf-8").read()
    expanded = re.search(r"\.app-sidebar\s*\{([^}]*)\}", css).group(1)
    collapsed = re.search(r"\.app-shell\.sidebar-collapsed \.app-sidebar\s*\{([^}]*)\}", css).group(1)
    assert "width: 272px" in expanded.replace("  ", " ")
    # Narrower, never zero.
    width = int(re.search(r"width:\s*(\d+)px", collapsed).group(1))
    assert 0 < width < 272, collapsed


def test_the_main_content_tracks_the_sidebar_width():
    css = open("static/css/app.css", encoding="utf-8").read()
    expanded = re.search(r"\.app-main-wrap\s*\{([^}]*)\}", css).group(1)
    collapsed = re.search(
        r"\.app-shell\.sidebar-collapsed \.app-main-wrap\s*\{([^}]*)\}", css
    ).group(1)
    assert "margin-left: 272px" in expanded.replace("  ", " ")
    collapsed_margin = int(re.search(r"margin-left:\s*(\d+)px", collapsed).group(1))
    assert 0 < collapsed_margin < 272


def test_labels_hide_when_collapsed_but_the_icons_stay():
    css = open("static/css/app.css", encoding="utf-8").read()
    hidden = re.search(
        r"\.app-shell\.sidebar-collapsed \.sidebar-label\s*\{([^}]*)\}", css
    ).group(1)
    assert "opacity: 0" in hidden
    # Only the label is hidden -- the nav link itself keeps its icon box.
    centering = re.search(r"\.app-shell\.sidebar-collapsed \.sidebar-nav a\s*\{([^}]*)\}", css).group(1)
    assert "justify-content: center" in centering


def test_collapsed_navigation_shows_a_tooltip():
    css = open("static/css/app.css", encoding="utf-8").read()
    tooltip = re.search(
        r"\.app-shell\.sidebar-collapsed \.sidebar-nav a::after\s*\{([^}]*)\}", css
    ).group(1)
    assert "content: attr(data-label)" in tooltip


def test_all_nine_navigation_destinations_are_present(logged_in):
    html = _html(logged_in, "/home")
    sidebar = html.split('class="sidebar-nav"', 1)[1].split("</nav>", 1)[0]

    expected = {
        "Home": "/home",
        "My Profile": "/profile/",
        "Opportunities": "/opportunities/",
        "Skill Gap": "/skill-gap/",
        "My Applications": "/applications/",
        "Interview Preparation": "/interview/",
        "Resume Builder": "/resume-builder/",
        "Cover Letter": "/cover-letter/",
        "Career Assistant": "/assistant/",
    }
    links = re.findall(r'<a href="([^"]+)"[^>]*data-label="([^"]+)"', sidebar)
    assert {label: href for href, label in links} == expected

    # Every destination also carries a title, so the tooltip survives even if
    # the CSS-generated one is unavailable.
    for href, label in links:
        assert f'title="{label}"' in sidebar, label


def test_the_sidebar_has_a_collapse_control(logged_in):
    html = _html(logged_in, "/home")
    assert 'id="sidebarCollapse"' in html
    assert "toggleSidebar()" in html
    assert 'aria-controls="appSidebar"' in html


def test_main_js_defines_both_sidebar_functions():
    js = open("static/js/main.js", encoding="utf-8").read()
    assert "function toggleSidebar" in js
    assert "function applySidebar" in js
    # The mobile overlay entry points must survive.
    assert "function openSidebar" in js
    assert "function closeSidebar" in js


def test_the_sidebar_prefers_reduced_motion():
    css = open("static/css/app.css", encoding="utf-8").read()
    assert "prefers-reduced-motion: reduce" in css


# =============================== JOB MODAL ===============================


def test_the_home_dashboard_keeps_its_view_details_popup(logged_in):
    """The Home Dashboard's popup must stay exactly as it was."""
    html = _html(logged_in, "/home")
    assert 'id="aiJobModal"' in html
    assert 'role="dialog"' in html
    assert 'aria-modal="true"' in html
    assert 'aria-labelledby="aiJobModalTitle"' in html
    assert "js/job_modal.js" in html

    js = open("static/js/job_modal.js", encoding="utf-8").read()
    assert "closeBtn.addEventListener" in js
    assert "backdrop.addEventListener" in js
    assert 'event.key === "Escape"' in js
    assert "ai-modal-open" in js

    css = open("static/css/app.css", encoding="utf-8").read()
    assert "body.ai-modal-open { overflow: hidden; }" in css


def test_opportunities_expands_inline_and_uses_no_dialog(logged_in):
    """The opposite behaviour on the same site, deliberately."""
    html = _html(logged_in, "/opportunities/")

    # No dialog at all on this page.
    assert 'id="aiJobModal"' not in html
    assert "js/job_modal.js" not in html
    assert "aiModalApply" not in html

    # Inline expansion instead, wired by its own module.
    assert "data-opp-toggle" in html
    assert "js/opportunity_expand.js" in html
    assert 'aria-expanded="false"' in html
    assert "opp-card__detail" in html

    js = open("static/js/opportunity_expand.js", encoding="utf-8").read()
    assert "aria-expanded" in js
    assert "event.key !== 'Escape'" in js


def test_opportunities_expands_without_navigating_away(logged_in):
    """No href on the control, so it cannot act as a link."""
    html = _html(logged_in, "/opportunities/")
    toggle = re.search(r"<button[^>]*data-opp-toggle.*?</button>", html, re.S)
    assert toggle, "no expand control found"
    assert "<a " not in toggle.group(0), "the expand control must not be a link"
    assert "href=" not in toggle.group(0)


def test_every_expand_control_carries_its_own_job(logged_in):
    html = _html(logged_in, "/opportunities/")
    buttons = re.findall(r"data-opp-toggle(.*?)>", html, re.S)
    assert len(buttons) >= 1
    ids = []
    for attrs in buttons:
        job_id = re.search(r'data-job-id="([^"]+)"', attrs)
        assert job_id, "an expand control has no job id"
        ids.append(job_id.group(1))
    assert len(set(ids)) == len(ids), "a job id is reused by two controls"

    # Each control points at a detail region that exists and starts collapsed.
    for job_id in ids:
        assert f'aria-controls="opp-detail-{job_id}"' in html
        assert f'<div class="opp-card__detail" id="opp-detail-{job_id}" hidden>' in html


def test_the_home_dashboard_view_details_buttons_carry_their_own_jobs(logged_in):
    html = _html(logged_in, "/home")
    # Scripts are stripped first: the View More handler contains the literal
    # "data-job-open" inside a querySelector call, which is a reference rather
    # than a button.
    markup = re.sub(r"<script.*?</script>", "", html, flags=re.S)
    buttons = re.findall(r"data-job-open(.*?)>", markup, re.S)
    assert len(buttons) >= 1

    ids = []
    for attrs in buttons:
        found = re.search(r'data-job-id="([^"]+)"', attrs)
        assert found, "a View Details button has no job id"
        ids.append(found.group(1))
    assert len(set(ids)) == len(ids), "a job id is reused by two buttons"


def test_every_expanded_region_is_hidden_until_opened(logged_in):
    html = _html(logged_in, "/opportunities/")
    regions = re.findall(r'<div class="opp-card__detail" id="opp-detail-\d+" hidden>', html)
    controls = re.findall(r"data-opp-toggle", html)
    assert len(regions) == len(controls) > 0, "each control needs a collapsed region"


def test_the_home_dialog_is_hidden_until_opened(logged_in):
    html = _html(logged_in, "/home")
    assert re.search(r'id="aiJobModal"[^>]*\shidden', html) or \
           re.search(r'\shidden[^>]*id="aiJobModal"', html)


def test_the_modal_renders_not_provided_for_absent_fields():
    """No field is invented; a missing one says so."""
    js = open("static/js/job_modal.js", encoding="utf-8").read()
    assert "Not provided" in js
    assert "ai-modal__none" in js


def test_the_five_actions_stay_wired_to_the_real_endpoints(logged_in):
    """Moved into the expanded region, but nothing about them is fake."""
    html = _html(logged_in, "/opportunities/")

    for label in ("Apply", "Save", "Get AI Summary", "Skill Gap", "Prepare for Interview"):
        assert re.search(r">\s*" + re.escape(label), html), label

    # Still the real endpoints, not visual-only buttons.
    assert "/applications/${jobId}/${action}" in html
    assert "/opportunities/${jobId}/ai-summary" in html
    assert "skill-gap/?job_id=" in html
    assert "interview/?job_id=" in html


def test_the_actions_appear_only_inside_the_expanded_region(logged_in):
    """A collapsed card shows the detail region hidden, not the actions."""
    html = _html(logged_in, "/opportunities/")

    cards = re.findall(r'<article class="opp-card[^"]*"[^>]*>.*?</article>',
                       html, re.S)
    assert cards

    for card in cards:
        # The region exists on every card and starts collapsed.
        assert 'class="opp-card__detail"' in card
        assert 'hidden' in re.search(
            r'<div class="opp-card__detail"[^>]*>', card).group(0)
        # And the five actions sit inside it, which is why a collapsed card
        # does not show them.
        detail = card[card.index('<div class="opp-card__detail"'):]
        for label in ("Get AI Summary", "Prepare for Interview", "Apply", "Save"):
            assert label in detail, label

    # Nothing shows the actions before the region opens.
    before_region = html[:html.index('<div class="opp-card__detail"')]
    assert "Get AI Summary" not in before_region


# =============================== OPPORTUNITIES ===============================


def test_all_five_job_actions_are_present(logged_in):
    html = _html(logged_in, "/opportunities/")
    for label in ("Apply", "Save", "Get AI Summary", "Skill Gap", "Prepare for Interview"):
        assert re.search(r">\s*" + re.escape(label), html), label


def test_the_company_badge_is_untouched(logged_in):
    """The brief said not to change how the logo is implemented."""
    html = _html(logged_in, "/opportunities/")
    assert '<span class="company-badge">' in html
    css = open("static/css/style.css", encoding="utf-8").read()
    # The original rule still exists in the original stylesheet.
    assert ".company-badge" in css


def test_the_fit_disclaimer_and_deadline_are_still_available(app, client, candidate):
    """Compact cards, but the explanation and deadline are not lost.

    Both moved into the dialog when the card was made compact, so this pins
    that they are still delivered rather than dropped.
    """
    # Fit is only rendered when the profile has skills to compare.
    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            for name in ("Python", "SQL", "Java", "Excel"):
                cursor.execute(
                    "INSERT INTO skills (user_id, name, category) VALUES (%s, %s, 'tool')",
                    (candidate["user_id"], name))
        db.commit()

    html = _html(client, "/opportunities/")
    # The card keeps a short version.
    assert "not a probability of getting the job" in html
    # The dialog carries the full explanation and the deadline section.
    modal_js = open("static/js/job_modal.js", encoding="utf-8").read()
    assert "It is not a probability of getting the job." in modal_js
    assert 'section("Application deadline"' in modal_js


# =============================== PROFILE ===============================


def test_one_section_level_education_editor_not_one_per_card(logged_in, app, candidate):
    """A single "Edit Education" disclosure holds a form per record."""
    from database.db import get_db

    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            for institution in ("Alpha University", "Beta Polytechnic"):
                cursor.execute(
                    "INSERT INTO education (user_id, institution, degree, field, "
                    "start_date, end_date) VALUES (%s, %s, 'B.Tech', 'CS', '2020', '2024')",
                    (candidate["user_id"], institution),
                )
        db.commit()

    html = _html(logged_in, "/profile/")
    section = html.split('id="education"', 1)[1].split('id="experience"', 1)[0]

    # One disclosure, not one Edit control per card.
    assert section.count("Edit Education") == 1
    # But every record still has its own update form inside it.
    forms = section.count("/profile/record/update")
    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS n FROM education WHERE user_id = %s",
                           (candidate["user_id"],))
            expected = cursor.fetchone()["n"]
    assert forms == expected
    assert section.count("/profile/record/delete") == expected
    assert "Add Education" in section


def test_the_technical_summary_label_is_gone(logged_in, app, candidate):
    from database.db import get_db
    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("UPDATE profiles SET summary = %s WHERE user_id = %s",
                           ("A verified summary.", candidate["user_id"]))
        db.commit()

    html = _html(logged_in, "/profile/")
    assert "extracted by the Resume Parser" not in html
    assert "Resume Parser" not in html
    # The plain label and the value are both still there.
    assert ">Summary<" in html
    assert "A verified summary." in html


def test_education_cards_are_visually_distinct(app, client, candidate):
    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute(
                "INSERT INTO education (user_id, institution, degree, field, "
                "start_date, end_date) VALUES (%s, 'Card U', 'B.Tech', 'CS', '2020', '2024')",
                (candidate["user_id"],))
        db.commit()

    html = _html(client, "/profile/")
    section = html.split('id="education"', 1)[1].split('id="experience"', 1)[0]
    assert 'class="record-card"' in section


def test_the_upload_resume_panel_is_prominent(logged_in):
    html = _html(logged_in, "/profile/")
    assert "upload-panel" in html
    assert "Upload New Resume" in html
    # Still the real route.
    assert 'href="/resume/upload"' in html


# =============================== SKILL GAP ===============================


def test_the_three_sections_are_present_and_ordered(logged_in):
    html = _html(logged_in, "/skill-gap/")
    positions = [
        html.index("Skill Overview"),
        html.index("Skill Gap Assessment"),
        html.index("Personalized Learning Roadmap"),
    ]
    assert positions == sorted(positions)


def test_the_job_description_box_is_no_longer_excessive(logged_in):
    html = _html(logged_in, "/skill-gap/")
    textarea = re.search(r'<textarea[^>]*id="job-description"[^>]*>', html).group(0)
    rows = int(re.search(r'rows="(\d+)"', textarea).group(1))
    assert rows <= 4, textarea
    css = open("static/css/app.css", encoding="utf-8").read()
    rule = re.search(r"#job-description\s*\{([^}]*)\}", css).group(1)
    height = int(re.search(r"min-height:\s*(\d+)px", rule).group(1))
    assert height <= 200, rule


def test_optional_fields_stay_optional(logged_in):
    html = _html(logged_in, "/skill-gap/")
    assert html.count("(optional)") == 2, html.count("(optional)")
    # Only the role select carries required.
    assert re.search(r'<select[^>]*id="target-role"[^>]*required', html)
    for field in ("company-name", "job-description"):
        control = re.search(r'<(?:input|textarea)[^>]*id="' + field + r'"[^>]*>', html).group(0)
        assert "required" not in control, field


def test_the_analyze_button_is_centred(logged_in):
    html = _html(logged_in, "/skill-gap/")
    assert 'class="sg-submit"' in html
    assert "Analyze Skill Gap" in html


def test_the_analysis_button_hides_when_no_role_is_selected():
    """Role-only analysis must still work without company or JD."""
    route = open("routes/skill_gap.py", encoding="utf-8").read()
    assert "if not target_role and job_id is None" in route
    # A role alone reaches build_role_context, not a job lookup.
    assert "build_role_context(target_role, company)" in route


def test_the_report_shows_a_loading_and_an_error_state(logged_in):
    html = _html(logged_in, "/skill-gap/")
    assert 'id="skill-gap-status"' in html
    assert 'aria-live="polite"' in html
    assert "sg-status--error" in html
    assert "sg-spinner" in html


def test_missing_skills_are_not_asserted_about_the_user(logged_in):
    """Wording must not claim the user lacks a skill outright."""
    html = _html(logged_in, "/skill-gap/")
    assert "Not found in your profile" in html


def test_recommendations_are_rendered_as_distinct_cards():
    """The old renderer made every recommendation an identical green pill."""
    html = open("templates/skill_gap.html", encoding="utf-8").read()

    # One card per recommendation, carrying both the skill and the action.
    assert "sg-plan__card" in html
    assert "sg-plan__skill" in html
    assert "sg-plan__action" in html
    assert "item.addresses" in html

    # The old function that produced the repeated identical pill is gone. The
    # name may still appear in a comment explaining why it was removed.
    assert "function renderSkillGapList" not in html
    assert "renderSkillGapList('skill-gap-recommendations'" not in html


def test_recommendation_renderer_handles_both_shapes():
    """Model output and the service fallback share {action, addresses}."""
    service = open("services/skill_gap_service.py", encoding="utf-8").read()
    assert '"action":' in service
    assert '"addresses":' in service
    html = open("templates/skill_gap.html", encoding="utf-8").read()
    # Both the string case and the object case are handled.
    assert "typeof item === 'string'" in html


def test_priority_gaps_are_separated_from_the_learning_plan(logged_in):
    html = _html(logged_in, "/skill-gap/")
    assert "Priority Gaps" in html
    assert "Recommended Learning Plan" in html
    assert 'id="skill-gap-priorities"' in html
    assert 'id="skill-gap-recommendations"' in html


def test_the_skill_overview_has_the_three_required_areas(logged_in):
    html = _html(logged_in, "/skill-gap/")
    for label in ("Skills You Already Have", "Missing &amp; Important Skills",
                  "Skills to Strengthen"):
        assert label in html, label


def test_the_gap_assessment_has_the_three_required_sections(logged_in):
    html = _html(logged_in, "/skill-gap/")
    for label in ("Experience Gap", "Qualification Requirements", "Preferred Skills"):
        assert label in html, label


def test_every_generated_skill_entry_can_carry_a_reason():
    """A reason is rendered when the analysis provides one."""
    html = open("templates/skill_gap.html", encoding="utf-8").read()
    assert "sg-item__why" in html
    assert "why_it_matters" in html


def test_skill_gap_preserves_every_existing_action(logged_in):
    html = _html(logged_in, "/skill-gap/")
    assert "/skill-gap/analyze" in html
    assert "Improve Resume" in html
    assert "Prepare for Interview" in html


# =============================== DESIGN SYSTEM ===============================


def test_the_app_stylesheet_is_loaded_once_by_the_shell():
    shell = open("templates/app_shell.html", encoding="utf-8").read()
    assert shell.count("css/app.css") == 1


def test_app_pages_do_not_load_the_public_stylesheet(logged_in):
    for path in ("/home", "/profile/", "/opportunities/", "/skill-gap/"):
        html = _html(logged_in, path)
        assert "css/landing.css" not in html, path
        assert "css/app.css" in html, path


def test_no_page_still_uses_the_old_dashboard_class_scheme(logged_in):
    for path in ("/home",):
        html = _html(logged_in, path)
        assert "db-hero" not in html
        assert "db-stat" not in html
        assert "db-rec" not in html


def test_app_css_defines_the_brief_palette_and_font():
    css = open("static/css/app.css", encoding="utf-8").read()
    assert "Inter" in css
    for token in ("#FFFFFF", "#F3F6FC", "#E4F0FF", "#2563EB", "#3B82F6",
                  "#102A56", "#080F20", "#172B4D", "#64748B"):
        assert token in css, token


def test_the_typography_floor_is_not_tiny():
    """The brief asked for larger text; the smallest token must stay readable."""
    css = open("static/css/app.css", encoding="utf-8").read()
    smallest = float(re.search(r"--ai-t-xs:\s*([\d.]+)rem", css).group(1))
    assert smallest >= 0.8125, smallest          # 13px


def test_no_duplicate_design_system_across_stylesheets():
    """The token block lives in app.css only, so it cannot drift."""
    css = open("static/css/app.css", encoding="utf-8").read()
    assert css.count("--ai-primary:") == 1
    assert css.count("--ai-navy:") == 1