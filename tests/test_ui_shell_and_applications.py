"""Shell, dashboard and My Applications contracts introduced by the redesign.

Covers the pieces that were changed functionally rather than cosmetically:

  * the sidebar toggle is an arrow in its own slot, with a pre-paint restore so
    navigating while collapsed cannot flash the expanded state;
  * the topbar search is centred by an explicit three-track grid;
  * the three summary cards share one type scale;
  * the Opportunities card is compact again, with the detail sections moved
    into the dialog rather than dropped;
  * Save/Apply feedback is a non-blocking toast that reflects the real outcome
    -- and the blocking window.alert() is gone;
  * My Applications offers a contextual Next Step for every stored status and
    never leaves an empty box;
  * a refused tracking write reports the constraint that actually failed.
"""

import re

import pymysql
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


def _css():
    return open("static/css/app.css", encoding="utf-8").read()


def _template(name):
    return open(f"templates/{name}", encoding="utf-8").read()


# =============================== SIDEBAR TOGGLE =========================


def test_the_toggle_is_a_directional_arrow_not_a_three_dot_menu():
    shell = _template("app_shell.html")
    toggle = re.search(
        r'<button[^>]*class="sidebar-collapse".*?</button>', shell, re.S
    ).group(0)

    # An arrow, not the three-line menu glyph that used to sit here.
    assert "chevron-left" in toggle
    assert "chevron" in _template("_icons.html")
    # Both directions exist so the control can indicate either state.
    for name in ("chevron-left", "chevron-right"):
        assert f'name == "{name}"' in _template("_icons.html")

    # It is not the wordmark, and it cannot merge into it.
    assert "sidebar-logo-mark" in shell


def test_the_toggle_rotates_to_indicate_the_collapsed_state():
    css = _css()
    rule = re.search(
        r"\.app-shell\.sidebar-collapsed \.sidebar-collapse-icon \.icon\s*\{([^}]*)\}",
        css,
    )
    assert rule, "collapsed icon rule missing"
    assert "rotate(180deg)" in rule.group(1)

    # And it never compresses, so it keeps its own slot beside the wordmark.
    base = re.search(r"\.sidebar-collapse\s*\{([^}]*)\}", css).group(1)
    assert "flex-shrink: 0" in base


def test_the_collapsed_state_is_restored_before_the_first_paint():
    """The flicker cause: the restore used to run on DOMContentLoaded.

    By then the browser had already painted the sidebar expanded. The class is
    now applied by an inline script in <head>, so the first frame is correct.
    """
    base = _template("base.html")
    head = base[: base.index("</head>")]
    assert "careerai:sidebar-collapsed" in head, "restore script must precede </head>"
    assert "sidebar-collapsed" in head
    # It runs inline in the head, before the body is parsed.
    assert base.index("careerai:sidebar-collapsed") < base.index("</head>")

    js = open("static/js/main.js", encoding="utf-8").read()
    restore = re.search(r"function restoreSidebar\(\)\s*\{(.*?)\n\}", js, re.S).group(1)
    # main.js adopts the pre-paint class instead of re-reading storage late.
    assert "document.documentElement.classList.contains" in restore


def test_collapsed_navigation_is_tighter_and_keeps_its_tooltips():
    css = _css()
    collapsed_nav = re.search(
        r"\.app-shell\.sidebar-collapsed \.sidebar-nav\s*\{([^}]*)\}", css
    )
    assert collapsed_nav, "collapsed nav rule missing"
    assert "gap:" in collapsed_nav.group(1)

    collapsed_links = re.search(
        r"\.app-shell\.sidebar-collapsed \.sidebar-nav a\s*\{([^}]*)\}", css
    ).group(1)
    assert "justify-content: center" in collapsed_links

    shell = _template("app_shell.html")
    # Every navigation destination keeps a tooltip source for the icon-only
    # state: data-label drives the CSS tooltip, title is the native fallback.
    nav = shell[shell.index('<nav class="sidebar-nav">'): shell.index("</nav>")]
    links = re.findall(r"<a\s[^>]*>", nav, re.S)
    assert len(links) == 9, f"expected 9 destinations, found {len(links)}"
    for link in links:
        assert "data-label=" in link, link
        assert "title=" in link, link


