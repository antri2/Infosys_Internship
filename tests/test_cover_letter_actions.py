"""Cover Letter Save and Regenerate must behave predictably.

The contract:
  * Save persists the exact editor content and never calls the model.
  * Regenerate creates a new draft only when asked, and does not overwrite the
    saved letter until the user saves it.
"""
import json

import pytest

from database.db import get_db
from services import cover_letter_agent as agent


def _body(seed: str, name: str = "Candidate") -> str:
    """A structurally valid letter body, inside the agent's 250-400 word window.

    It cites the target role, the candidate's verified university, and the
    AWS Certified Developer credential the fixture profile carries, which is what
    the agent requires before it accepts model output. The candidate's real name
    must appear, so tests pass it in.
    """
    sentence = ("My time at Test University, along with the AWS Certified "
                "Developer credential I completed, prepared me to contribute "
                "steady effort and an evidence based approach while learning. ")
    return (f"Dear Hiring Manager,\n\n{seed} I am applying for the Data Analyst "
            "position. " + sentence * 13 + f"\n\nSincerely,\n{name}")


LETTER_V1 = _body("This is the first saved version.")
EDITED = _body("I edited this by hand before saving.")
GENERATED = _body("A freshly generated draft.")


@pytest.fixture
def no_model(monkeypatch):
    """Any LLM call during these tests is a failure."""
    from services import cover_letter_agent as cla

    def boom(*args, **kwargs):
        raise AssertionError("Save/Regenerate must not call the model")

    monkeypatch.setattr(cla, "generate", boom)
    return cla


@pytest.fixture
def signed(app, candidate):
    """Replace the fixtures with letters signed by this candidate's real name."""
    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT name FROM users WHERE id = %s", (candidate["user_id"],))
            name = cursor.fetchone()["name"]
    return name


def _save(client, content, letter_id=None, job_id=None):
    return client.post("/cover-letter/save", json={
        "content": content, "letter_id": letter_id, "job_id": job_id})


def test_save_persists_the_exact_editor_text(client, candidate, no_model):
    response = _save(client, EDITED)
    assert response.status_code in (200, 201), response.get_data(as_text=True)
    letter_id = response.get_json()["letter_id"]

    with client.application.app_context():
        stored = agent.load_cover_letter(get_db(), candidate["user_id"], letter_id)
    assert stored["content"] == EDITED


def test_save_never_calls_the_model(client, candidate, no_model):
    """The fixture raises if the model is touched, so reaching here proves it."""
    assert _save(client, EDITED).status_code in (200, 201)


def test_save_update_replaces_content_in_place(client, candidate, no_model):
    first = _save(client, LETTER_V1)
    letter_id = first.get_json()["letter_id"]

    second = _save(client, EDITED, letter_id=letter_id)
    assert second.status_code in (200, 201)
    assert second.get_json()["letter_id"] == letter_id

    with client.application.app_context():
        stored = agent.load_cover_letter(get_db(), candidate["user_id"], letter_id)
    assert stored["content"] == EDITED


def test_empty_content_is_rejected(client, candidate):
    assert _save(client, "   ").status_code == 400


# --------------------------------------------------------------- regenerate ---

def test_generate_does_not_persist_until_the_user_saves(client, candidate, signed,
                                                        monkeypatch):
    """Generate returns an unsaved draft; only Save creates a stored letter."""
    from services import cover_letter_agent as cla

    monkeypatch.setattr(cla, "generate", lambda prompt, **kwargs: json.dumps({
        "cover_letter": _body("A freshly generated draft.", signed),
        "highlighted_verified_facts": ["AWS Certified Developer"],
        "flagged_claims": [],
    }))

    draft = client.post("/cover-letter/generate", json={
        "generic": True, "target_role": "Data Analyst"}).get_json()
    assert draft["letter_id"] is None
    assert draft["used_fallback"] is False, "the stubbed draft should be accepted"

    with client.application.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS c FROM cover_letters WHERE user_id = %s",
                           (candidate["user_id"],))
            assert cursor.fetchone()["c"] == 0


def test_saving_alone_never_refreshes_the_stored_letter(client, candidate,
                                                        monkeypatch, no_model):
    """A plain Save must not regenerate the letter behind the user's back."""
    letter_id = _save(client, LETTER_V1).get_json()["letter_id"]
    again = _save(client, EDITED, letter_id=letter_id)
    assert again.status_code in (200, 201)

    with client.application.app_context():
        stored = agent.load_cover_letter(get_db(), candidate["user_id"], letter_id)
    assert stored["content"] == EDITED, "Save regenerated instead of persisting"


