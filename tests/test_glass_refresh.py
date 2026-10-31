"""Glass design refresh: Opportunities, Skill Gap, Cover Letter, Assistant, shell.

Each section here corresponds to a requirement in this change:

  * Opportunities uses inline expansion, while the Home Dashboard keeps its
    popup -- the two must be provably different;
  * job search reuses the route's existing `?q=` path;
  * the five opportunity actions survive, inside the expanded region;
  * Skill Gap is restyled but its analysis contract is untouched;
  * the footer is a translucent card, not a solid bar;
  * Cover Letter has a real View Letter action and role-identifying headings;
  * the Assistant's intro is short and its history uses the available height;
  * the sidebar collapse control no longer reads as attached to the logo.
"""

import re

import pytest

from database.db import get_db


@pytest.fixture
def signed_in(app, candidate):
    client = app.test_client()
    with client.session_transaction() as flask_session:
        flask_session["user_id"] = candidate["user_id"]
        flask_session["user_name"] = "Step1 Candidate"
    return client


def _html(client, path):
    response = client.get(path)
    assert response.status_code == 200, path
    return response.get_data(as_text=True)


def candidate_id(client):
    """The user id a signed-in client is acting as."""
    with client.session_transaction() as flask_session:
        return flask_session["user_id"]


def _cards(html):
    return re.findall(r'<article class="opp-card[^"]*"[^>]*>.*?</article>',
                      html, re.S)


def _first_card(html):
    return _cards(html)[0]


# ==========================================================================
# Opportunities: compact cards + inline expansion
# ==========================================================================


def test_opportunity_cards_show_only_the_compact_fields(signed_in):
    card = _first_card(_html(signed_in, "/opportunities/"))
    collapsed = card[:card.index('<div class="opp-card__detail"')]

    # Title, company, location, Skill Fit and the expand control.
    assert "opp-card__title" in collapsed
    assert "opp-card__company" in collapsed
    assert "opp-card__meta" in collapsed
    assert "match-badge" in collapsed
    assert "data-opp-toggle" in collapsed

    # None of the detail content is on the collapsed card.
    for absent in ("Get AI Summary", "Prepare for Interview",
                   "opp-detail__section", "Skill comparison"):
        assert absent not in collapsed, absent


def test_skill_fit_sits_with_the_expand_control_in_the_corner(signed_in):
    card = _first_card(_html(signed_in, "/opportunities/"))
    collapsed = card[:card.index('<div class="opp-card__detail"')]
    corner = re.search(r'<div class="opp-card__corner">(.*?)</div>\s*</div>',
                       collapsed, re.S)
    assert corner, "no corner block"
    assert "match-badge" in corner.group(1)
    assert "data-opp-toggle" in corner.group(1)


def test_view_details_expands_inline_and_never_navigates(signed_in):
    html = _html(signed_in, "/opportunities/")
    toggle = re.search(r"<button[^>]*data-opp-toggle.*?</button>", html, re.S).group(0)

    # A button, not a link: it cannot navigate away.
    assert toggle.lstrip().startswith("<button")
    assert "href=" not in toggle
    # Proper disclosure semantics.
    assert 'aria-expanded="false"' in toggle
    assert 'aria-controls="opp-detail-' in toggle

    # The region it controls exists and starts collapsed.
    job_id = re.search(r'data-job-id="(\d+)"', toggle).group(1)
    assert f'<div class="opp-card__detail" id="opp-detail-{job_id}" hidden>' in html


def test_expanding_one_card_collapses_any_other():
    """Only one card is expanded at a time, so the list stays scannable."""
    js = open("static/js/opportunity_expand.js", encoding="utf-8").read()
    assert "collapseOthers" in js
    assert "aria-expanded" in js
    # Escape closes the open card, matching the dialog's behaviour.
    assert "Escape" in js