def test_the_two_sidebar_states_keep_the_same_navigation_order():
    shell = _template("app_shell.html")
    nav = shell[shell.index('<nav class="sidebar-nav">'): shell.index("</nav>")]
    hrefs = re.findall(r'<a\s[^>]*?href="([^"]+)"', nav, re.S)
    assert len(hrefs) == 9
    assert len(set(hrefs)) == 9, "navigation destinations must be distinct"
    # No placeholder destination anywhere in the shell.
    assert 'href="#"' not in shell


# =============================== SEARCH BAR =============================


def test_the_search_bar_is_centred_by_an_explicit_three_track_grid():
    css = _css()
    topbar = re.search(r"\.app-topbar\s*\{([^}]*)\}", css).group(1)
    assert "grid-template-columns" in topbar
    # Two flexible side tracks around a bounded middle one, which is what keeps
    # the field centred instead of merely filling the leftover space.
    assert "minmax(0, 1fr)" in topbar
    assert topbar.count("minmax(0, 1fr)") == 2

    shell = _template("app_shell.html")
    assert shell.count("topbar-slot") >= 2, "start and end slots required"
    # The search behaviour is untouched: same action, same parameter.
    assert 'name="q"' in shell
    assert "opportunities.list_view" in shell


def test_the_search_rule_resets_the_max_width_inherited_from_style_css():
    """A real regression caught in the browser.

    style.css still sets max-width:420px on .topbar-search. Omitting a
    declaration does not reset an earlier sheet's value, so the form was
    clamped to 420px inside its 560px track and sat off-centre.
    """
    css = _css()
    rule = re.search(r"\.topbar-search\s*\{([^}]*)\}", css).group(1)
    assert "max-width: none" in rule, rule

    style = open("static/css/style.css", encoding="utf-8").read()
    assert "max-width: 420px" in style, "the conflicting declaration should still be there"


# =============================== SUMMARY CARDS =========================


def test_the_three_summary_cards_share_one_text_scale():
    """Same sizes and weights everywhere; only colour tokens differ.

    This replaces the previous light-blue / white / dark-blue heading mix,
    which forced a different colour per card for no semantic reason.
    """
    css = _css()
    # .stat-card has more than one rule; the tokens live in the one that sets
    # them, so the declaration is searched for rather than assumed first.
    stat_rules = re.findall(r"\.stat-card\s*\{([^}]*)\}", css)
    base = next((r for r in stat_rules if "--stat-label" in r), None)
    assert base, "no .stat-card rule declares the text tokens"
    for token in ("--stat-label", "--stat-meta", "--stat-value"):
        assert token in base, token

    accents = re.search(r"\.stat-card--electric,\s*\.stat-card--navy\s*\{([^}]*)\}", css)
    assert accents, "accent colour tokens missing"
    for token in ("--stat-label", "--stat-meta", "--stat-value"):
        assert token in accents.group(1), token

    # The three parts read their colour from the token, not from a hard-coded
    # hue, so only one rule can drift.
    for part in ("label", "value", "meta"):
        rule = re.search(rf"\.stat-card__{part}\s*\{{([^}}]*)\}}", css).group(1)
        assert f"var(--stat-{part})" in rule, part

    # Type settings are declared once and are not re-specified per surface.
    label = re.search(r"\.stat-card__label\s*\{([^}]*)\}", css).group(1)
    assert "font-weight: 700" in label
    assert "letter-spacing" in label


