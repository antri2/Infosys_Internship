import json

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


def _model_gap_report(critical=None, preferred=None, partial=None):
    return json.dumps({
        "critical_gaps": critical or [],
        "partial_gaps": partial or [],
        "preferred_gaps": preferred or [],
        "experience_gaps": [],
        "qualification_gaps": [],
        "recommendations": [{"action": "Practice the highest-priority skill.", "addresses": "priority"}],
    })


def test_skill_gap_page_requires_authentication(app):
    client = app.test_client()

    response = client.get("/skill-gap/")

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_skill_gap_page_renders_for_authenticated_user(client):
    response = client.get("/skill-gap/")

    assert response.status_code == 200
    assert b"Skill Gap Analysis" in response.data
    assert b"Target Role" in response.data
    assert b"Company Name" in response.data
    assert b"Job Description" in response.data
    assert b"Analyze Skill Gap" in response.data
    assert b'name="job_id"' not in response.data
    assert b"Job ID" not in response.data


def test_skill_gap_analysis_success_and_grounding(
    app, client, candidate, monkeypatch
):
    _set_skills(app, candidate["user_id"], ["JS"])
    job = _job_with_skill(app, "JavaScript")
    captured = {}

    def fake_generate(prompt, **kwargs):
        captured["prompt"] = prompt
        return _model_gap_report(
            critical=[{"skill": "TensorFlow", "why_it_matters": "invented claim"}],
            partial=[{"skill": "React", "why_it_matters": "related evidence"}],
        )

    monkeypatch.setattr("services.skill_gap_service.generate", fake_generate)

    response = client.post(
        "/skill-gap/analyze",
        json={"job_id": job["job_id"], "user_id": 999999},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["analysis"]["mode"] == "job"
    assert payload["job"]["job_id"] == job["job_id"]
    report = payload["report"]
    assert report["used_fallback"] is False
    assert "JavaScript" in report["matched_skills"]
    assert "TensorFlow" not in json.dumps(report)
    assert report["missing_required_skills"] is not None
    assert report["missing_preferred_skills"] is not None
    assert "JavaScript" in captured["prompt"]
    assert candidate["user_id"] != 999999


def test_skill_gap_role_only_ai_engineer_does_not_select_a_dataset_job(
    app, client, candidate, monkeypatch
):
    _set_skills(app, candidate["user_id"], ["Python", "SQL"])
    captured = {}

    def fake_generate(prompt, **kwargs):
        captured["prompt"] = prompt
        return _model_gap_report(
            critical=[{"skill": "statistics", "why_it_matters": "Important for model evaluation."}],
            preferred=[{"skill": "RAG", "why_it_matters": "Useful for retrieval systems."}],
        )

    monkeypatch.setattr("services.skill_gap_service.generate", fake_generate)
    response = client.post("/skill-gap/analyze", json={"target_role": "AI Engineer"})

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["analysis"]["mode"] == "role"
    assert payload["job"] is None
    assert "job_id" not in payload
    assert "Role-level advisory requirements" in captured["prompt"]
    assert "statistics" in payload["report"]["missing_required_skills"]
    assert "Python" in payload["report"]["matched_skills"]


def test_skill_gap_role_only_software_engineer_does_not_select_a_dataset_job(
    client, monkeypatch
):
    monkeypatch.setattr(
        "services.skill_gap_service.generate",
        lambda *args, **kwargs: _model_gap_report(
            critical=[{"skill": "testing", "why_it_matters": "Needed for reliable software delivery."}]
        ),
    )
    response = client.post("/skill-gap/analyze", json={"target_role": "Software Engineer"})

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["analysis"]["mode"] == "role"
    assert payload["job"] is None
    assert "testing" in payload["report"]["missing_required_skills"]


def test_skill_gap_prioritizes_pasted_job_description(
    app, client, candidate, monkeypatch
):
    _set_skills(app, candidate["user_id"], ["Python"])
    captured = {}

    def fake_generate(prompt, **kwargs):
        captured["prompt"] = prompt
        return _model_gap_report(
            critical=[{"skill": "PyTorch", "why_it_matters": "The JD asks for PyTorch experience."}],
            preferred=[{"skill": "SQL", "why_it_matters": "The JD lists SQL as preferred."}],
        )

    monkeypatch.setattr("services.skill_gap_service.generate", fake_generate)
    response = client.post(
        "/skill-gap/analyze",
        json={
            "target_role": "AI Engineer",
            "company": "ABC Technologies",
            "job_description": (
                "AI Engineer role. Required skills: Python, PyTorch, Docker, AWS, RAG. "
                "Preferred skills: SQL. Build production AI features."
            ),
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["analysis"]["mode"] == "jd"
    assert payload["analysis"]["source"] == "provided_job_description"
    assert payload["job"] is None
    assert "pytorch" in [skill.casefold() for skill in payload["report"]["missing_required_skills"]]
    assert "sql" in [skill.casefold() for skill in payload["report"]["missing_preferred_skills"]]
    assert "python" in [skill.casefold() for skill in payload["report"]["matched_skills"]]
    assert "ABC Technologies" in captured["prompt"]
    assert "Required skills: Python, PyTorch, Docker, AWS, RAG" in captured["prompt"]


def test_skill_gap_jd_without_company_still_uses_jd(
    app, client, candidate, monkeypatch
):
    _set_skills(app, candidate["user_id"], ["Python"])
    captured = {}

    def fake_generate(prompt, **kwargs):
        captured["prompt"] = prompt
        return _model_gap_report(
            critical=[{"skill": "Docker", "why_it_matters": "The JD asks for Docker."}]
        )

    monkeypatch.setattr("services.skill_gap_service.generate", fake_generate)
    response = client.post(
        "/skill-gap/analyze",
        json={
            "target_role": "AI Engineer",
            "job_description": "Required skills: Python, Docker, AWS.",
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["analysis"]["mode"] == "jd"
    assert payload["analysis"]["company"] == ""
    assert "docker" in [skill.casefold() for skill in payload["report"]["missing_required_skills"]]
    assert "Docker" in captured["prompt"]


def test_skill_gap_empty_jd_falls_back_to_role_level_analysis(
    client, monkeypatch
):
    monkeypatch.setattr(
        "services.skill_gap_service.generate",
        lambda *args, **kwargs: _model_gap_report(
            critical=[{"skill": "Python", "why_it_matters": "Role foundation."}]
        ),
    )
    response = client.post(
        "/skill-gap/analyze",
        json={"target_role": "AI Engineer", "company": "ABC", "job_description": ""},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["analysis"]["mode"] == "role"
    assert payload["analysis"]["company"] == "ABC"
    assert payload["job"] is None
    assert "Python" in payload["report"]["missing_required_skills"]


def test_skill_gap_missing_job_returns_json_404(client):
    response = client.post("/skill-gap/analyze", json={"job_id": 999999999})

    assert response.status_code == 404
    assert response.is_json
    assert response.get_json()["success"] is False


def test_skill_gap_invalid_job_id_returns_json_400(client):
    response = client.post("/skill-gap/analyze", json={"job_id": "not-a-number"})

    assert response.status_code == 400
    assert response.is_json
    assert "valid job_id" in response.get_json()["error"]


def test_skill_gap_llm_failure_uses_alias_consistent_fallback(
    app, client, candidate, monkeypatch
):
    _set_skills(app, candidate["user_id"], ["JS"])
    job = _job_with_skill(app, "JavaScript")

    def broken_generate(*args, **kwargs):
        raise RuntimeError("simulated LLM failure")

    monkeypatch.setattr("services.skill_gap_service.generate", broken_generate)

    response = client.post("/skill-gap/analyze", json={"job_id": job["job_id"]})

    assert response.status_code == 200
    report = response.get_json()["report"]
    assert report["used_fallback"] is True
    assert "JavaScript" in report["matched_skills"]
    assert report["missing_required_skills"] is not None
    assert report["missing_preferred_skills"] is not None
    assert report["recommendations"]


def test_skill_gap_analysis_requires_authentication(app):
    client = app.test_client()

    response = client.post("/skill-gap/analyze", json={"job_id": 1})

    assert response.status_code == 401
    assert response.is_json
