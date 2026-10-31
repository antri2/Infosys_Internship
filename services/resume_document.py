"""Canonical resume document model, shared by the preview, TXT and PDF.

Why one module owns all three renderings
----------------------------------------
The requirement is that the PDF and TXT contain the *edited* resume, and that
what the user sees in the preview is what they download. The only reliable way
to guarantee that is to derive all three from a single structured value rather
than maintaining three parallel formats.

So a resume here is always this shape::

    {
      "name": "...",
      "contact": ["email", "phone", ...],
      "headline": "Data Analyst",
      "sections": [
          {"key": "professional_summary", "title": "Professional Summary",
           "kind": "text", "text": "..."},
          {"key": "skills", "title": "Technical Skills", "kind": "skill_groups",
           "groups": [{"label": "Languages", "skills": ["Python"]}]},
          {"key": "experience", "title": "Experience", "kind": "entries",
           "entries": [{"title", "organization", "start_date", "end_date",
                        "bullets": [...]}]},
          ...
      ],
    }

`sections` is an ordered list, which is what makes "reorder or remove a
section" possible without any extra bookkeeping. `validate_sections` is the
only way user input enters that structure, so every value is length-bounded and
string-typed before it can reach a renderer.

Nothing in this module invents content: `sections_from_tailored` only copies
facts that the tailored dict already carries, and a field that is absent simply
does not produce a line.
"""

from __future__ import annotations

import html as _html
import io
import re

# Section kinds the renderer knows how to draw. An unknown kind is dropped
# rather than rendered as raw text.
KINDS = ("text", "skill_groups", "entries", "list")

# Bounds. A resume is a page or two; anything beyond this is a paste accident
# and is truncated rather than allowed to blow up the renderer.
MAX_SECTIONS = 12
MAX_SECTION_TITLE = 80
MAX_TEXT = 6000
MAX_ITEMS = 40
MAX_BULLETS = 20
MAX_BULLET = 600
MAX_SKILLS = 80
MAX_SKILL = 80
MAX_HEADLINE = 120
MAX_CONTACT_ITEMS = 6
MAX_CONTACT_ITEM = 160

DEFAULT_SECTION_TITLES = {
    "professional_summary": "Professional Summary",
    "skills": "Technical Skills",
    "experience": "Experience",
    "projects": "Projects",
    "education": "Education",
    "certifications": "Certifications",
}


# --------------------------------------------------------------------------
# Normalisation
# --------------------------------------------------------------------------

def _text(value, limit: int) -> str:
    """Collapse whitespace and clamp length; never returns a non-string."""
    if value is None:
        return ""
    cleaned = " ".join(str(value).split()).strip()
    if len(cleaned) > limit:
        cleaned = cleaned[:limit].rstrip()
    return cleaned


def _lines(value, limit: int, per_line: int) -> list[str]:
    """Normalise a multi-line value into clean, non-empty lines.

    Accepts a textarea string (split on newlines) or an already-list-shaped
    value such as a list of bullets. Handling both here is what keeps the
    generated path (lists) and the edited path (textareas) interchangeable.
    """
    if value is None:
        return []
    if isinstance(value, str):
        raw_lines = value.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    elif isinstance(value, (list, tuple)):
        raw_lines = [str(item) for item in value]
    else:
        raw_lines = [str(value)]

    out = []
    for raw in raw_lines:
        line = _text(raw, per_line)
        if line:
            out.append(line)
        if len(out) >= limit:
            break
    return out


