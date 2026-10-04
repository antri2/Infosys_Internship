"""Coverage for role-level Resume Builder instructions and exact approval saves."""
import json

from database.db import get_db
from services import resume_agent
from services.agent_orchestrator import AgentOrchestrator
from services.role_catalog import find_role_job


def _role_job(app, role="AI Engineer"):
    with app.app_context():
        job = find_role_job(get_db(), "Machine Learning Engineer" if role == "ML Engineer" else role)
        assert job is not None
        return job


def test_resume_builder_page_uses_role_options_without_job_ids(client):
    response = client.get("/resume-builder/")

    assert response.status_code == 200
    assert b"Target Role" in response.data
    assert b"AI Engineer" in response.data
    assert b"ML Engineer" in response.data
    assert b"Data Scientist" in response.data
    assert b"Software Engineer" in response.data
    assert b"Custom Instructions" in response.data
    assert b'name="job_id"' not in response.data
    assert b"Job ID" not in response.data
    assert "— Company".encode() not in response.data


def test_custom_instructions_are_sent_to_agent_and_reflected_in_generated_text(
    app, client, candidate, monkeypatch
):
    job = _role_job(app)
    captured = {}

    def fake_generate(prompt, **kwargs):
        captured["prompt"] = prompt
        return json.dumps({
            "professional_summary": "A factual summary for review.",
            "highlighted_skills": ["Python"],
            "experience": [],
            "projects": [],
            "keyword_alignment": ["Python"],
        })

    monkeypatch.setattr(resume_agent, "generate", fake_generate)
    response = client.post(
        "/resume-builder/generate",
        data={
            "target_role": "AI Engineer",
            "template": "chronological",
            "custom_instructions": "Add TensorFlow to my skills\nHighlight my verified experience",
        },
    )

    assert response.status_code == 200
    assert b"Tailored Resume Preview" in response.data
    assert b"TensorFlow" in response.data
    assert "TensorFlow" in captured["prompt"]
    assert "Highlight my verified experience" in captured["prompt"]
    assert int(job["job_id"]) > 0


def test_save_preserves_exact_text_and_applies_explicit_user_updates_without_llm(
    app, client, candidate, monkeypatch
):
    job = _role_job(app)
    with app.app_context():
        orchestrator = AgentOrchestrator(get_db(), candidate["user_id"])
        generated = orchestrator.run_resume_builder(
            int(job["job_id"]),
            custom_instructions="Add TensorFlow to my skills",
            target_role="AI Engineer",
        )
        assert "TensorFlow" in generated["resume_text"]

        exact = "  APPROVED RESUME TEXT\n\nUser edit must remain exact.  "
        monkeypatch.setattr(
            resume_agent,
            "generate",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("LLM called during save")),
        )
        saved = orchestrator.save_resume_builder(
            int(job["job_id"]),
            exact,
            custom_instructions="Add TensorFlow to my skills",
            target_role="AI Engineer",
        )

    assert saved["resume_text"] == exact
    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute(
                "SELECT tailored_sections FROM tailored_resumes WHERE user_id = %s AND job_id = %s",
                (candidate["user_id"], job["job_id"]),
            )
            sections = cursor.fetchone()["tailored_sections"]
            if isinstance(sections, str):
                sections = json.loads(sections)
            assert sections["resume_text"] == exact
            cursor.execute(
                "SELECT name FROM skills WHERE user_id = %s",
                (candidate["user_id"],),
            )
            assert "TensorFlow" in [row["name"] for row in cursor.fetchall()]

    reloaded = client.get("/resume-builder/?target_role=AI%20Engineer")
    assert reloaded.status_code == 200
    assert exact.encode() in reloaded.data
