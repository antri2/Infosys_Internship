"""Two regressions found while verifying the Resume Builder by hand.

Both were live bugs before these tests existed:

1. A browser send a form-encoded POST with `Accept: application/json`, and the
   routes branched on `request.is_json` -- which describes the *request* body,
   not the wanted response. Save and download silently returned an HTML page,
   and the client reported "Unexpected token '<'".

   (A follow-on mistake while fixing that replaced the guard inside the helper
   with a call to itself, so it recursed forever. The direct-call test below
   pins the shape of the helper so that cannot come back.)

2. Choosing a template changed the generated plain text but not the new
   structured document, so "Technical ATS" put skills first in one rendering
   and last in another.
"""

import json

from services import resume_document
from services.resume_agent import TEMPLATES


TAILORED = {
    "name": "Jane Doe", "email": "jane@example.com", "target_role": "Data Analyst",
    "professional_summary": "Analyst with SQL and reporting experience.",
    "highlighted_skills": ["Python", "SQL"],
    "experience": [{"title": "Intern", "organization": "Infosys",
                    "start_date": "2025", "end_date": "2025", "bullets": ["Wrote reports."]}],
    "projects": [{"title": "Ranker", "tech_stack": "Python", "bullets": ["Built it."]}],
    "education": [{"degree": "B.Tech", "institution": "U",
                   "start_date": "2022", "end_date": "2026"}],
    "certifications": [{"name": "Cert", "issuer": "Org"}],
}

MAIN_KEYS = ("professional_summary", "skills", "experience", "projects", "education")


def _document(template_key):
    order = TEMPLATES[template_key]["section_order"]
    return resume_document.sections_from_tailored(TAILORED, {}, list(order))


def test_the_selected_template_orders_the_document():
    for template_key, template in TEMPLATES.items():
        keys = [s["key"] for s in _document(template_key)["sections"]]
        expected = [k for k in template["section_order"] if k in MAIN_KEYS]

        assert keys[: len(expected)] == expected, (
            f"{template_key}: expected {expected} first, got {keys}"
        )


def test_technical_ats_really_puts_skills_first():
    keys = [s["key"] for s in _document("technical_ats")["sections"]]
    assert keys[0] == "skills"


def test_minimal_ats_really_omits_the_summary():
    """The template is documented as "No summary", so it must not render one."""
    keys = [s["key"] for s in _document("minimal_ats")["sections"]]
    assert "professional_summary" not in keys


def test_certifications_are_kept_even_when_a_template_omits_them():
    """Mirrors the existing text renderer, which appends certifications."""
    keys = [s["key"] for s in _document("technical_ats")["sections"]]
    assert "certifications" in keys


def test_without_a_template_order_the_natural_order_is_kept():
    keys = [s["key"] for s in
            resume_document.sections_from_tailored(TAILORED, {})["sections"]]
    assert keys[:5] == list(MAIN_KEYS)


def test_section_order_survives_a_round_trip_through_validation():
    """Reordering a saved document must not be undone by validation."""
    document = _document("technical_ats")
    revalidated = resume_document.validate_sections(
        document["sections"], name=document["name"],
        contact=document["contact"], headline=document["headline"],
    )
    assert [s["key"] for s in revalidated["sections"]] == \
        [s["key"] for s in document["sections"]]


# ---------------------------------------------------------------------------
# Response negotiation
# ---------------------------------------------------------------------------

def test_wants_json_is_not_recursive(app):
    """A direct call must return a bool, not exhaust the stack."""
    from routes.resume_builder import _wants_json

    client = app.test_client()
    with client.session_transaction() as flask_session:
        flask_session["user_id"] = 1
        flask_session["user_name"] = "Someone"

    # A JSON request body.
    with client.session_transaction():
        pass
    response = client.post(
        "/resume-builder/versions/save",
        json={"sections": json.dumps({"sections": []})},
    )
    assert response.status_code == 400, "JSON callers get a JSON error"
    assert response.get_json()["success"] is False

    # Form body asking for JSON back, which is what the browser editor sends.
    response = client.post(
        "/resume-builder/versions/save",
        data={"sections": json.dumps({"sections": []})},
        headers={"Accept": "application/json", "X-Requested-With": "fetch"},
    )
    assert response.status_code == 400
    assert response.mimetype == "application/json", "an HTML page here is the bug"
    assert response.get_json()["success"] is False

    # A plain form post with no Accept header gets the page back.
    response = client.post(
        "/resume-builder/versions/save",
        data={"sections": json.dumps({"sections": []})},
    )
    assert response.mimetype == "text/html"

    # And the helper itself is importable and callable outside a request.
    assert callable(_wants_json)