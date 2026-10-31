"""Pin the Skill Fit badge contrast so it cannot silently regress.

The badge ships from style.css at 3.00 / 2.86 / 3.95 : 1, which is under the
4.5:1 AA threshold for its 12.5px bold text. app.css overrides the three
foregrounds with the same-family 700 step; this asserts the *computed* result of
that override against the real token values, so it fails if either the override
or the underlying palette changes.
"""

import re


def _srgb_luminance(hex_colour: str) -> float:
    value = hex_colour.lstrip("#")
    channels = [int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)]

    def linear(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (linear(c) for c in channels)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _ratio(foreground: str, background: str) -> float:
    first, second = _srgb_luminance(foreground), _srgb_luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def _palette() -> dict:
    """Read the token values from style.css rather than hardcoding them."""
    css = open("static/css/style.css", encoding="utf-8").read()

    def token(name: str) -> str:
        found = re.search(rf"--{re.escape(name)}:\s*(#[0-9A-Fa-f]{{6}})\s*;", css)
        assert found, f"--{name} not found in style.css"
        return found.group(1)

    return {name: token(name) for name in
            ("success", "success-bg", "warning", "warning-bg", "danger", "danger-bg")}


def _app_css_rule(selector: str) -> str:
    css = open("static/css/app.css", encoding="utf-8").read()
    found = re.search(rf"{re.escape(selector)}\s*\{{([^}}]*)\}}", css)
    assert found, f"{selector} not declared in app.css"
    return found.group(1)


def test_the_original_palette_would_fail_so_the_override_is_needed():
    """Documents why the override exists; fails if style.css is ever fixed."""
    palette = _palette()
    original = [
        _ratio(palette["success"], palette["success-bg"]),
        _ratio(palette["warning"], palette["warning-bg"]),
        _ratio(palette["danger"], palette["danger-bg"]),
    ]
    # At least one variant is below AA without the override.
    assert min(original) < 4.5, original


def test_every_badge_variant_meets_aa():
    """12.5px bold is normal text, so the threshold is 4.5:1."""
    palette = _palette()

    variants = [
        (".match-badge", palette["success-bg"], 4.5),
        (".match-badge.mid", palette["warning-bg"], 4.5),
        (".match-badge.low", palette["danger-bg"], 4.5),
    ]

    for selector, background, minimum in variants:
        rule = _app_css_rule(selector)
        colour = re.search(r"color:\s*(#[0-9A-Fa-f]{6})", rule)
        assert colour, f"{selector} does not set a hex colour"

        ratio = _ratio(colour.group(1), background)
        assert ratio >= minimum, (
            f"{selector}: {colour.group(1)} on {background} is {ratio:.2f}:1, "
            f"needs {minimum}:1"
        )


def test_the_badge_backgrounds_are_untouched():
    """Only the foreground may change; the tint is part of the design."""
    css = open("static/css/app.css", encoding="utf-8").read()
    badge_block = css[css.index("Skill Fit badge contrast"):]
    assert "background" not in badge_block, badge_block
    assert "background-color" not in badge_block


def test_the_override_does_not_leak_to_the_home_dashboard():
    """The Home Dashboard renders no .match-badge, so its own buttons are
    unaffected -- asserted here because the override is global, not scoped."""
    assert "match-badge" not in open("templates/home.html", encoding="utf-8").read()