def _safe_int(value) -> int | None:
    """A non-negative integer or None; used for section ordering."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def validate_sections(raw, name: str = "", contact=None, headline: str = "") -> dict:
    """Coerce arbitrary submitted data into the canonical document shape.

    This is the single validation point. It never raises on bad input -- it
    drops what it cannot understand -- so a malformed POST degrades to a shorter
    resume instead of a 500.
    """
    document = {
        "name": _text(name, 160),
        "contact": [],
        "headline": _text(headline, MAX_HEADLINE),
        "sections": [],
    }

    # Contact details: only strings the user actually supplied.
    if isinstance(contact, (list, tuple)):
        for item in contact:
            value = _text(item, MAX_CONTACT_ITEM)
            if value and value not in document["contact"]:
                document["contact"].append(value)
            if len(document["contact"]) >= MAX_CONTACT_ITEMS:
                break

    # Accept either a JSON string (from a hidden form field) or a real list.
    if isinstance(raw, str):
        import json

        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            raw = []

    if not isinstance(raw, (list, tuple)):
        raw = []

    for item in raw:
        if not isinstance(item, dict):
            continue
        kind = _text(item.get("kind"), 20)
        if kind not in KINDS:
            continue

        key = _text(item.get("key"), 40) or kind
        title = _text(item.get("title"), MAX_SECTION_TITLE) or \
            DEFAULT_SECTION_TITLES.get(key, "Section")

        section = {"key": key, "title": title, "kind": kind}

        if kind == "text":
            section["text"] = _text(item.get("text"), MAX_TEXT)

        elif kind == "skill_groups":
            groups = []
            raw_groups = item.get("groups")
            if isinstance(raw_groups, (list, tuple)):
                for group in raw_groups:
                    if not isinstance(group, dict):
                        continue
                    label = _text(group.get("label"), MAX_SECTION_TITLE)
                    values = []
                    for skill in group.get("skills") or []:
                        value = _text(skill, MAX_SKILL)
                        if value and value not in values:
                            values.append(value)
                        if len(values) >= MAX_SKILLS:
                            break
                    if values:
                        groups.append({"label": label, "skills": values})
                    if len(groups) >= MAX_ITEMS:
                        break
            section["groups"] = groups

        elif kind == "entries":
            entries = []
            for entry in item.get("entries") or []:
                if not isinstance(entry, dict):
                    continue
                clean = {
                    "title": _text(entry.get("title"), 200),
                    "organization": _text(entry.get("organization"), 200),
                    "start_date": _text(entry.get("start_date"), 40),
                    "end_date": _text(entry.get("end_date"), 40),
                    "detail": _text(entry.get("detail"), 200),
                    "tech_stack": _text(entry.get("tech_stack"), 200),
                    "bullets": _lines(entry.get("bullets"), MAX_BULLETS, MAX_BULLET),
                }
                entries.append(clean)
                if len(entries) >= MAX_ITEMS:
                    break
            section["entries"] = entries

        elif kind == "list":
            section["items"] = _lines(item.get("items"), MAX_ITEMS, MAX_BULLET)

        document["sections"].append(section)
        if len(document["sections"]) >= MAX_SECTIONS:
            break

    # A section with nothing in it is noise on a resume; drop it rather than
    # render a heading over nothing.
    document["sections"] = [
        section for section in document["sections"] if _section_has_content(section)
    ]
    return document


def _section_has_content(section: dict) -> bool:
    if section["kind"] == "text":
        return bool(section.get("text"))
    if section["kind"] == "skill_groups":
        return bool(section.get("groups"))
    if section["kind"] == "entries":
        return bool(section.get("entries"))
    if section["kind"] == "list":
        return bool(section.get("items"))
    return False


def is_empty(document: dict) -> bool:
    """True when there is nothing worth showing, downloading or saving.

    A name on its own is not a resume. Deciding this on sections rather than on
    the whole document is what stops a blank resume -- the candidate's name and
    nothing else -- from being stored as if it were real content.
    """
    return not (document.get("sections") or [])


# --------------------------------------------------------------------------
# Building from generated content
# --------------------------------------------------------------------------

def _skill_groups(tailored: dict) -> list[dict]:
    """Prefer the agent's own categories; fall back to a single flat group."""
    groups = tailored.get("skill_categories")
    if isinstance(groups, list) and groups:
        out = []
        for group in groups:
            if not isinstance(group, dict):
                continue
            label = _text(group.get("label"), MAX_SECTION_TITLE)
            values = [_text(skill, MAX_SKILL) for skill in group.get("skills") or []]
            values = [value for value in values if value]
            if values:
                out.append({"label": label, "skills": values})
        if out:
            return out

    values = [_text(skill, MAX_SKILL) for skill in tailored.get("highlighted_skills") or []]
    values = [value for value in values if value]
    return [{"label": "", "skills": values}] if values else []


