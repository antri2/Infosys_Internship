"""Career Assistant launcher: one fixed bottom-right button, nowhere else.

The original bug was that .chatbot-fab had no CSS at all, so it rendered as an
unstyled third flex child of .app-shell and appeared beside the topbar next to
the user's name. These tests lock in the fixed positioning and the single
global entry point.
"""

import re

import pytest

APP_PAGES = [
    "/home",
    "/profile/",
    "/opportunities/",
    "/skill-gap/",
    "/interview/",
    "/resume-builder/",
    "/cover-letter/",
    "/applications/",
]

# Outside the Basic Multilingual Plane, so an emoji in the launcher is caught.
EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿]")

STYLESHEET = "static/css/style.css"


def _launcher(html: str) -> str:
    match = re.search(r'<a [^>]*class="chatbot-fab".*?</a>', html, re.S)
    assert match, "floating Career Assistant launcher is missing"
    return match.group(0)


@pytest.mark.parametrize("url", APP_PAGES)
def test_launcher_present_on_every_app_page(client, url):
    response = client.get(url)
    assert response.status_code == 200, url
    assert _launcher(response.get_data(as_text=True))


def test_launcher_hidden_on_the_assistant_page_itself(client):
    html = client.get("/assistant/").get_data(as_text=True)
    assert "chatbot-fab" not in html
    # The real chat UI is untouched.
    assert 'id="assistant-question"' in html
    assert 'id="assistant-send"' in html


def test_launcher_appears_exactly_once_per_page(client):
    for url in APP_PAGES:
        count = client.get(url).get_data(as_text=True).count('class="chatbot-fab"')
        assert count == 1, f"{url} rendered {count} launchers"
    # Suppressed on the assistant page so there is no duplicate entry point.
    assert client.get("/assistant/").get_data(as_text=True).count('class="chatbot-fab"') == 0


def test_launcher_never_sits_inside_the_topbar(client):
    for url in APP_PAGES:
        html = client.get(url).get_data(as_text=True)
        topbar = re.search(r'<header class="app-topbar">(.*?)</header>', html, re.S)
        assert topbar, f"{url} has no topbar"
        assert "chatbot-fab" not in topbar.group(1), f"{url} leaked the launcher into the topbar"
        assert 'class="topbar-bell"' in topbar.group(1), url
        assert 'class="topbar-user"' in topbar.group(1), url
        assert 'id="profileDropdown"' in topbar.group(1), url
        assert 'class="topbar-search"' in topbar.group(1), url


def test_launcher_sits_after_the_main_column_not_beside_the_topbar(client):
    """It must not be a flex sibling of the topbar inside .app-shell.

    The unstyled launcher used to sit between .app-topbar and the user name as
    a third child of the shell's flex row. It has to come after the whole
    .app-main-wrap column instead.
    """
    html = client.get("/home").get_data(as_text=True)
    assert 'id="appShell"' in html, "app shell not found"

    main_wrap_at = html.rindex('class="app-main-wrap"')
    main_at = html.rindex('<main class="app-main">')
    launcher_at = html.rindex("chatbot-fab")
    topbar_at = html.rindex('<header class="app-topbar">')

    # DOM order: .app-main-wrap opens, then its topbar, then <main>, then the
    # launcher after </main>. The topbar must be fully closed before the
    # launcher appears, which is what keeps it out of the navigation row.
    assert main_wrap_at < topbar_at < main_at < launcher_at, (
        "launcher must come after the main column, not beside the topbar"
    )
    assert launcher_at > html.index("</main>")
    assert launcher_at > html.index("</header>")


def test_launcher_points_at_the_existing_assistant_route(client):
    launcher = _launcher(client.get("/home").get_data(as_text=True))
    assert 'href="/assistant/"' in launcher


def test_launcher_has_an_accessible_name_and_a_tooltip(client):
    launcher = _launcher(client.get("/home").get_data(as_text=True))
    assert 'aria-label="Open Career Assistant"' in launcher
    assert 'data-tooltip="Career Assistant"' in launcher


def test_launcher_uses_the_project_svg_icon_not_an_emoji(client):
    launcher = _launcher(client.get("/home").get_data(as_text=True))
    assert "<svg" in launcher
    # No text node content and no emoji anywhere inside the button.
    assert not EMOJI.search(launcher)
    body = re.sub(r"<[^>]+>", "", launcher)
    assert body.strip() == "", f"launcher carries stray text: {body!r}"


def test_sidebar_navigation_is_unchanged(client):
    """The sidebar link is existing navigation and must survive."""
    html = client.get("/home").get_data(as_text=True)
    sidebar = re.search(r'<nav class="sidebar-nav">(.*?)</nav>', html, re.S)
    assert sidebar, "sidebar nav missing"
    assert 'href="/assistant/"' in sidebar.group(1)
    for label in ("Home", "My Profile", "Opportunities", "Skill Gap", "Interview Preparation"):
        assert label in sidebar.group(1), label


def test_launcher_requires_login(client, app):
    anonymous = app.test_client()
    for url in APP_PAGES:
        response = anonymous.get(url)
        assert response.status_code == 302, url
        assert "chatbot-fab" not in response.get_data(as_text=True), url


# ------------------------------------------------------------------- styles ---


def _fab_rule(css: str, selector: str) -> str:
    match = re.search(rf"(?m)^{re.escape(selector)}\s*\{{([^}}]*)\}}", css)
    assert match, f"CSS rule for {selector} is missing"
    return match.group(1)


def test_stylesheet_pins_the_launcher_to_the_viewport_bottom_right():
    css = open(STYLESHEET, encoding="utf-8").read()
    rule = _fab_rule(css, ".chatbot-fab")
    assert "position: fixed" in rule
    assert "right: 24px" in rule
    assert "bottom: 24px" in rule
    assert "border-radius: 50%" in rule
    assert "z-index" in rule


def test_stylesheet_uses_brand_colour_and_a_shadow():
    css = open(STYLESHEET, encoding="utf-8").read()
    rule = _fab_rule(css, ".chatbot-fab")
    assert "var(--primary)" in rule
    assert "box-shadow" in rule
    assert "transition" in rule

    hover = _fab_rule(css, ".chatbot-fab:hover")
    assert "var(--primary-dark)" in hover
    assert "scale" in hover
    assert "brightness" in hover


def test_stylesheet_defines_the_hover_tooltip():
    css = open(STYLESHEET, encoding="utf-8").read()
    tooltip = _fab_rule(css, ".chatbot-fab::after")
    assert "attr(data-tooltip)" in tooltip
    assert "position: absolute" in tooltip
    assert "opacity: 0" in tooltip
    # Revealed on hover and keyboard focus.
    assert re.search(r"\.chatbot-fab:hover::after[^{]*\{[^}]*opacity: 1", css)
    assert re.search(r"\.chatbot-fab:focus-visible::after[^{]*\{[^}]*opacity: 1", css)


def test_stylesheet_shrinks_the_launcher_on_small_screens():
    css = open(STYLESHEET, encoding="utf-8").read()
    block = re.search(r"@media \(max-width: 800px\)\s*\{(.*?)\n\}", css, re.S)
    assert block, "no small-screen breakpoint for the launcher"
    mobile = block.group(1)
    assert ".chatbot-fab" in mobile
    assert "right: 16px" in mobile
    assert "bottom: 16px" in mobile
    assert re.search(r"\.chatbot-fab\s*\{[^}]*width: 48px", mobile)
    # A smaller button than the 54px desktop default.
    assert "width: 54px" in _fab_rule(css, ".chatbot-fab")
