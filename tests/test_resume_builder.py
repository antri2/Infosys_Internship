import json

from database.db import get_db
from services.resume_agent import render_resume_html


def _set_skills(app, user_id, skills):
    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("DELETE FROM skills WHERE user_id = %s", (user_id,))
            for skill in skills:
                cursor.execute(
                    "INSERT INTO skills (user_id, name, category) VALUES (%s, %s, 'other')",
                    (user_id, skill),
                )
        db.commit()


def _job_with_skill(app, skill):
    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute(
                """
                SELECT job_id, title, company, required_skills, preferred_skills
                FROM jobs
                WHERE required_skills LIKE %s
                ORDER BY job_id
                LIMIT 1
                """,
                (f"%{skill}%",),
            )
            return cursor.fetchone()


def _tailored_row(app, user_id, job_id):
    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute(
                "SELECT tailored_sections, fact_check_status FROM tailored_resumes WHERE user_id = %s AND job_id = %s",
                (user_id, job_id),
            )
            return cursor.fetchone()


def test_resume_builder_page_requires_authentication(app):
    response = app.test_client().get("/resume-builder/")

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_resume_builder_page_renders_profile_and_job(app, client, candidate):
    _set_skills(app, candidate["user_id"], ["Python"])
    job = _job_with_skill(app, "Python")

    response = client.get(f"/resume-builder/?job_id={job['job_id']}")

    assert response.status_code == 200
    assert b"Resume Builder" in response.data
    assert b"Current Profile" in response.data
    assert b"Skill Gap Context" in response.data
    assert b"Generate Tailored Resume" in response.data
    assert b"Test University" in response.data


def test_resume_builder_missing_job_is_safe(app, client):
    response = client.get("/resume-builder/?job_id=999999999")

    assert response.status_code == 200
    assert b"Job 999999999 was not found" in response.data


def test_resume_builder_generation_saves_and_renders_source_backed_result(
    app, client, candidate, monkeypatch
):
    _set_skills(app, candidate["user_id"], ["Python", "SQL"])
    job = _job_with_skill(app, "Python")
    captured = {}

    def fake_generate(prompt, **kwargs):
        captured["prompt"] = prompt
        return json.dumps({
            "professional_summary": "A clearer summary could be reviewed here.",
            "highlighted_skills": ["Python", "TensorFlow"],
            "experience": [],
            "projects": [],
            "keyword_alignment": ["Python"],
        })

    monkeypatch.setattr("services.resume_agent.generate", fake_generate)

    response = client.post(
        "/resume-builder/generate",
        data={"job_id": job["job_id"], "template": "chronological"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Tailored Resume Preview" in response.data
    assert b"Loaded saved version" in response.data
    assert b"AI Wording Suggestions" in response.data
    row = _tailored_row(app, candidate["user_id"], job["job_id"])
    assert row is not None
    sections = row["tailored_sections"]
    if isinstance(sections, str):
        sections = json.loads(sections)
    assert "TensorFlow" not in sections["highlighted_skills"]
    assert "Python" in sections["highlighted_skills"]
    assert "Python" in captured["prompt"]


def test_resume_builder_loads_cached_result_without_llm_call(
    app, client, candidate, monkeypatch
):
    _set_skills(app, candidate["user_id"], ["Python"])
    job = _job_with_skill(app, "Python")
    monkeypatch.setattr(
        "services.resume_agent.generate",
        lambda *args, **kwargs: '{"highlighted_skills": ["Python"]}',
    )
    client.post(
        "/resume-builder/generate",
        data={"job_id": job["job_id"]},
        follow_redirects=True,
    )

    monkeypatch.setattr(
        "services.resume_agent.generate",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("LLM should not run for cache")),
    )
    response = client.get(f"/resume-builder/?job_id={job['job_id']}")

    assert response.status_code == 200
    assert b"Loaded saved version" in response.data


def test_resume_builder_fallback_is_used_when_llm_fails(
    app, client, candidate, monkeypatch
):
    _set_skills(app, candidate["user_id"], ["Python"])
    job = _job_with_skill(app, "Python")
    monkeypatch.setattr(
        "services.resume_agent.generate",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("simulated failure")),
    )

    response = client.post(
        "/resume-builder/generate",
        data={"job_id": job["job_id"]},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"AI fallback used" in response.data
    assert b"Tailored Resume Preview" in response.data


def test_resume_builder_user_id_form_value_is_ignored(
    app, client, candidate, monkeypatch
):
    _set_skills(app, candidate["user_id"], ["Python"])
    job = _job_with_skill(app, "Python")
    captured = {}

    def fake_generate(prompt, **kwargs):
        captured["prompt"] = prompt
        return '{"highlighted_skills": ["Python"]}'

    monkeypatch.setattr("services.resume_agent.generate", fake_generate)
    response = client.post(
        "/resume-builder/generate",
        data={"job_id": job["job_id"], "user_id": 999999},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "Python" in captured["prompt"]
    assert candidate["user_id"] != 999999


def test_resume_builder_displays_saved_skill_gap_context(
    app, client, candidate
):
    _set_skills(app, candidate["user_id"], ["Python"])
    job = _job_with_skill(app, "Python")
    missing_skill = next(
        skill.strip()
        for skill in job["required_skills"].split(",")
        if skill.strip() and skill.strip().lower() != "python"
    )
    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO skill_gap_reports
                    (user_id, job_id, critical_gaps, partial_gaps, preferred_gaps,
                     experience_gaps, qualification_gaps, recommendations)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    candidate["user_id"],
                    job["job_id"],
                    json.dumps([{"skill": missing_skill, "why_it_matters": "Required by role"}]),
                    json.dumps([]),
                    json.dumps([]),
                    json.dumps([]),
                    json.dumps([]),
                    json.dumps([]),
                ),
            )
        db.commit()

    response = client.get(f"/resume-builder/?job_id={job['job_id']}")

    assert response.status_code == 200
    assert b"Skill Gap Context" in response.data
    assert b"Missing required" in response.data
    assert missing_skill.encode() in response.data


def test_legacy_resume_html_renderer_escapes_generated_values():
    rendered = render_resume_html({
        "professional_summary": "<script>alert(1)</script>",
        "highlighted_skills": ["<b>Python</b>"],
        "experience": [],
        "projects": [],
        "education": [],
    })

    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered
    assert "<b>Python</b>" not in rendered