def sections_from_tailored(
    tailored: dict,
    candidate: dict | None = None,
    section_order: list[str] | None = None,
) -> dict:
    """Build the canonical document from a generated/edited tailored dict.

    `section_order` is the selected template's order. It is passed in rather
    than imported so this module stays free of the agent dependency, and so a
    template such as "Technical ATS" (skills first) or "Minimal ATS" (no
    summary) produces the same order in the preview, the TXT and the PDF as it
    already did in the generated text. Certifications are appended when the
    template does not place them, which is what the text renderer does too.

    Copies only what is already present. An absent field produces no line rather
    than a placeholder, which is what keeps "Not provided" out of a document
    someone is about to send to an employer.
    """
    tailored = tailored if isinstance(tailored, dict) else {}
    candidate = candidate if isinstance(candidate, dict) else {}

    contact = contact_for(tailored if tailored.get("email") or tailored.get("phone")
                          else candidate)

    headline = _text(
        tailored.get("target_role") or candidate.get("degree"), MAX_HEADLINE
    )

    raw_sections = []

    summary = _text(tailored.get("professional_summary"), MAX_TEXT)
    if summary:
        raw_sections.append({
            "key": "professional_summary", "title": "Professional Summary",
            "kind": "text", "text": summary,
        })

    raw_sections.append({
        "key": "skills", "title": "Technical Skills",
        "kind": "skill_groups", "groups": _skill_groups(tailored),
    })

    experience = []
    for item in tailored.get("experience") or []:
        if not isinstance(item, dict):
            continue
        experience.append({
            "title": _text(item.get("title"), 200),
            "organization": _text(item.get("organization"), 200),
            "start_date": _text(item.get("start_date"), 40),
            "end_date": _text(item.get("end_date"), 40),
            "detail": "",
            "tech_stack": "",
            "bullets": _lines(
                item.get("bullets") if isinstance(item.get("bullets"), list)
                else "\n".join(item.get("bullets") or []),
                MAX_BULLETS, MAX_BULLET,
            ),
        })
    raw_sections.append({
        "key": "experience", "title": "Experience",
        "kind": "entries", "entries": experience,
    })

    projects = []
    for item in tailored.get("projects") or []:
        if not isinstance(item, dict):
            continue
        projects.append({
            "title": _text(item.get("title"), 200),
            "organization": "",
            "start_date": "",
            "end_date": "",
            "detail": "",
            "tech_stack": _text(item.get("tech_stack"), 200),
            "bullets": _lines(
                item.get("bullets") if isinstance(item.get("bullets"), list)
                else "\n".join(item.get("bullets") or []),
                MAX_BULLETS, MAX_BULLET,
            ),
        })
    raw_sections.append({
        "key": "projects", "title": "Projects",
        "kind": "entries", "entries": projects,
    })

    education = []
    for item in tailored.get("education") or []:
        if not isinstance(item, dict):
            continue
        education.append({
            "title": _text(item.get("degree") or item.get("field"), 200),
            "organization": _text(item.get("institution"), 200),
            "start_date": _text(item.get("start_date"), 40),
            "end_date": _text(item.get("end_date"), 40),
            "detail": "",
            "tech_stack": "",
            "bullets": [],
        })
    if not education:
        # Some profiles only carry a degree/CGPA on the profile row.
        degree = _text(tailored.get("degree") or candidate.get("degree"), 200)
        college = _text(tailored.get("college") or candidate.get("college"), 200)
        cgpa = tailored.get("cgpa", candidate.get("cgpa"))
        if degree or college:
            detail = ""
            if cgpa not in (None, ""):
                detail = f"CGPA: {cgpa}"
            education.append({
                "title": degree, "organization": college,
                "start_date": "", "end_date": "",
                "detail": detail, "tech_stack": "", "bullets": [],
            })
    raw_sections.append({
        "key": "education", "title": "Education",
        "kind": "entries", "entries": education,
    })

    certifications = []
    for item in tailored.get("certifications") or []:
        if isinstance(item, dict):
            name_value = _text(item.get("name"), 200)
            issuer = _text(item.get("issuer"), 200)
            value = " — ".join(part for part in (name_value, issuer) if part)
        else:
            value = _text(item, MAX_BULLET)
        if value:
            certifications.append(value)
    raw_sections.append({
        "key": "certifications", "title": "Certifications",
        "kind": "list", "items": certifications,
    })

    ordered = _apply_section_order(raw_sections, section_order)

    return validate_sections(ordered, name=name_of(tailored, candidate),
                             contact=contact, headline=headline)