def test_the_summary_cards_keep_all_three_values_and_their_links(logged_in):
    """The redesign is presentational: no value, label or link was dropped."""
    html = _html(logged_in, "/home")

    cards = re.findall(r'<a class="(stat-card[^"]*)" href="([^"]+)"(.*?)</a>', html, re.S)
    assert len(cards) == 3

    labels = [re.search(r'stat-card__label">([^<]+)<', body).group(1)
              for _, _, body in cards]
    assert labels == ["Recommended Opportunities", "Applications", "Profile Completeness"]

    # Each value is still rendered from the route's own number.
    for _, _, body in cards:
        assert re.search(r'stat-card__value">(\d+)(?:%)?<', body)

    assert "/opportunities/" in [href for _, href, _ in cards]
    assert "/applications/" in [href for _, href, _ in cards]
    assert "/profile/" in [href for _, href, _ in cards]


def test_career_tool_icons_are_centred_in_their_wells():
    css = _css()
    rule = re.search(r"\.tool-card__icon\s*\{([^}]*)\}", css).group(1)
    assert "justify-content: center" in rule
    assert "align-items: center" in rule
    # A fixed square, so the glyph cannot drift with the card's content.
    width = re.search(r"width:\s*(\d+)px", rule).group(1)
    height = re.search(r"height:\s*(\d+)px", rule).group(1)
    assert width == height


def test_the_welcome_section_is_layered_rather_than_one_solid_block():
    css = _css()
    hero = re.search(r"\.hero-panel\s*\{([^}]*)\}", css).group(1)
    # A gradient base, not a flat fill.
    assert "linear-gradient" in hero
    assert "radial-gradient" in hero, "a soft blue pool gives the panel depth"

    # Two surfaces: the text column and a translucent aside.
    assert "grid-template-columns" in hero
    aside = re.search(r"\.hero-panel__aside\s*\{([^}]*)\}", css).group(1)
    assert "backdrop-filter" in aside
    assert "rgba(255, 255, 255" in aside

    # And it stacks rather than squeezing the greeting on narrow screens.
    stacked = [rule for rule in re.findall(r"\.hero-panel\s*\{([^}]*)\}", css)
               if "minmax(0, 1fr)" in rule]
    assert stacked


def test_the_welcome_section_still_shows_the_signed_in_name(logged_in):
    html = _html(logged_in, "/home")
    assert "Step1 Candidate" in html
    assert 'class="hero-panel__name"' in html
    # The greeting is still chosen by the existing ternary.
    assert "'Welcome,' if is_new_user else 'Welcome back,'" in _template("home.html")


# =============================== RECOMMENDED JOBS ======================


def test_the_recommended_job_card_carries_only_the_decision_facts(logged_in):
    html = _html(logged_in, "/home")
    card = re.search(r'<article class="job-card[^"]*"[^>]*>(.*?)</article>',
                     html, re.S).group(1)

    # Optional facts render as rows only when the source carries them, so the
    # card is not padded out with fixed labels standing in for missing data.
    assert "job-card__facts" in card
    assert "Required skills" in card

    # No placeholder is rendered in place of a missing field.
    assert "Not provided" not in card
    assert "Not Provided" not in card

    # A suggested window carries its own label, so it can never read as an
    # employer deadline -- and no employer deadline exists in this data.
    assert "Suggested Apply By" in card
    assert "Application deadline" not in card

    # View Details leads the action row and is the one that opens the dialog.
    actions = re.search(r'<div class="job-card__actions">(.*?)</div>', card, re.S).group(1)
    assert "View Details" in actions
    assert actions.index("View Details") < actions.index("Save")
    # The two button treatments the brief specifies.
    assert "ai-btn--job-details" in actions
    assert actions.count("ai-btn--job-action") == 2
    # The existing tracking endpoints and job id are untouched.
    assert 'data-track-action="save"' in actions
    assert 'data-track-action="apply"' in actions
    assert re.search(r'data-track-job="\d+"', actions)