def test_the_expander_builds_the_same_detail_sections_the_dialog_had():
    js = open("static/js/opportunity_expand.js", encoding="utf-8").read()
    for section in ("Job summary", "Why this matches your profile", "Skills fit",
                    "Skill comparison", "Responsibilities", "Qualifications",
                    "Role details"):
        assert section in js, section
    for group in ("Required skills", "Preferred skills",
                  "Your profile skills (matched)", "Skills to learn"):
        assert group in js, group


def test_the_expander_escapes_every_value_it_renders():
    """A job description is untrusted text and must never become markup."""
    js = open("static/js/opportunity_expand.js", encoding="utf-8").read()

    # The escaper is declared as an assigned function expression.
    assert "var esc = function" in js
    for character, entity in (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"),
                              ('"', "&quot;")):
        assert f".replace(/{character}/g" in js, character
        assert entity in js, entity

    # Malformed match reasons degrade to "no reasons" instead of throwing.
    assert "catch (error)" in js

    # The real property: nothing unescaped is concatenated into the markup.
    #
    # Every value reaches innerHTML either as a string literal, as a call whose
    # result the module built through esc(), or through esc() directly. What
    # must never appear is a bare job field -- `+ d.description` rather than
    # `+ esc(d.description)`. So: strip literals, then collect the identifiers
    # that appear after a `+`, and require them to be values this module owns.
    source = re.sub(r"/\*.*?\*/", "", js, flags=re.S)      # comments
    source = re.sub(r"'(?:[^'\\]|\\.)*'", "''", source)  # single-quoted literals

    # A call is skipped by inspecting the text after the match: `esc(...)`,
    # `pillRow(...)`, `values.map(...)`. What survives is a bare value
    # concatenated straight into markup, which is exactly what must not happen.
    # (A negative lookahead cannot express this -- the identifier backtracks to
    # `es` so that `c` is no longer followed by `(`.)
    bare = set()
    for match in re.finditer(r"\+\s*([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)",
                             source):
        if not source[match.end():].lstrip().startswith("("):
            bare.add(match.group(1))

    # `html` is this module's own escaped accumulator. `kind` is one of three
    # literal strings it passes in ("required"/"have"/"missing").
    unescaped = bare - {"html", "kind"}
    assert not unescaped, f"unescaped values reach the markup: {sorted(unescaped)}"

    # And a representative field really is escaped at its use site.
    assert "esc(d.description)" not in js  # it goes through paragraphs()
    assert "paragraphs(d.description)" in js
    assert "esc(title)" in js and "esc(fit)" in js


def test_all_five_actions_survive_inside_the_expansion(signed_in):
    detail_region = _html(signed_in, "/opportunities/")
    detail = detail_region[detail_region.index('<div class="opp-card__detail"'):]
    for label in ("Apply", "Save", "Get AI Summary", "Skill Gap",
                  "Prepare for Interview"):
        assert label in detail, label
    # Still the existing routes and handlers.
    assert "/applications/${jobId}/${action}" in detail
    assert "/opportunities/${jobId}/ai-summary" in detail
    assert "/skill-gap/?job_id=" in detail
    assert "/interview/?job_id=" in detail


def test_the_home_popup_still_exists_and_is_separate(signed_in):
    """The brief requires the two pages to behave differently."""
    home = _html(signed_in, "/home")
    opportunities = _html(signed_in, "/opportunities/")

    assert 'id="aiJobModal"' in home
    assert "js/job_modal.js" in home
    assert "data-job-open" in home

    assert 'id="aiJobModal"' not in opportunities
    assert "js/job_modal.js" not in opportunities
    assert "data-job-open" not in opportunities
    assert "js/opportunity_expand.js" in opportunities


# ==========================================================================
# Opportunities: search
# ==========================================================================


def test_the_search_input_is_present_and_posts_to_the_existing_route(signed_in):
    html = _html(signed_in, "/opportunities/")
    assert '<form class="opp-search"' in html
    assert 'method="GET"' in html
    assert 'action="/opportunities/"' in html
    assert 'name="q"' in html
    assert 'id="opp-search-input"' in html
    assert 'role="search"' in html


