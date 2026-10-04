"""Regression coverage for the generic Cover Letter UX."""
from database.db import get_db
from services import cover_letter_agent


def test_cover_letter_page_is_generic_by_default(client):
    response = client.get("/cover-letter/")

    assert response.status_code == 200
    assert b"No specific job is selected by default" in response.data
    assert b'id="cover-letter-job-id"' not in response.data
    assert b'name="job_id"' not in response.data
    assert b"cover-letter-role" not in response.data
    assert b"Job ID" not in response.data


def test_generic_cover_letter_can_be_saved_loaded_updated_and_regenerated(
    app, client, candidate, monkeypatch
):
    captured = {}

    def broken_generate(prompt, **kwargs):
        captured["prompt"] = prompt
        return "not-json"

    monkeypatch.setattr(cover_letter_agent, "generate", broken_generate)
    details = (
        "Company: Acme Labs\n"
        "Specific role: AI Engineer\n"
        "Job description: Build reliable machine learning features.\n"
        "Required skills: Python, SQL\n"
        "Project details: CareerAI\n"
        "Internship details: Data analysis internship"
    )
    generated = client.post(
        "/cover-letter/generate",
        json={"generic": True, "extra_context": details},
    )

    assert generated.status_code == 200
    generated_payload = generated.get_json()
    assert generated_payload["job_id"] is None
    assert generated_payload["job"] is None
    assert generated_payload["cover_letter"]
    assert "Acme Labs" in captured["prompt"]

    content = generated_payload["cover_letter"]
    saved = client.post(
        "/cover-letter/save",
        json={"content": content},
    )
    assert saved.status_code == 200
    saved_payload = saved.get_json()
    assert saved_payload["job_id"] is None

    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute(
                "SELECT job_id FROM cover_letters WHERE id = %s AND user_id = %s",
                (saved_payload["letter_id"], candidate["user_id"]),
            )
            assert cursor.fetchone()["job_id"] is None

    loaded = client.get(f"/cover-letter/load/{saved_payload['letter_id']}")
    assert loaded.status_code == 200
    assert loaded.get_json()["job_id"] is None

    edited = content + "\n\nCandidate edit."
    updated = client.post(
        "/cover-letter/update",
        json={
            "letter_id": saved_payload["letter_id"],
            "content": edited,
        },
    )
    assert updated.status_code == 200
    assert updated.get_json()["content"] == edited

    regenerated = client.post(
        "/cover-letter/regenerate",
        json={"letter_id": saved_payload["letter_id"]},
    )
    assert regenerated.status_code == 200
    assert regenerated.get_json()["job_id"] is None

    role_regenerated = client.post(
        "/cover-letter/regenerate",
        json={"letter_id": saved_payload["letter_id"], "target_role": "AI Engineer"},
    )
    assert role_regenerated.status_code == 200
    assert "AI Engineer" in role_regenerated.get_json()["cover_letter"]


def test_cover_letter_keeps_role_level_selector_without_exposing_job_ids(client):
    response = client.get("/cover-letter/?target_role=AI%20Engineer")

    assert response.status_code == 200
    assert b'id="target-role"' in response.data
    assert b"AI Engineer" in response.data
    assert b'name="job_id"' not in response.data
    assert b"Job ID" not in response.data


def test_role_level_cover_letter_resolves_a_representative_job(
    app, client, monkeypatch
):
    captured = {}

    def broken_generate(prompt, **kwargs):
        captured["prompt"] = prompt
        return "not-json"

    monkeypatch.setattr(cover_letter_agent, "generate", broken_generate)
    response = client.post(
        "/cover-letter/generate",
        json={"generic": True, "target_role": "AI Engineer"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["job_id"] is not None
    assert payload["job"]["title"]
    assert payload["job"]["title"] in captured["prompt"]
    assert payload["job"]["title"] in payload["cover_letter"]