def test_every_job_card_uses_the_same_hierarchy(logged_in):
    html = _html(logged_in, "/home")
    cards = re.findall(r'<article class="job-card[^"]*"[^>]*>(.*?)</article>',
                      html, re.S)
    assert cards
    for card in cards:
        # Identity block, title, facts, skills, actions: one fixed order.
        for class_name in ("job-card__head", "job-card__title", "job-card__facts",
                           "job-card__skills", "job-card__actions"):
            assert class_name in card, class_name
        assert card.index("job-card__head") < card.index("job-card__title")
        assert card.index("job-card__title") < card.index("job-card__facts")
        assert card.index("job-card__facts") < card.index("job-card__skills")
        assert card.index("job-card__skills") < card.index("job-card__actions")


def test_skill_tags_distinguish_matched_from_required(logged_in):
    """Green/blue here is a defined status, not decoration."""
    html = _html(logged_in, "/home")
    pills = re.findall(r'<span class="ai-pill (ai-pill--[a-z]+)"', html)
    assert pills
    # Three defined states: matched, required-but-missing, and the overflow
    # summary standing in for the skills a truncated row does not show.
    assert set(pills) <= {"ai-pill--have", "ai-pill--required", "ai-pill--more"}

    # The overflow pill never hides a skill silently.
    for pill in re.findall(r'<span class="ai-pill ai-pill--more"[^>]*>', html):
        assert "title=" in pill, pill


# =============================== OPPORTUNITIES ==========================


def test_the_opportunity_card_is_compact_again(logged_in):
    """Title, company, location, Skill Fit and View Details -- nothing else."""
    html = _html(logged_in, "/opportunities/")
    card = re.search(r'<article class="opp-card[^"]*"[^>]*>(.*?)</article>',
                     html, re.S).group(1)

    # What stays on the collapsed card.
    assert "opp-card__title" in card
    assert "opp-card__company" in card
    assert "opp-card__meta" in card
    assert "match-badge" in card
    assert "data-opp-toggle" in card

    # Fit and the expand control sit together in the card's corner.
    assert "opp-card__corner" in card

    # The actions are not on the collapsed card, only inside the hidden region.
    collapsed = card[:card.index('<div class="opp-card__detail"')]
    for label in ("Get AI Summary", "Prepare for Interview"):
        assert label not in collapsed, label

    # And the region that holds them starts collapsed.
    assert 'class="opp-card__detail"' in card
    assert re.search(r'<div class="opp-card__detail"[^>]*\shidden', card)


def test_all_five_opportunity_actions_survive(logged_in):
    """Preserved, now inside the expanded region rather than on the card face."""
    html = _html(logged_in, "/opportunities/")
    card = re.search(r'<article class="opp-card[^"]*"[^>]*>(.*?)</article>',
                     html, re.S).group(1)
    detail = card[card.index('<div class="opp-card__detail"'):]

    for label in ("Save", "Apply", "Get AI Summary", "Skill Gap", "Prepare for Interview"):
        assert label in detail, label
    assert "View Details" in card

    # And the handlers/routes are the existing ones, not new endpoints.
    # url_for renders to a URL, so the URL is what is checked -- a stronger
    # assertion, because it proves the control points at a real route.
    assert "trackApplication(" in detail
    assert "getAISummary(" in detail
    assert "/skill-gap/?job_id=" in detail
    assert "/interview/?job_id=" in detail
    assert "target_source=custom" in detail


def test_the_dialog_still_carries_every_moved_detail_section():
    js = open("static/js/job_modal.js", encoding="utf-8").read()
    for section in ("Job summary", "Job details", "Why this matches your profile",
                    "Skills fit", "Skill comparison", "Responsibilities",
                    "Qualifications", "Experience required"):
        assert section in js, section

    # The four skill groups the Opportunities page used to show.
    for group in ("Required skills", "Preferred skills",
                  "Your profile skills (matched)", "Skills to learn"):
        assert group in js, group


def test_the_card_carries_the_data_the_dialog_needs(logged_in):
    html = _html(logged_in, "/opportunities/")
    card = re.search(r'<article class="opp-card[^"]*"[^>]*>(.*?)</article>',
                     html, re.S).group(1)
    for attr in ("data-description=", "data-match-reasons=", "data-required-skills=",
                 "data-preferred-skills=", "data-matched-skills=", "data-missing-skills=",
                 "data-work-mode=", "data-experience=", "data-deadline="):
        assert attr in card, attr