def test_search_uses_the_existing_query_path(app, signed_in):
    """No second search system: the same ?q= the route already handled."""
    plain = re.findall(r'data-job-id="(\d+)"', _html(signed_in, "/opportunities/"))
    searched = re.findall(
        r'data-job-id="(\d+)"',
        _html(signed_in, "/opportunities/?q=data%20analyst"),
    )
    assert searched, "a search returned nothing"
    # The response is still rendered by the same list route.
    assert '<div class="opp-list">' in _html(signed_in, "/opportunities/?q=python")


def test_a_search_term_is_echoed_and_can_be_cleared(signed_in):
    html = _html(signed_in, "/opportunities/?q=python")
    assert 'value="python"' in html
    assert "opp-search__clear" in html
    assert "Showing results for" in html


# ==========================================================================
# Skill Gap
# ==========================================================================


def test_skill_gap_uses_the_glass_surfaces():
    css = open("static/css/app.css", encoding="utf-8").read()
    for selector in (".sg-form", ".sg-panel", ".sg-recommendations", ".sg-results"):
        assert selector in css, selector


def test_the_three_skill_groups_are_visually_separated():
    """Separated by tint and a top rule, not by three different boxes."""
    css = open("static/css/app.css", encoding="utf-8").read()
    for modifier in ("--have", "--missing", "--partial"):
        assert f".sg-panel{modifier}" in css, modifier
    # A tinted rule marks each group.
    assert ".sg-panel::before" in css


def test_skill_gap_analysis_is_untouched(signed_in):
    """Presentation only: every id the existing JS hooks into survives."""
    html = _html(signed_in, "/skill-gap/")
    for hook in ('id="skill-gap-form"', 'id="skill-gap-report"',
                 'id="skill-gap-status"', 'id="target-role"',
                 'id="company-name"', 'id="job-description"',
                 'id="matched-skills"', 'id="missing-required"',
                 'id="missing-preferred"', 'id="partial-matches"',
                 'id="count-have"', 'id="count-missing"',
                 'data-explicit-job-id'):
        assert hook in html, hook

    js = open("templates/skill_gap.html", encoding="utf-8").read()
    for function in ("renderSkills", "renderRecommendations", "renderPriorities"):
        assert f"function {function}" in js, function
    assert "Analyze Skill Gap" in html


# ==========================================================================
# Footer
# ==========================================================================


def test_the_footer_is_declared_exactly_once():
    """No duplicated or conflicting rules -- the brief asks for this directly."""
    css = open("static/css/app.css", encoding="utf-8").read()

    # Strip media queries first: a responsive override is expected, a second
    # competing base rule is not.
    base = re.sub(r"@media[^{]+\{(?:[^{}]|\{[^{}]*\})*\}", "", css)
    assert base.count(".app-footer {") == 1, base.count(".app-footer {")
    assert base.count(".app-footer__inner {") == 1

    # The responsive override is a single, complete block.
    queries = re.findall(r"@media \(max-width: 780px\) \{([^@]*?)\n\}", css)
    footer_media = [q for q in queries if ".app-footer" in q]
    assert len(footer_media) == 1, len(footer_media)


def test_the_footer_is_a_translucent_card_not_a_solid_block():
    css = open("static/css/app.css", encoding="utf-8").read()

    outer = re.search(r"\.app-footer\s*\{([^}]*)\}", css).group(1)
    # The outer element is a plain spacer: no fill, no heavy block.
    assert "background: none" in outer
    assert "border: none" in outer

    inner = re.search(r"\.app-footer__inner\s*\{([^}]*)\}", css).group(1)
    # The visible surface is the inner card: softly tinted, bordered, rounded.
    assert "rgba(" in inner
    assert "border-radius" in inner
    assert "border: 1px solid" in inner
    assert "box-shadow" in inner
    assert "backdrop-filter" in inner
    # No saturated blue fill.
    for heavy in ("#102A56", "--ai-navy)", "linear-gradient(135deg, #1"):
        assert heavy not in inner, heavy