def _apply_section_order(raw_sections: list[dict], section_order) -> list[dict]:
    """Reorder sections to match a template, omitting ones the template drops.

    A template that leaves a section out genuinely means it -- Minimal ATS is
    described as "No summary", so the summary is not rendered under it. This
    mirrors the existing plain-text renderer exactly, so switching a template
    changes the preview, the TXT and the PDF identically.

    Certifications are the one exception: they are appended when the template
    does not place them, which is what the text renderer does.
    """
    if not section_order:
        return raw_sections

    wanted = [key for key in section_order if key in DEFAULT_SECTION_TITLES]
    if not wanted:
        return raw_sections

    by_key = {section["key"]: section for section in raw_sections}
    ordered = []
    for key in wanted:
        # A template may name a section the candidate has nothing for; it is
        # then absent from the document rather than rendered empty.
        if key in by_key:
            ordered.append(by_key.pop(key))

    if "certifications" not in wanted and "certifications" in by_key:
        ordered.append(by_key.pop("certifications"))

    # Anything else the template does not mention is left out, exactly as the
    # plain-text renderer leaves it out.
    return ordered


def name_of(tailored: dict, candidate: dict | None = None) -> str:
    candidate = candidate if isinstance(candidate, dict) else {}
    return _text(tailored.get("name") or candidate.get("name"), 160)


def contact_for(source: dict | None) -> list[str]:
    """The contact line, taken only from fields that are actually present.

    A saved resume keeps its own copy of these, so it still renders correctly
    after the profile is edited.
    """
    source = source if isinstance(source, dict) else {}
    email = _text(source.get("email"), MAX_CONTACT_ITEM)
    phone = _text(source.get("phone"), MAX_CONTACT_ITEM)
    contact = [value for value in (email, phone) if value]
    # Explicitly supplied extras (for example a location the user typed) are
    # appended, but never invented here.
    for extra in source.get("contact") or []:
        value = _text(extra, MAX_CONTACT_ITEM)
        if value and value not in contact:
            contact.append(value)
        if len(contact) >= MAX_CONTACT_ITEMS:
            break
    return contact[:MAX_CONTACT_ITEMS]


# --------------------------------------------------------------------------
# Plain text (TXT download, and the canonical stored text)
# --------------------------------------------------------------------------

def _entry_headline(entry: dict) -> str:
    left = " - ".join(p for p in (entry.get("title"), entry.get("organization")) if p)
    right = date_range(entry.get("start_date"), entry.get("end_date"))
    if entry.get("tech_stack") and "tech_stack" in entry:
        right = f"{entry['tech_stack']} | {right}" if right else entry["tech_stack"]
    if left and right:
        return f"{left} | {right}"
    return left or right