def test_company_logos_are_left_as_they_were(logged_in):
    """Rendered exactly as the pre-existing company-badge element."""
    html = _html(logged_in, "/opportunities/")
    card = re.search(r'<article class="opp-card[^"]*"[^>]*>(.*?)</article>',
                     html, re.S).group(1)
    # The rendered card still uses the pre-existing company-badge element.
    assert re.search(r'<span class="company-badge">\s*\w\s*</span>', card)

    # And the template still derives it from the job's own first letter, with
    # no image or lookup introduced.
    template = _template("opportunities.html")
    assert re.search(
        r'<span class="company-badge">\{\{ job\.company\[0\] \| upper \}\}</span>',
        template,
    )
    assert "<img" not in card


# =============================== SAVE / APPLY FEEDBACK ==================


def test_no_blocking_alert_remains_on_the_five_pages():
    for name in ("home.html", "opportunities.html", "applications.html",
                 "profile.html", "skill_gap.html"):
        source = _template(name)
        assert "alert(" not in source, name
        assert "window.alert" not in source, name


def test_the_toast_is_non_blocking_and_cannot_cover_a_card():
    css = _css()
    rule = re.search(r"\.toast-host\s*\{([^}]*)\}", css).group(1)
    # Fixed at the bottom, so it never sits over the content being acted on.
    assert "position: fixed" in rule
    assert "bottom:" in rule
    assert "pointer-events: none" in rule, "must not block the page"

    # The toast rule itself: the reduced-motion block matches the same selector,
    # so select the one that declares the pointer behaviour.
    toast_rules = re.findall(r"\.toast\s*\{([^}]*)\}", css)
    toast = next(r for r in toast_rules if "pointer-events" in r)
    assert "pointer-events: auto" in toast

    # The two outcomes are visually distinct, which is what makes the message
    # readable at a glance.
    assert re.search(r"\.toast--success\s*\{([^}]*)\}", css).group(1)
    assert re.search(r"\.toast--error\s*\{([^}]*)\}", css).group(1)


def test_the_toast_helper_announces_itself_to_screen_readers():
    js = open("static/js/main.js", encoding="utf-8").read()
    assert "function showToast" in js
    assert "aria-live" in js
    # Errors are assertive, successes are polite.
    assert '"alert"' in js
    assert '"status"' in js


def test_a_failed_save_is_never_reported_as_success():
    """The outcome shown must come from the response, not from optimism."""
    for name in ("home.html", "opportunities.html"):
        source = _template(name)
        # Errors go through the error branch of the toast.
        assert "'error'" in source, name
        # And the button label is never overwritten with a long server message.
        assert "textContent = data.message" not in source, name


# =============================== MY APPLICATIONS ========================


def _make_applications(app, user_id, resume_id):
    """One application per stored status, so every branch can be exercised."""
    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT job_id FROM jobs ORDER BY job_id LIMIT 5")
            job_ids = [row["job_id"] for row in cursor.fetchall()]
            for job_id, status in zip(
                job_ids, ["saved", "applied", "interview", "under_review", "rejected"]
            ):
                cursor.execute(
                    "INSERT INTO applications (user_id, job_id, resume_id, status) "
                    "VALUES (%s, %s, %s, %s)",
                    (user_id, job_id, resume_id, status),
                )
        db.commit()
    return job_ids


def test_every_status_filter_is_preserved(logged_in):
    html = _html(logged_in, "/applications/")
    for label in ("All", "Saved", "Applied", "Interview", "Under Review", "Rejected"):
        assert label in html, label
    assert "applications-filters" in html