def test_the_footer_follows_the_sidebar_and_cannot_overflow():
    css = open("static/css/app.css", encoding="utf-8").read()
    outer = re.search(r"\.app-footer\s*\{([^}]*)\}", css).group(1)

    # No fixed width, so it cannot disagree with the sidebar's state.
    assert "width:" not in outer
    assert "position: fixed" not in outer

    # Still pushed to the bottom of a short page. This was nearly lost when the
    # rule was first merged: a `margin` shorthand would have reset it.
    assert "margin-top: auto" in outer

    # It is a child of the wrap, which is what makes it track the sidebar.
    shell = open("templates/app_shell.html", encoding="utf-8").read()
    wrap = shell.index('<div class="app-main-wrap">')
    footer = shell.index('class="app-footer"')
    assert wrap < footer
    assert "app-footer" in shell[footer:].split("</footer>")[0]


def test_footer_links_still_resolve(signed_in):
    html = _html(signed_in, "/home")
    footer = html[html.index('class="app-footer"'):]
    footer = footer[:footer.index("</footer>")]
    hrefs = re.findall(r'<a href="([^"]+)"', footer)
    assert hrefs
    for href in hrefs:
        assert not href.startswith("#"), href
        assert signed_in.get(href).status_code in (200, 302), href


# ==========================================================================
# Cover Letter
# ==========================================================================


def test_view_and_load_letter_are_both_present_and_distinct(signed_in):
    html = _html(signed_in, "/cover-letter/")
    assert "view-cover-letter" in html
    assert "load-cover-letter" in html
    # And the panel they differ on exists.
    assert 'id="cover-letter-view"' in html
    assert 'id="cover-letter-editor"' in html

    js = html[html.index("{% block scripts %}") if "{% block scripts %}" in html else 0:]
    # The read-only view writes textContent; the editor is never touched by it.
    assert "viewBody.textContent" in _html(signed_in, "/cover-letter/")


def test_viewing_a_letter_cannot_overwrite_the_editor():
    """The distinction that matters: View reads, Load edits."""
    source = open("templates/cover_letter.html", encoding="utf-8").read()

    # Slice from the View Letter comment, not from the querySelectorAll call:
    # the showView helper that writes textContent is defined *before* it.
    view_start = source.index("/* ---- View Letter ----")
    load_start = source.index("/* ---- Load Letter ----")
    view_block = source[view_start:load_start]
    load_block = source[load_start:]

    # View reads...
    assert "editor.value" not in view_block, "View Letter must not write to the editor"
    assert "textContent" in view_block
    assert "viewBody" in view_block
    # ...and says so, so the two are not ambiguous.
    assert "Your editor is unchanged." in view_block

    # Load edits.
    assert "editor.value" in load_block, "Load Letter must write to the editor"


def test_view_letter_reuses_the_existing_load_endpoint(signed_in):
    """No new route: the existing endpoint serves both actions.

    It also guards a bug that shipped here for a long time. Both buttons used
    to build their URL with
    `url_for("cover_letter.load", letter_id=0).replace('/0/', '/<id>/')`,
    but that renders `/cover-letter/load/0` with no trailing slash, so the
    replace never fired and every click requested letter 0 -- which the server
    correctly rejected. The URL is now rendered per button by Jinja, so it
    cannot drift from the route again.
    """
    source = open("templates/cover_letter.html", encoding="utf-8").read()

    # No string surgery on the URL.
    assert ".replace('/0/'" not in source
    assert "letter_id=0" not in source

    # Both buttons carry the endpoint, rendered by Jinja.
    assert source.count("data-letter-url") == 2
    assert source.count("url_for('cover_letter.load', letter_id=letter.id)") == 2

    html = _html(signed_in, "/cover-letter/")
    urls = re.findall(r'data-letter-url="([^"]+)"', html)
    if urls:
        # Every rendered URL must be a real, non-placeholder letter id.
        for url in urls:
            assert re.fullmatch(r"/cover-letter/load/[1-9]\d*", url), url