def date_range(start, end) -> str:
    start = _text(start, 40)
    end = _text(end, 40)
    if start and end:
        return f"{start} - {end}"
    return start or end


def render_text(document: dict) -> str:
    """Clean, readable plain text. Section titles are used verbatim."""
    lines: list[str] = []

    name = _text(document.get("name"), 160)
    if name:
        lines.append(name)
    contact = [c for c in (document.get("contact") or []) if c]
    if contact:
        lines.append(" | ".join(contact))
    headline = _text(document.get("headline"), MAX_HEADLINE)
    if headline:
        lines.append(headline)

    for section in document.get("sections") or []:
        body: list[str] = []
        title = _text(section.get("title"), MAX_SECTION_TITLE)

        if section["kind"] == "text":
            body.append(_text(section.get("text"), MAX_TEXT))

        elif section["kind"] == "skill_groups":
            for group in section.get("groups") or []:
                values = ", ".join(group.get("skills") or [])
                if not values:
                    continue
                label = _text(group.get("label"), MAX_SECTION_TITLE)
                body.append(f"{label}: {values}" if label else values)

        elif section["kind"] == "entries":
            for entry in section.get("entries") or []:
                headline_text = _entry_headline(entry)
                if headline_text:
                    body.append(headline_text)
                detail = _text(entry.get("detail"), 200)
                if detail:
                    body.append(detail)
                for bullet in entry.get("bullets") or []:
                    body.append(f"- {bullet}")

        elif section["kind"] == "list":
            body.extend(f"- {item}" for item in section.get("items") or [])

        if not body:
            continue
        if title:
            lines.append("")
            lines.append(title.upper())
            lines.append("")
        lines.extend(body)

    # Collapse any run of blank lines to one, and trim the ends.
    cleaned: list[str] = []
    for line in lines:
        if not line.strip() and (not cleaned or not cleaned[-1].strip()):
            continue
        cleaned.append(line)

    return "\n".join(cleaned).strip() + "\n" if any(l.strip() for l in cleaned) else ""


# --------------------------------------------------------------------------
# HTML (on-screen preview)
# --------------------------------------------------------------------------

def esc(value) -> str:
    return _html.escape(str(value or ""), quote=True)


def render_html(document: dict) -> str:
    """Preview markup. Every value passes through esc() -- no raw user text."""
    parts = ['<article class="resume-doc">']

    name = _text(document.get("name"), 160)
    if name:
        parts.append(f'<h1 class="resume-doc__name">{esc(name)}</h1>')

    contact = [c for c in (document.get("contact") or []) if c]
    if contact:
        parts.append(
            '<p class="resume-doc__contact">'
            + '&nbsp;&nbsp;|&nbsp;&nbsp;'.join(esc(c) for c in contact)
            + "</p>"
        )

    headline = _text(document.get("headline"), MAX_HEADLINE)
    if headline:
        parts.append(f'<p class="resume-doc__headline">{esc(headline)}</p>')

    for section in document.get("sections") or []:
        title = _text(section.get("title"), MAX_SECTION_TITLE)
        if not title:
            continue
        parts.append(f'<h2 class="resume-doc__heading">{esc(title)}</h2>')

        if section["kind"] == "text":
            parts.append(f'<p class="resume-doc__para">{esc(section.get("text"))}</p>')

        elif section["kind"] == "skill_groups":
            parts.append('<div class="resume-doc__skills">')
            for group in section.get("groups") or []:
                label = _text(group.get("label"), MAX_SECTION_TITLE)
                values = group.get("skills") or []
                if not values:
                    continue
                label_html = f'<span class="resume-doc__skill-label">{esc(label)}</span>' if label else ""
                parts.append(
                    '<div class="resume-doc__skill-row">'
                    + label_html
                    + '<span class="resume-doc__skill-values">'
                    + ", ".join(esc(v) for v in values)
                    + "</span></div>"
                )
            parts.append("</div>")

        elif section["kind"] == "entries":
            parts.append('<div class="resume-doc__entries">')
            for entry in section.get("entries") or []:
                headline_text = _entry_headline(entry)
                if headline_text:
                    parts.append(
                        f'<p class="resume-doc__entry-head">{esc(headline_text)}</p>'
                    )
                detail = _text(entry.get("detail"), 200)
                if detail:
                    parts.append(
                        f'<p class="resume-doc__entry-detail">{esc(detail)}</p>'
                    )
                bullets = entry.get("bullets") or []
                if bullets:
                    parts.append("<ul>")
                    for bullet in bullets:
                        parts.append(f"<li>{esc(bullet)}</li>")
                    parts.append("</ul>")
            parts.append("</div>")

        elif section["kind"] == "list":
            parts.append('<ul class="resume-doc__bullets">')
            for item in section.get("items") or []:
                parts.append(f"<li>{esc(item)}</li>")
            parts.append("</ul>")

    parts.append("</article>")
    return "".join(parts)