def test_the_applications_page_uses_a_distinct_deep_navy_treatment():
    css = _css()
    page = re.search(r"\.applications-page\s*\{([^}]*)\}", css).group(1)
    # Deep navy base rather than the shared light ambient wash.
    assert "var(--ai-navy-deep)" in page
    assert "linear-gradient" in page

    # And it is not the same background as every other page: the shared shell
    # is light, this panel is dark.
    tokens = re.search(r":root\s*\{([^}]*)\}", css).group(1)
    assert "--ai-bg: #F3F6FC" in tokens, "the shared page base is light"
    shell = re.search(r"\.app-shell\s*\{([^}]*)\}", css).group(1)
    assert "var(--ai-bg)" in shell
    assert "#F3F6FC" not in page

    assert ".app-tracker__card" in css


def test_every_status_gets_a_next_step_with_no_empty_box(app, candidate, logged_in):
    resume_id = candidate["resume_id"]
    _make_applications(app, candidate["user_id"], resume_id)
    html = _html(logged_in, "/applications/")

    cards = re.findall(r'<article class="app-tracker__card">(.*?)</article>', html, re.S)
    assert len(cards) == 5

    for card in cards:
        status = re.search(r'class="status-badge [a-z_]+">([^<]+)<', card).group(1).strip()

        # The Next Step block runs to the end of the card.
        marker = '<div class="app-tracker__next'
        assert marker in card, f"no Next Step block for status {status}"
        block = card[card.index(marker):]

        # Never blank: there is always a message.
        text = re.search(r'app-tracker__next-text">(.*?)</span>', block, re.S)
        assert text and text.group(1).strip(), f"empty Next Step text for {status}"

        # And always something to do: a real route, or an honest status message.
        action = re.search(
            r'<(?:a|button)[^>]*class="ai-btn[^"]*"[^>]*>(.*?)</(?:a|button)>', block, re.S
        )
        assert action and action.group(1).strip(), f"no action for {status}"


def test_the_next_step_reflects_the_stored_status(app, candidate, logged_in):
    _make_applications(app, candidate["user_id"], candidate["resume_id"])
    html = _html(logged_in, "/applications/")

    expected = {
        "Saved": "Apply for this job",
        "Applied": "Prepare for Interview",
        "Interview": "Prepare for Interview",
        "Under Review": "Skill Gap",
        "Rejected": "Explore other opportunities",
    }
    for card in re.findall(r'<article class="app-tracker__card">(.*?)</article>', html, re.S):
        status = re.search(r'class="status-badge [a-z_]+">([^<]+)<', card).group(1).strip()
        assert expected[status] in card, status


def test_the_next_step_links_only_to_working_routes(app, candidate, logged_in):
    _make_applications(app, candidate["user_id"], candidate["resume_id"])
    client = logged_in
    html = _html(client, "/applications/")

    links = re.findall(
        r'<a[^>]*class="ai-btn[^"]*"[^>]*href="([^"]+)"', html, re.S
    )
    assert links, "no Next Step links found"
    for href in links:
        # Every destination resolves; none is a placeholder.
        assert not href.startswith("#")
        assert href.startswith("/")
        assert client.get(href).status_code in (200, 302), href


def test_the_next_step_does_not_change_any_status(app, candidate, logged_in):
    """A suggestion is not an action on the record."""
    _make_applications(app, candidate["user_id"], candidate["resume_id"])
    _html(logged_in, "/applications/")

    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute(
                "SELECT status FROM applications WHERE user_id = %s",
                (candidate["user_id"],),
            )
            before = sorted(row["status"] for row in cursor.fetchall())

    # GETting the page must not promote anything.
    _html(logged_in, "/applications/")

    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute(
                "SELECT status FROM applications WHERE user_id = %s",
                (candidate["user_id"],),
            )
            after = sorted(row["status"] for row in cursor.fetchall())

    assert before == after