def test_regenerate_returns_a_new_draft_without_overwriting(client, candidate,
                                                            signed, monkeypatch):
    """The saved letter keeps its content until the user explicitly saves."""
    from services import cover_letter_agent as cla

    monkeypatch.setattr(cla, "generate", lambda prompt, **kwargs: json.dumps({
        "cover_letter": _body("A freshly generated draft.", signed),
        "highlighted_verified_facts": ["AWS Certified Developer"],
        "flagged_claims": [],
    }))

    letter_id = _save(client, LETTER_V1).get_json()["letter_id"]

    regenerated = client.post("/cover-letter/regenerate", json={
        "letter_id": letter_id, "generic": True, "target_role": "Data Analyst"})
    assert regenerated.status_code == 200, regenerated.get_data(as_text=True)
    assert "generated draft" in regenerated.get_json()["cover_letter"].lower()

    # The stored version is untouched until the user saves.
    with client.application.app_context():
        stored = agent.load_cover_letter(get_db(), candidate["user_id"], letter_id)
    assert stored["content"] == LETTER_V1


def test_saving_the_regenerated_draft_updates_the_stored_letter(client, candidate,
                                                                 signed, monkeypatch):
    from services import cover_letter_agent as cla

    monkeypatch.setattr(cla, "generate", lambda prompt, **kwargs: json.dumps({
        "cover_letter": _body("A freshly generated draft.", signed),
        "highlighted_verified_facts": ["AWS Certified Developer"],
        "flagged_claims": [],
    }))

    letter_id = _save(client, LETTER_V1).get_json()["letter_id"]

    draft = client.post("/cover-letter/regenerate", json={
        "letter_id": letter_id, "generic": True,
        "target_role": "Data Analyst"}).get_json()["cover_letter"]

    _save(client, draft, letter_id=letter_id)
    with client.application.app_context():
        stored = agent.load_cover_letter(get_db(), candidate["user_id"], letter_id)
    assert stored["content"] == draft


def test_regenerate_never_invents_a_company_for_a_role_only_letter(client, candidate,
                                                                   monkeypatch):
    from services import cover_letter_agent as cla

    monkeypatch.setattr(cla, "generate", lambda prompt, **kwargs: json.dumps({
        "cover_letter": GENERATED,
        "highlighted_verified_facts": ["AWS Certified Developer"],
        "flagged_claims": [],
    }))

    with client.application.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT DISTINCT company FROM jobs")
            companies = [row["company"] for row in cursor.fetchall() if row["company"]]

    payload = client.post("/cover-letter/regenerate", json={
        "letter_id": _save(client, LETTER_V1).get_json()["letter_id"],
        "generic": True, "target_role": "Data Analyst",
    }).get_json()

    lowered = payload["cover_letter"].casefold()
    assert not [name for name in companies if name.casefold() in lowered]
    assert payload["job_id"] is None


# ------------------------------------------------------------------- wiring ---

def test_cover_letter_page_exposes_separate_save_and_regenerate(client):
    html = client.get("/cover-letter/").get_data(as_text=True)
    assert 'id="save-cover-letter"' in html
    assert 'id="regenerate-cover-letter"' in html
    # Save posts the editor contents; Regenerate posts to the regenerate route.
    # The route aliases are interchangeable, so the rendered path is not
    # asserted -- only that both endpoints are wired to the same behaviour.
    assert "content: editor.value" in html
    # Rendered paths: url_for picks one of each endpoint's interchangeable
    # aliases (/save, /save-letter, /update and /regenerate, /regenerate-letter).
    assert "/cover-letter/update" in html
    assert "/cover-letter/regenerate-letter" in html
    # Regenerate must tell the user the saved letter is not yet replaced.
    assert "save it to update the stored letter" in html


def test_save_aliases_all_persist_the_same_content(client, candidate):
    """The /save, /save-letter and /update aliases share one implementation."""
    body = EDITED
    ids = []
    for path in ("/cover-letter/save", "/cover-letter/save-letter",
                 "/cover-letter/update"):
        response = client.post(path, json={"content": body})
        assert response.status_code in (200, 201), path
        ids.append(response.get_json()["letter_id"])

    with client.application.app_context():
        db = get_db()
        for letter_id in ids:
            stored = agent.load_cover_letter(db, candidate["user_id"], letter_id)
            assert stored["content"] == body