# --------------------------------------------------------------------------
# PDF
# --------------------------------------------------------------------------

# PyMuPDF's Story engine supports a small, well-defined subset of HTML/CSS, so
# this stays deliberately simple: block elements, weights and colours. No
# layout tricks that would risk rendering as an image or silently dropping out.
PDF_CSS = """
* { font-family: sans-serif; }
.resume-name { font-size: 17pt; font-weight: bold; color: #102A56; margin: 0 0 2pt 0; }
.resume-contact { font-size: 9pt; color: #33475B; margin: 0 0 1pt 0; }
.resume-headline { font-size: 9.5pt; color: #2563EB; margin: 0 0 2pt 0; }
.resume-heading { font-size: 10pt; font-weight: bold; color: #102A56;
                  margin-top: 12pt; margin-bottom: 3pt; }
.resume-para { font-size: 9.5pt; line-height: 1.42; margin: 0 0 2pt 0; }
.resume-skill-row { font-size: 9.5pt; line-height: 1.42; margin: 0 0 1pt 0; }
.resume-skill-label { font-weight: bold; color: #102A56; }
.resume-skill-values { color: #172B4D; }
.resume-entry-head { font-size: 9.5pt; font-weight: bold; color: #172B4D; margin: 0 0 1pt 0; }
.resume-entry-detail { font-size: 9pt; color: #33475B; margin: 0 0 1pt 0; }
ul { margin: 1pt 0 3pt 10pt; }
li { font-size: 9.5pt; line-height: 1.42; }
"""

# 0.6in margins on A4 -- inside the range most ATS parsers expect.
PDF_MARGIN = 43