def test_the_next_step_invents_no_dates_or_employer_responses():
    """No interview date, deadline or employer reply may be fabricated."""
    source = _template("applications.html")
    # The content block only: the script block is behaviour, not rendered copy.
    body = source[
        source.index("{% block app_content %}"): source.index("{% endblock %}", source.index("{% block app_content %}"))
    ]

    # The only date rendered is the real stored timestamp.
    assert "applied_on" in body
    assert "updated_at" in body
    # Nothing that would imply a scheduled event we have no record of.
    for invented in ("interview_date", "response_date", "reply_date",
                     "days_left", "responds by", "interview on"):
        assert invented not in body, invented


def test_app_statuses_and_records_are_preserved(app, candidate, logged_in):
    _make_applications(app, candidate["user_id"], candidate["resume_id"])
    html = _html(logged_in, "/applications/")

    # Every stored status appears, rendered from the value itself.
    for status in ("saved", "applied", "interview", "under_review", "rejected"):
        assert status in html, status

    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) AS n FROM applications WHERE user_id = %s",
                (candidate["user_id"],),
            )
            assert cursor.fetchone()["n"] == 5


# =============================== TRACKING ERRORS ========================


def test_a_refused_write_reports_the_constraint_that_actually_failed():
    """The old handler reported one generic message for every IntegrityError."""
    from routes.applications import _tracking_error_detail

    fk = pymysql.err.IntegrityError(
        1452,
        "CONSTRAINT `applications_ibfk_2` FOREIGN KEY (`job_id`) REFERENCES `jobs`",
    )
    assert "job listing" in _tracking_error_detail(fk)

    resume = pymysql.err.IntegrityError(
        1452, "CONSTRAINT `fk_applications_resume_id` FOREIGN KEY (`resume_id`)"
    )
    assert "resume" in _tracking_error_detail(resume)

    duplicate = pymysql.err.IntegrityError(
        1062, "Duplicate entry '1-2' for key 'applications.uniq_user_job'"
    )
    assert "already recorded" in _tracking_error_detail(duplicate)

    # An unrecognised code states what happened without guessing a cause.
    unknown = _tracking_error_detail(pymysql.err.IntegrityError(9999, "??"))
    assert "job or resume" not in unknown


def test_saving_a_job_that_no_longer_exists_reports_it(app, candidate):
    """No success message when the write cannot happen."""
    client = app.test_client()
    with client.session_transaction() as flask_session:
        flask_session["user_id"] = candidate["user_id"]
        flask_session["user_name"] = "Step1 Candidate"

    response = client.post("/applications/987654321/save")
    assert response.status_code >= 400
    payload = response.get_json()
    assert payload["error"]
    assert "could not be found" in payload["error"].lower()

    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) AS n FROM applications "
                "WHERE user_id = %s AND job_id = %s",
                (candidate["user_id"], 987654321),
            )
            assert cursor.fetchone()["n"] == 0


# =============================== ISOLATION ==============================


def test_the_glass_layer_stays_out_of_the_excluded_pages():
    """Interview / Resume Builder / Cover Letter / Assistant are untouched."""
    shell = _template("app_shell.html")
    assert "app.css" in shell

    # The public surface keeps its own opt-in stylesheet.
    base = _template("base.html")
    assert "surface_styles" in base
    assert "landing.css" not in base, "landing styles belong on the public pages only"

    for page in ("login.html", "register.html", "forgot_password.html", "landing.html"):
        assert "app.css" not in _template(page), page


def test_no_new_frontend_dependency_was_added():
    for name in ("home.html", "opportunities.html", "applications.html",
                 "profile.html", "skill_gap.html", "app_shell.html"):
        source = _template(name)
        # Check what is actually loaded, not the word anywhere: profile.html
        # contains the English word "react" in its resume-writing tips.
        for script in re.findall(r"<script[^>]*src=\"([^\"]+)\"", source):
            assert "react" not in script.lower(), name
            assert "vue" not in script.lower(), name
            assert "tailwind" not in script.lower(), name
            assert "url_for('static'" in script, (name, script)
        for link in re.findall(r"<link[^>]*href=\"([^\"]+)\"", source):
            assert "cdn" not in link.lower(), (name, link)
            assert "url_for(" in link or link.startswith("/static/"), (name, link)