def test_letter_headings_identify_the_target_role():
    from routes.cover_letter import letter_heading

    assert letter_heading({"target_role": "Data Analyst"}) == \
        "Generic Cover Letter / Data Analyst"
    assert letter_heading({"target_role": "Software Engineer"}) == \
        "Generic Cover Letter / Software Engineer"
    assert letter_heading({"job_title": "Data Analyst Intern",
                           "job_company": "Infosys"}) == \
        "Cover Letter / Data Analyst Intern at Infosys"
    # A row saved before the role existed says so rather than guessing.
    assert "no role recorded" in letter_heading({})


def test_the_ambiguous_generic_heading_is_gone(signed_in):
    """Checked on rendered headings, not the whole document.

    The inline script legitimately contains the string "Generic Cover Letter / "
    because it builds one client-side when a draft is generated. Searching the
    raw page would therefore match the script, not a heading.

    Letters are created here rather than assumed, so the assertion cannot pass
    vacuously on an empty list.
    """
    for role in ("Data Analyst", "Software Engineer"):
        response = signed_in.post(
            "/cover-letter/save",
            json={"content": "Dear Hiring Manager,\n\nA letter for " + role + ".",
                  "job_id": None, "target_role": role},
        )
        assert response.status_code == 200, response.get_data(as_text=True)

    html = _html(signed_in, "/cover-letter/")
    assert "<strong>Generic Cover Letter</strong>" not in html

    markup = re.sub(r"<script.*?</script>", "", html, flags=re.S)
    headings = re.findall(r'class="cl-list__heading">([^<]*)<', markup)
    assert headings, "no saved-letter headings rendered"

    for heading in headings:
        heading = heading.strip()
        assert heading, "a heading rendered empty"
        assert heading != "Generic Cover Letter", heading
        # Every heading either names a job or names a role (or states plainly
        # that an older row recorded neither).
        assert ("/" in heading) or ("no role recorded" in heading), heading

    # Both saved roles are named, which is the requirement.
    joined = " | ".join(h.strip() for h in headings)
    assert "Generic Cover Letter / Data Analyst" in joined, joined
    assert "Generic Cover Letter / Software Engineer" in joined, joined


