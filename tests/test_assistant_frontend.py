"""Frontend regression checks for Career Assistant response rendering."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = (ROOT / "templates" / "assistant.html").read_text(encoding="utf-8")
RENDERER = (ROOT / "static" / "js" / "assistant_rendering.js").read_text(encoding="utf-8")


def test_assistant_uses_external_safe_response_renderer():
    assert "js/assistant_rendering.js" in TEMPLATE
    assert "normalizeResponse" in TEMPLATE
    assert "renderMarkdown" in TEMPLATE
    assert "addMessage('assistant', data);" in TEMPLATE
    assert "JSON.stringify(data.answer" not in TEMPLATE
    assert "innerHTML" not in RENDERER


def test_renderer_supports_wrapped_json_and_common_markdown():
    for required in (
        "JSON.parse(text)",
        "['answer', 'response', 'content', 'message', 'text']",
        "createElement('strong')",
        "var nextType = ordered ? 'ol' : 'ul';",
        "createElement('h' + level)",
        "replaceChildren(fragment)",
    ):
        assert required in RENDERER


def test_template_preserves_plain_and_wrapped_answers_separately():
    assert "bubble.textContent = String(fallbackText" in TEMPLATE
    assert "data-markdown-source" in TEMPLATE
    assert "bubble.dataset.markdownSource" in TEMPLATE