def _pdf_body(document: dict) -> str:
    parts = []

    name = _text(document.get("name"), 160)
    if name:
        parts.append(f'<p class="resume-name">{esc(name)}</p>')

    contact = [c for c in (document.get("contact") or []) if c]
    if contact:
        parts.append(
            '<p class="resume-contact">'
            + " &nbsp;|&nbsp; ".join(esc(c) for c in contact)
            + "</p>"
        )

    headline = _text(document.get("headline"), MAX_HEADLINE)
    if headline:
        parts.append(f'<p class="resume-headline">{esc(headline)}</p>')

    for section in document.get("sections") or []:
        title = _text(section.get("title"), MAX_SECTION_TITLE)
        if not title:
            continue
        parts.append(f'<p class="resume-heading">{esc(title.upper())}</p>')

        if section["kind"] == "text":
            parts.append(f'<p class="resume-para">{esc(section.get("text"))}</p>')

        elif section["kind"] == "skill_groups":
            for group in section.get("groups") or []:
                values = group.get("skills") or []
                if not values:
                    continue
                label = _text(group.get("label"), MAX_SECTION_TITLE)
                label_html = f'<span class="resume-skill-label">{esc(label)}:</span> ' if label else ""
                parts.append(
                    '<p class="resume-skill-row">'
                    + label_html
                    + f'<span class="resume-skill-values">{esc(", ".join(values))}</span>'
                    + "</p>"
                )

        elif section["kind"] == "entries":
            entries = section.get("entries") or []
            for index, entry in enumerate(entries):
                # <p> before the first <ul> and </p> after the last one keeps the
                # Story engine from breaking the spacing between entries.
                if index == 0:
                    parts.append("<p>")
                headline_text = _entry_headline(entry)
                if headline_text:
                    parts.append(
                        f'<p class="resume-entry-head">{esc(headline_text)}</p>'
                    )
                detail = _text(entry.get("detail"), 200)
                if detail:
                    parts.append(
                        f'<p class="resume-entry-detail">{esc(detail)}</p>'
                    )
                bullets = entry.get("bullets") or []
                if bullets:
                    parts.append("<ul>")
                    for bullet in bullets:
                        parts.append(f"<li>{esc(bullet)}</li>")
                    parts.append("</ul>")
                if index == len(entries) - 1:
                    parts.append("</p>")

        elif section["kind"] == "list":
            items = section.get("items") or []
            if items:
                parts.append("<p><ul>")
                for item in items:
                    parts.append(f"<li>{esc(item)}</li>")
                parts.append("</ul></p>")

    return "".join(parts)


def render_pdf(document: dict) -> bytes:
    """Return real PDF bytes with selectable text.

    PyMuPDF is already a declared requirement (it extracts uploaded resumes), so
    this adds no new dependency. The Story engine paginates the markup and
    embeds actual glyphs, so an ATS reading the file sees the same words the
    preview shows -- not a picture of the preview.
    """
    import pymupdf

    body = _pdf_body(document)
    if not body.strip():
        raise ValueError("There is no resume content to put in a PDF yet.")

    paper = pymupdf.paper_rect("a4")

    def rectfn(page_number, filled):
        # A truthy mediabox starts a new page; the engine calls again until the
        # content fits, which is what paginates a long resume.
        return paper, paper + (PDF_MARGIN, PDF_MARGIN, -PDF_MARGIN, -PDF_MARGIN), \
            pymupdf.Matrix(1, 0, 0, 1, 0, 0)

    story = pymupdf.Story(html=body, user_css=PDF_CSS)
    document_obj = story.write_with_links(rectfn)

    stream = io.BytesIO()
    document_obj.save(stream)
    return stream.getvalue()


def pdf_page_count(pdf_bytes: bytes) -> int:
    """Pages in a generated PDF; used by tests to confirm real pagination."""
    import pymupdf

    with pymupdf.open("pdf", pdf_bytes) as document_obj:
        return document_obj.page_count


_PDF_LIGATURES = {
    "\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl",
    "\ufb03": "ffi", "\ufb04": "ffl", "\ufb06": "st",
}


def pdf_text(pdf_bytes: bytes) -> str:
    """Extract the text a PDF actually contains -- proves it is not an image.

    The Story engine typesets fi/fl ligatures as single glyphs, which come back
    out of extraction as U+FB01 and friends rather than "fi". They are folded
    back here so a substring check against the source text is meaningful; the
    characters are visually and semantically identical to the reader.
    """
    import pymupdf

    with pymupdf.open("pdf", pdf_bytes) as document_obj:
        text = "\n".join(page.get_text() for page in document_obj)
    for ligature, plain in _PDF_LIGATURES.items():
        text = text.replace(ligature, plain)
    return text


def safe_filename(value: str, fallback: str = "resume") -> str:
    """A download filename that is safe on every platform."""
    slug = re.sub(r"[^A-Za-z0-9]+", "-", str(value or "")).strip("-").lower()
    return (slug or fallback)[:80]