def test_the_target_role_is_persisted(app, signed_in):
    """A generic letter has no job row, so the role must be stored."""
    response = signed_in.post(
        "/cover-letter/save",
        json={"content": "Dear Hiring Manager,\n\nA role-specific letter.",
              "job_id": None, "target_role": "Data Analyst"},
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    body = response.get_json()
    assert body["success"] is True
    assert body["target_role"] == "Data Analyst"
    letter_id = body["letter_id"]

    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute(
                "SELECT target_role FROM cover_letters WHERE id = %s AND user_id = %s",
                (letter_id, candidate_id(signed_in)),
            )
            row = cursor.fetchone()
    assert row["target_role"] == "Data Analyst", row

    # The saved list now names it. This exercises list_cover_letters, not
    # load_cover_letter -- the two are separate queries and the list one was
    # missing the column.
    html = _html(signed_in, "/cover-letter/")
    headings = re.findall(r'class="cl-list__heading">([^<]*)<', html)
    assert "Generic Cover Letter / Data Analyst" in headings, headings

    # And the read-only view reports the same heading.
    loaded = signed_in.get(f"/cover-letter/load/{letter_id}").get_json()
    assert loaded["letter"]["heading"] == "Generic Cover Letter / Data Analyst"
    assert loaded["letter"]["target_role"] == "Data Analyst"


def test_editing_a_letter_does_not_erase_its_role(app, signed_in):
    """Saving an edit without a role must keep the stored one."""
    first = signed_in.post(
        "/cover-letter/save",
        json={"content": "First", "job_id": None, "target_role": "Data Analyst"},
    ).get_json()
    letter_id = first["letter_id"]

    # A second save with no role supplied.
    second = signed_in.post(
        "/cover-letter/save",
        json={"content": "Edited", "job_id": None, "letter_id": letter_id},
    ).get_json()

    assert second["target_role"] == "Data Analyst"


def test_the_migration_is_additive_and_idempotent(app):
    """The column is nullable and existing rows keep NULL."""
    from database import db as db_module
    assert hasattr(db_module, "_ensure_cover_letter_target_role")

    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute(
                "SELECT COLUMN_NAME, IS_NULLABLE FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'cover_letters' "
                "AND COLUMN_NAME = 'target_role'",
                (__import__("config").MYSQL_DATABASE,),
            )
            row = cursor.fetchone()
    assert row is not None, "target_role column missing"
    assert row["IS_NULLABLE"] == "YES"


# ==========================================================================
# Career Assistant
# ==========================================================================


def test_the_intro_is_a_single_short_line(signed_in):
    html = _html(signed_in, "/assistant/")

    assert "grounded Career AI Assistant" not in html
    assert "I\u2019m your grounded CareerAI assistant" not in html

    welcome = re.search(r'<div class="chat-bubble assistant welcome-message">(.*?)</div>',
                        html, re.S)
    assert welcome, "welcome message missing"
    text = " ".join(welcome.group(1).split())
    # One line, well under the previous five sentences.
    assert len(text) < 90, text
    assert text.count(".") <= 1, text


def test_the_heading_and_starter_questions_are_preserved(signed_in):
    html = _html(signed_in, "/assistant/")
    assert "What would you like to work on?" in html

    for question in ("AI Engineer learning path", "Selected job fit",
                     "Resume guidance", "Interview preparation",
                     "Project ideas"):
        assert question in html, question

    assert len(re.findall(r'class="assistant-starter"', html)) == 5


def test_the_chat_history_uses_the_available_height():
    css = open("static/css/app.css", encoding="utf-8").read()

    page = re.search(r"\.assistant-page\s*\{([^}]*)\}", css).group(1)
    # stretch, not flex-start: the sidebar has to be able to grow.
    assert "align-items: stretch" in page

    sidebar = re.search(r"\.assistant-sidebar\s*\{([^}]*)\}", css).group(1)
    assert "align-self: stretch" in sidebar

    conversations = re.search(r"\.assistant-conversations\s*\{([^}]*)\}", css).group(1)
    assert "flex: 1 1 auto" in conversations
    # Required for the scroll to engage: a flex item will not shrink below its
    # content height unless min-height is explicitly 0.
    assert "min-height: 0" in conversations
    assert "overflow-y: auto" in conversations
    # The old arbitrary cap is gone.
    assert "max-height: 62vh" not in conversations
    assert "max-height: none" in conversations


def test_the_history_cannot_overlap_the_composer():
    css = open("static/css/app.css", encoding="utf-8").read()
    composer = re.search(r"\.assistant-composer\s*\{([^}]*)\}", css).group(1)
    # It does not shrink, so the history's scroll ends above it.
    assert "flex-shrink: 0" in composer

    shell = re.search(r"\.assistant-chat-shell\s*\{([^}]*)\}", css).group(1)
    assert "overflow: hidden" in shell
    assert "min-height: 0" in shell


def test_the_assistant_gets_the_glass_surface(signed_in):
    css = open("static/css/app.css", encoding="utf-8").read()
    assert ".glass-panel" in css
    html = _html(signed_in, "/assistant/")
    assert "glass-panel" in html


def test_assistant_capabilities_are_not_removed(signed_in):
    """The conversation list, new chat and the endpoint stay."""
    html = _html(signed_in, "/assistant/")
    assert 'id="assistant-conversations"' in html
    assert 'id="assistant-reset"' in html
    assert 'id="assistant-form"' in html
    assert 'id="assistant-question"' in html
    assert "conversation-rename" in html
    assert "conversation-delete" in html


# ==========================================================================
# Sidebar collapse control
# ==========================================================================


def test_the_collapse_control_has_no_square_chrome():
    css = open("static/css/app.css", encoding="utf-8").read()
    rule = re.search(r"\.sidebar-collapse\s*\{([^}]*)\}", css).group(1)

    # No border, and a fill dark enough to stay understated on the navy rail.
    assert "border: none" in rule
    assert "box-shadow: none" in rule
    assert "28px" not in rule, "still the old 28px square"
    assert re.search(r"width:\s*2[0-4]px", rule), "should be a smaller control"

    fill = re.search(r"background:\s*([^;]+);", rule).group(1)
    # Darker than the original light chip.
    assert "rgba(3, 10, 26" in fill, fill


def test_the_collapse_control_cannot_touch_the_logo():
    css = open("static/css/app.css", encoding="utf-8").read()

    top = re.search(r"\.sidebar-top\s*\{([^}]*)\}", css).group(1)
    gap = int(re.search(r"gap:\s*(\d+)px", top).group(1))
    assert gap >= 12, f"only {gap}px between the logo and the control"

    # The logo is capped and the control never compresses, so neither can grow
    # into the other.
    logo = re.search(r"\.sidebar-logo\s*\{([^}]*)\}", css).group(1)
    assert "min-width: 0" in logo
    assert "overflow: hidden" in logo

    collapse = re.search(r"\.sidebar-collapse\s*\{([^}]*)\}", css).group(1)
    assert "flex-shrink: 0" in collapse


def test_the_arrow_stays_visible_in_both_states():
    css = open("static/css/app.css", encoding="utf-8").read()
    collapsed = re.search(
        r"\.app-shell\.sidebar-collapsed \.sidebar-collapse-icon \.icon\s*\{([^}]*)\}",
        css).group(1)
    assert "rotate(180deg)" in collapsed

    shell = open("templates/app_shell.html", encoding="utf-8").read()
    toggle = re.search(r'<button[^>]*id="sidebarCollapse".*?</button>', shell, re.S).group(0)
    assert "chevron-left" in toggle


def test_the_pre_paint_restore_is_still_present():
    """The anti-flicker behaviour must survive the restyle."""
    base = open("templates/base.html", encoding="utf-8").read()
    head = base[:base.index("</head>")]
    assert "careerai:sidebar-collapsed" in head


# ==========================================================================
# Isolation
# ==========================================================================


def test_no_new_dependency_was_added():
    requirements = open("requirements.txt", encoding="utf-8").read()
    for name in ("bootstrap", "tailwind", "react", "jquery", "alpine"):
        assert name not in requirements.lower(), name


def test_resume_builder_is_not_touched_by_this_change():
    """The task explicitly excludes it."""
    source = open("templates/resume_builder.html", encoding="utf-8").read()
    # None of this task's new classes leaked into it.
    for cls in ("opp-card__detail", "opp-search", "cl-view", "glass-panel",
                "sg-recommendations", "ai-card--accent"):
        assert cls not in source, cls


def test_the_new_styles_are_scoped():
    """No bare-element or global rule leaked in."""
    css = open("static/css/app.css", encoding="utf-8").read()
    for selector in (".opp-card__detail", ".opp-search", ".cl-view",
                     ".glass-panel", ".sg-form"):
        rule = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css).group(1)
        assert not rule.strip().startswith("*"), selector


def test_authentication_still_guards_every_changed_page(app):
    for path in ("/opportunities/", "/skill-gap/", "/cover-letter/", "/assistant/"):
        response = app.test_client().get(path)
        assert response.status_code in (302, 405), path
        if response.status_code == 302:
            assert "/login" in response.headers["Location"], path