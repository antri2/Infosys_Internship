from database.db import get_db


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


def test_ai_summary_endpoint_success_uses_grounded_m2_context(
    app, client, candidate, monkeypatch
):
    _set_skills(app, candidate["user_id"], ["JavaScript", "React"])
    job = _job_with_skill(app, "JavaScript")
    captured = {}

    def fake_generate(prompt, **kwargs):
        captured["prompt"] = prompt
        captured["kwargs"] = kwargs
        return '{"matched_skills": ["JavaScript", "React"]}'

    monkeypatch.setattr("services.job_summary_agent.generate", fake_generate)

    response = client.post(f"/opportunities/{job['job_id']}/ai-summary")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["used_fallback"] is False
    assert payload["summary"].startswith("Your JavaScript skills match several requirements for this role.")
    assert "React" not in payload["summary"].split("Missing required skills", 1)[0]
    assert job["title"] in captured["prompt"]
    assert "JavaScript" in captured["prompt"]
    assert captured["kwargs"]["max_tokens"] == 140


def test_ai_summary_missing_job_returns_json_404(client):
    response = client.post("/opportunities/999999999/ai-summary")

    assert response.status_code == 404
    assert response.is_json
    assert response.get_json() == {
        "success": False,
        "error": "Job 999999999 was not found.",
    }


def test_ai_summary_llm_failure_uses_deterministic_fallback(
    app, client, candidate, monkeypatch
):
    _set_skills(app, candidate["user_id"], ["Python", "SQL"])
    job = _job_with_skill(app, "Python")

    def broken_generate(*args, **kwargs):
        raise RuntimeError("simulated LLM failure")

    monkeypatch.setattr("services.job_summary_agent.generate", broken_generate)

    response = client.post(f"/opportunities/{job['job_id']}/ai-summary")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["used_fallback"] is True
    assert payload["summary"]
    assert "AWS Certified Developer" not in payload["summary"]
    assert len(payload["summary"].split()) < 60


def test_ai_summary_filters_unsupported_skill_suggestions(
    app, client, candidate, monkeypatch
):
    _set_skills(app, candidate["user_id"], ["JavaScript"])
    job = _job_with_skill(app, "JavaScript")
    monkeypatch.setattr(
        "services.job_summary_agent.generate",
        lambda *args, **kwargs: '{"matched_skills": ["TensorFlow", "JavaScript"]}',
    )

    response = client.post(f"/opportunities/{job['job_id']}/ai-summary")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["used_fallback"] is False
    assert "TensorFlow" not in payload["summary"]
    assert "JavaScript" in payload["summary"]


def test_ai_summary_rejects_probability_claim_and_falls_back(
    app, client, candidate, monkeypatch
):
    _set_skills(app, candidate["user_id"], ["Python"])
    job = _job_with_skill(app, "Python")
    monkeypatch.setattr(
        "services.job_summary_agent.generate",
        lambda *args, **kwargs: "You have a 90% chance of getting this job.",
    )

    response = client.post(f"/opportunities/{job['job_id']}/ai-summary")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["used_fallback"] is True
    assert "chance" not in payload["summary"].lower()
    assert "probability" not in payload["summary"].lower()


def test_opportunities_page_includes_get_ai_summary_control(client):
    response = client.get("/opportunities/")

    assert response.status_code == 200
    assert b"Get AI Summary" in response.data
    assert b"ai-summary-" in response.data
