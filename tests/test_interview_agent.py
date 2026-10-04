"""Interview Agent unit, safety, persistence, and route tests.

All model calls are mocked; these tests never require a Groq key.
"""
import json

import pytest

from database.db import get_db
from services import interview_agent


def _candidate():
    return {
        "skills": ["Python", "SQL"],
        "education": [{
            "institution": "Test University",
            "degree": "B.Tech",
            "field": "Computer Science",
            "start_date": "2022",
            "end_date": "2026",
        }],
        "experience": [{
            "title": "Data Analyst Intern",
            "organization": "Acme Analytics",
            "start_date": "2025",
            "end_date": "2025",
            "description": "Used Python and SQL to analyze sample data.",
        }],
        "projects": [{
            "title": "CareerAI",
            "description": "Built a RAG job matching project.",
            "tech_stack": "Python, FAISS",
        }],
        "certifications": [{
            "name": "AWS Certified Developer",
            "issuer": "Test Issuer",
        }],
        "college": "Test University",
        "degree": "B.Tech",
        "passing_year": 2026,
        "cgpa": 8.5,
        "summary": "Interested in AI and software roles.",
        "resume": {"id": 1, "file_type": "pdf", "parse_status": "parsed"},
    }


def _plan(role="AI Engineer"):
    return {
        "target_role": role,
        "priority_topics": ["AI system design"],
        "resume_areas_to_revise": ["CareerAI"],
        "technical_areas_to_revise": ["AI system design"],
        "coding_problem_solving_areas": ["Python"],
        "hr_behavioral_preparation": ["Motivation"],
        "skill_gap_areas": [],
        "recommended_practice_sequence": ["Review concepts"],
        "interview_strategy": ["Use verified examples"],
    }


def _question(category="technical", difficulty="medium", source_id=None, text=None):
    question = {
        "question": text or "Explain the fundamentals relevant to this role.",
        "category": category,
        "difficulty": difficulty,
        "reason": "It is relevant to the selected role.",
        "guidance": "Explain the reasoning clearly.",
        "preparation_area": "role fundamentals",
    }
    if source_id:
        question["source_id"] = source_id
    return question


def _payload(category="technical", difficulty="medium", role="AI Engineer", count=1, question=None, text=None):
    return json.dumps({
        "questions": [question or _question(category, difficulty, text=text)],
        "plan": _plan(role),
    })


def _run(monkeypatch, raw, category="technical", difficulty="medium", role="AI Engineer", count=1, job=None, gap=None):
    monkeypatch.setattr(interview_agent, "generate", lambda *args, **kwargs: raw)
    return interview_agent.generate_interview_content(
        _candidate(), job, gap, role, category, difficulty, count
    )


@pytest.mark.parametrize("category", ["technical", "coding", "hr", "aptitude"])
def test_five_non_resume_question_categories_are_supported(monkeypatch, category):
    result = _run(
        monkeypatch,
        _payload(category=category),
        category=category,
    )

    assert result["used_fallback"] is False
    assert result["questions"][0]["category"] == category
    assert result["questions"][0]["difficulty"] == "medium"
    assert result["plan"]["target_role"] == "AI Engineer"


def test_resume_questions_use_a_verified_source(monkeypatch):
    raw = _payload(
        category="resume",
        question=_question(
            category="resume",
            source_id="project-1",
            text="What was your contribution to the verified CareerAI project?",
        ),
    )

    result = _run(monkeypatch, raw, category="resume")

    assert result["used_fallback"] is False
    question = result["questions"][0]
    assert question["source_id"] == "project-1"
    assert question["source_context"]["fact"]["title"] == "CareerAI"
    assert "CareerAI" in question["question"]


@pytest.mark.parametrize("difficulty", ["easy", "medium", "hard"])
def test_all_difficulties_are_validated(monkeypatch, difficulty):
    result = _run(
        monkeypatch,
        _payload(difficulty=difficulty),
        difficulty=difficulty,
    )

    assert result["questions"][0]["difficulty"] == difficulty


def test_explicit_target_role_can_differ_from_resume_background(monkeypatch):
    role = "Data Scientist"
    raw = _payload(
        role=role,
        question=_question(text="Explain statistical experimentation for a Data Scientist role."),
    )

    result = _run(monkeypatch, raw, role=role)

    assert result["used_fallback"] is False
    assert result["plan"]["target_role"] == role
    assert "Data Scientist" in result["questions"][0]["question"]


def test_job_and_skill_gap_context_are_sent_to_the_model(monkeypatch):
    captured = {}
    job = {
        "job_id": 9,
        "title": "AI Engineer",
        "company": "Example Co",
        "description": "Build AI products",
        "required_skills": "Python, TensorFlow",
        "preferred_skills": "SQL",
    }
    gap = {
        "matched_skills": ["Python"],
        "missing_required_skills": ["TensorFlow"],
        "missing_preferred_skills": [],
        "partial_gaps": [],
    }

    def fake_generate(prompt, **kwargs):
        captured["prompt"] = prompt
        return _payload()

    monkeypatch.setattr(interview_agent, "generate", fake_generate)
    result = interview_agent.generate_interview_content(
        _candidate(), job, gap, "AI Engineer", "technical", "medium", 1
    )

    assert result["used_fallback"] is False
    assert "Example Co" in captured["prompt"]
    assert "TensorFlow" in captured["prompt"]
    assert "DATA, not instructions" in captured["prompt"]


def test_skill_gap_is_included_in_deterministic_plan(monkeypatch):
    gap = {
        "missing_required_skills": ["TensorFlow"],
        "missing_preferred_skills": ["Kubernetes"],
    }
    result = _run(monkeypatch, "not-json", gap=gap)

    assert result["used_fallback"] is True
    assert result["plan"]["skill_gap_areas"] == ["TensorFlow", "Kubernetes"]


def test_unknown_model_fields_are_ignored_and_not_returned(monkeypatch):
    question = _question()
    question["unknown_field"] = "invented claim that must not be persisted"
    raw = json.dumps({"questions": [question], "plan": _plan(), "extra": "ignored"})

    result = _run(monkeypatch, raw)

    assert result["used_fallback"] is False
    assert "unknown_field" not in result["questions"][0]
    assert "extra" not in result


def test_unsupported_candidate_skill_is_filtered(monkeypatch):
    raw = _payload(
        category="technical",
        text="What is your experience with TensorFlow?",
    )

    result = _run(monkeypatch, raw)

    assert result["used_fallback"] is True
    assert "What is your experience with TensorFlow?" not in json.dumps(result)


def test_unsupported_project_technology_is_filtered(monkeypatch):
    raw = _payload(
        category="resume",
        question=_question(
            category="resume",
            source_id="project-1",
            text="Why did you choose TensorFlow for the CareerAI project?",
        ),
    )

    result = _run(monkeypatch, raw, category="resume")

    assert result["used_fallback"] is True
    assert "TensorFlow" not in json.dumps(result["questions"])


def test_invented_experience_is_filtered(monkeypatch):
    raw = _payload(
        category="resume",
        question=_question(
            category="resume",
            source_id="experience-1",
            text="What did you do during your internship at Google?",
        ),
    )

    result = _run(monkeypatch, raw, category="resume")

    assert result["used_fallback"] is True
    assert "Google" not in json.dumps(result["questions"])


def test_invented_metric_or_achievement_is_filtered(monkeypatch):
    raw = _payload(
        category="resume",
        question=_question(
            category="resume",
            source_id="project-1",
            text="How many users did the CareerAI project achieve?",
        ),
    )

    result = _run(monkeypatch, raw, category="resume")

    assert result["used_fallback"] is True
    assert "How many users" not in json.dumps(result["questions"])


def test_empty_output_uses_fallback(monkeypatch):
    result = _run(monkeypatch, "")

    assert result["used_fallback"] is True
    assert result["questions"]


def test_malformed_json_uses_fallback(monkeypatch):
    result = _run(monkeypatch, "{ definitely not json")

    assert result["used_fallback"] is True
    assert result["validation_status"] == "fallback"


def test_invalid_model_category_uses_fallback(monkeypatch):
    raw = _payload(question=_question(category="hr"))
    result = _run(monkeypatch, raw, category="technical")

    assert result["used_fallback"] is True
    assert all(item["category"] == "technical" for item in result["questions"])


def test_invalid_model_difficulty_uses_fallback(monkeypatch):
    raw = _payload(question=_question(difficulty="easy"))
    result = _run(monkeypatch, raw, difficulty="hard")

    assert result["used_fallback"] is True
    assert all(item["difficulty"] == "hard" for item in result["questions"])


def test_missing_target_role_is_rejected_before_llm(monkeypatch):
    called = []
    monkeypatch.setattr(interview_agent, "generate", lambda *args, **kwargs: called.append(True))

    with pytest.raises(ValueError, match="Target role"):
        interview_agent.generate_interview_content(
            _candidate(), None, None, "", "technical", "medium", 1
        )
    assert called == []


def test_invalid_generation_inputs_are_rejected(monkeypatch):
    monkeypatch.setattr(interview_agent, "generate", lambda *args, **kwargs: "{}")
    with pytest.raises(ValueError):
        interview_agent.generate_interview_content(_candidate(), None, None, "AI Engineer", "bad", "medium", 1)
    with pytest.raises(ValueError):
        interview_agent.generate_interview_content(_candidate(), None, None, "AI Engineer", "technical", "impossible", 1)
    with pytest.raises(ValueError):
        interview_agent.generate_interview_content(_candidate(), None, None, "AI Engineer", "technical", "medium", 0)


def test_interview_page_requires_authentication(app):
    response = app.test_client().get("/interview/")

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_interview_page_renders_all_categories_and_controls(client):
    response = client.get("/interview/")

    assert response.status_code == 200
    assert b"Interview Preparation" in response.data
    assert b"Start Practice" in response.data
    assert b"Start Mock Interview" in response.data
    for label in (b"Technical", b"HR / Behavioral", b"Coding", b"Project-Based",
                  b"Role-Specific", b"Mixed Interview"):
        assert label in response.data
    for level in (b"Beginner", b"Intermediate", b"Advanced"):
        assert level in response.data
    for option in (b">5<", b">10<", b">15<", b">20<"):
        assert option in response.data


def test_interview_page_exposes_target_sources_and_optional_fields(client):
    response = client.get("/interview/")

    assert response.status_code == 200
    assert b"Select a Role" in response.data
    assert b"Custom Job" in response.data
    assert b"Focus Areas" in response.data
    assert b"Company Name (Optional)" in response.data
    assert b"Job Description (Optional)" in response.data
    assert b"Paste job description here..." in response.data


def test_interview_page_does_not_expose_a_random_job_resolver(client):
    """A bare role must never become a stored job on the page."""
    response = client.get("/interview/?target_role=AI%20Engineer")

    assert response.status_code == 200
    assert b"Exact Opportunity selected" not in response.data
    assert b'data-explicit-job-id=""' in response.data


def _first_job(app):
    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT job_id, title, company FROM jobs ORDER BY job_id LIMIT 1")
            return cursor.fetchone()


def test_generation_endpoint_saves_questions_and_plan_and_reloads(
    app, client, candidate, monkeypatch
):
    job = _first_job(app)
    captured = {}

    def fake_generate(prompt, **kwargs):
        captured["prompt"] = prompt
        return json.dumps({
            "questions": [_question(), _question(text="Explain a second role-relevant concept.")],
            "plan": _plan(),
        })

    monkeypatch.setattr(interview_agent, "generate", fake_generate)
    response = client.post(
        "/interview/generate",
        json={
            "target_role": "AI Engineer",
            "job_id": job["job_id"],
            "category": "technical",
            "difficulty": "medium",
            "count": 2,
            "user_id": 999999,
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert len(payload["questions"]) == 2
    assert payload["plan"]["target_role"] == "AI Engineer"
    assert candidate["user_id"] != 999999

    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) AS count FROM interview_questions WHERE user_id = %s",
                (candidate["user_id"],),
            )
            assert cursor.fetchone()["count"] >= 2
            cursor.execute(
                "SELECT job_id, plan FROM interview_prep_plans WHERE user_id = %s ORDER BY id DESC LIMIT 1",
                (candidate["user_id"],),
            )
            saved_plan = cursor.fetchone()
    assert saved_plan["job_id"] == job["job_id"]
    assert "target_role" in (saved_plan["plan"] if isinstance(saved_plan["plan"], dict) else json.loads(saved_plan["plan"]))

    reloaded = client.get("/interview/")
    assert reloaded.status_code == 200
    assert b"Recent Preparation" in reloaded.data
    assert b"role-relevant" in reloaded.data


def test_generation_without_job_persists_custom_role_plan(app, client, candidate, monkeypatch):
    monkeypatch.setattr(
        interview_agent,
        "generate",
        lambda *args, **kwargs: _payload(
            role="Backend Engineer",
            question=_question(text="Explain API design."),
        ),
    )
    response = client.post(
        "/interview/generate",
        json={
            "target_role": "Backend Engineer",
            "category": "technical",
            "difficulty": "medium",
            "count": 1,
        },
    )

    assert response.status_code == 200
    assert response.get_json()["target_role"] == "Backend Engineer"
    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute(
                "SELECT job_id, plan FROM interview_prep_plans WHERE user_id = %s AND job_id IS NULL",
                (candidate["user_id"],),
            )
            saved = cursor.fetchone()
    assert saved is not None
    assert saved["job_id"] is None


def test_generation_endpoint_rejects_invalid_inputs_and_missing_job(client):
    missing_role = client.post("/interview/generate", json={"category": "technical", "difficulty": "easy", "count": 1})
    assert missing_role.status_code == 400

    invalid_category = client.post(
        "/interview/generate",
        json={"target_role": "AI Engineer", "category": "unknown", "difficulty": "easy", "count": 1},
    )
    assert invalid_category.status_code == 400

    invalid_difficulty = client.post(
        "/interview/generate",
        json={"target_role": "AI Engineer", "category": "technical", "difficulty": "unknown", "count": 1},
    )
    assert invalid_difficulty.status_code == 400

    invalid_count = client.post(
        "/interview/generate",
        json={"target_role": "AI Engineer", "category": "technical", "difficulty": "easy", "count": 99},
    )
    assert invalid_count.status_code == 400

    missing_job = client.post(
        "/interview/generate",
        json={"target_role": "AI Engineer", "job_id": 999999999, "category": "technical", "difficulty": "easy", "count": 1},
    )
    assert missing_job.status_code == 404


def test_saved_generated_content_is_html_escaped(client, monkeypatch):
    def fake_generate(*args, **kwargs):
        return json.dumps({
            "questions": [_question(difficulty="easy", text="<script>alert('unsafe')</script>")],
            "plan": _plan(),
        })

    monkeypatch.setattr(interview_agent, "generate", fake_generate)
    response = client.post(
        "/interview/generate",
        json={
            "target_role": "AI Engineer",
            "category": "technical",
            "difficulty": "easy",
            "count": 1,
        },
    )
    assert response.status_code == 200
    page = client.get("/interview/")
    assert b"<script>alert('unsafe')</script>" not in page.data
    assert b"&lt;script&gt;" in page.data
    assert b"alert(" in page.data


def test_generation_endpoint_uses_fallback_when_llm_fails(client, monkeypatch):
    def broken_generate(*args, **kwargs):
        raise RuntimeError("simulated LLM outage")

    monkeypatch.setattr(interview_agent, "generate", broken_generate)
    response = client.post(
        "/interview/generate",
        json={
            "target_role": "AI Engineer",
            "category": "technical",
            "difficulty": "easy",
            "count": 2,
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["used_fallback"] is True
    assert len(payload["questions"]) == 2


def test_generation_endpoint_enforces_authentication(app):
    response = app.test_client().post(
        "/interview/generate",
        json={"target_role": "AI Engineer", "category": "technical", "difficulty": "easy", "count": 1},
    )

    assert response.status_code == 401
    assert response.is_json


# ---------------------------------------------------------------------------
# Interview Preparation scenarios (role only, custom JD, focus, practice,
# mock evaluation, tip, and explicit Opportunity/Application context).
# ---------------------------------------------------------------------------


def _generate(client, monkeypatch, raw=None, **overrides):
    """Post a generation request.

    Pass ``raw=None`` (the default) to have this helper install a
    deterministic model reply, or ``raw=False`` when the caller has already
    installed its own ``generate`` mock, for example to capture the prompt.
    """
    category = overrides.pop("category", "technical")
    difficulty = overrides.pop("difficulty", "easy")
    if raw is None:
        raw = _payload(
            category=category,
            difficulty=difficulty,
            role=overrides.get("target_role", "AI Engineer"),
            question=_question(category=category, difficulty=difficulty),
        )
    if raw is not False:
        monkeypatch.setattr(interview_agent, "generate", lambda *a, **k: raw)
    body = {"category": category, "difficulty": difficulty, "count": 1}
    body.update(overrides)
    return client.post("/interview/generate", json=body)


def test_role_only_ai_engineer_has_no_random_job(client, monkeypatch):
    captured = {}

    def fake_generate(prompt, **kwargs):
        captured["prompt"] = prompt
        return _payload()

    monkeypatch.setattr(interview_agent, "generate", fake_generate)
    response = _generate(client, monkeypatch, raw=False, target_role="AI Engineer")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["context_mode"] == "role"
    assert payload["job"] is None
    assert "job_id" not in payload
    assert payload["target_role"] == "AI Engineer"
    # A role-only request must not invent a stored posting.
    assert "SELECTED JOB DATA" in captured["prompt"]
    assert '"company": null' in captured["prompt"] or '"company": ""' in captured["prompt"]


def test_role_only_software_engineer_differs_from_ai_engineer(client, monkeypatch):
    monkeypatch.setattr(interview_agent, "generate", lambda *a, **k: "not-json")
    response = _generate(
        client, monkeypatch, raw=False, target_role="Software Engineer", category="technical"
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["target_role"] == "Software Engineer"
    assert payload["context_mode"] == "role"
    assert payload["job"] is None
    question_text = json.dumps(payload["questions"])
    assert "Software Engineer" in question_text
    assert "retrieval" not in question_text.casefold()


def test_role_with_company_and_jd_uses_the_pasted_jd(client, monkeypatch):
    captured = {}

    def fake_generate(prompt, **kwargs):
        captured["prompt"] = prompt
        return _payload()

    monkeypatch.setattr(interview_agent, "generate", fake_generate)
    response = _generate(
        client,
        monkeypatch,
        raw=False,
        target_role="AI Engineer",
        company="ABC Technologies",
        job_description="We are looking for an AI Engineer with Python, PyTorch, Docker, AWS, RAG.",
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["context_mode"] == "jd"
    assert payload["company"] == "ABC Technologies"
    assert payload["job"] is None
    assert "PyTorch" in captured["prompt"]
    assert "Docker" in captured["prompt"]


def test_role_with_jd_and_no_company_still_uses_the_jd(client, monkeypatch):
    captured = {}

    def fake_generate(prompt, **kwargs):
        captured["prompt"] = prompt
        return _payload()

    monkeypatch.setattr(interview_agent, "generate", fake_generate)
    response = _generate(
        client,
        monkeypatch,
        raw=False,
        target_role="AI Engineer",
        job_description="Required skills: Python, PyTorch, Docker, AWS, RAG.",
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["context_mode"] == "jd"
    assert payload["company"] == ""
    assert payload["job"] is None
    assert "PyTorch" in captured["prompt"]


def test_focus_areas_are_passed_to_the_interview_agent(client, monkeypatch):
    captured = {}

    def fake_generate(prompt, **kwargs):
        captured["prompt"] = prompt
        return _payload()

    monkeypatch.setattr(interview_agent, "generate", fake_generate)
    response = _generate(
        client,
        monkeypatch,
        raw=False,
        target_role="AI Engineer",
        focus_areas="Python and Machine Learning",
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["focus_areas"] == "Python and Machine Learning"
    assert "Python and Machine Learning" in captured["prompt"]


def test_practice_mode_questions_carry_answer_and_how_to_answer(client, monkeypatch):
    response = _generate(client, monkeypatch, raw=False, target_role="AI Engineer", category="technical")

    assert response.status_code == 200
    question = response.get_json()["questions"][0]
    assert question["answer"]
    assert question["how_to_answer"]


def test_mock_mode_answer_is_evaluated_with_structured_feedback(client, monkeypatch):
    def fake_generate(prompt, **kwargs):
        if "interview coach" in prompt:
            return json.dumps({
                "did_well": ["You defined the concept clearly."],
                "improve": ["Add a concrete example."],
                "suggested_answer": "A short, structured interview-style answer.",
                "how_to_improve": "1. Define. 2. Example. 3. Use case.",
                "score": 72,
            })
        return _payload()

    monkeypatch.setattr(interview_agent, "generate", fake_generate)
    response = client.post(
        "/interview/evaluate",
        json={
            "target_role": "AI Engineer",
            "category": "technical",
            "question": "Explain supervised versus unsupervised learning.",
            "answer": "Supervised learning uses labelled data, unsupervised finds structure.",
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["did_well"] == ["You defined the concept clearly."]
    assert payload["improve"] == ["Add a concrete example."]
    assert payload["suggested_answer"]
    assert payload["score"] == 72


def test_tip_is_short_and_does_not_reveal_the_full_answer(client, monkeypatch):
    monkeypatch.setattr(
        interview_agent,
        "generate",
        lambda *a, **k: json.dumps({"tip": "Think about how labelled data changes the learning process."}),
    )
    response = client.post(
        "/interview/tip",
        json={
            "target_role": "AI Engineer",
            "category": "technical",
            "question": "How would you handle missing values in a machine learning dataset?",
        },
    )

    assert response.status_code == 200
    tip = response.get_json()["tip"]
    assert tip
    assert len(tip) <= interview_agent.MAX_TIP_LENGTH


def test_tip_uses_a_safe_hint_when_the_model_fails(client, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("simulated LLM outage")

    monkeypatch.setattr(interview_agent, "generate", broken)
    response = client.post(
        "/interview/tip",
        json={"target_role": "AI Engineer", "question": "Explain cross-validation."},
    )

    assert response.status_code == 200
    assert response.get_json()["tip"]


def test_opportunity_context_uses_the_exact_selected_job(app, client, monkeypatch):
    job = _first_job(app)
    monkeypatch.setattr(interview_agent, "generate", lambda *a, **k: _payload())
    response = client.post(
        "/interview/generate",
        json={
            "target_role": "AI Engineer",
            "job_id": job["job_id"],
            "category": "technical",
            "difficulty": "easy",
            "count": 1,
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["context_mode"] == "job"
    assert payload["job"]["job_id"] == job["job_id"]
    assert payload["job"]["title"] == job["title"]


def test_opportunity_link_renders_exact_job_on_the_page(client):
    job = _first_job(client.application)
    page = client.get(f"/interview/?job_id={job['job_id']}&target_source=custom")

    assert page.status_code == 200
    assert b"Exact Opportunity selected" in page.data
    assert job["title"].encode() in page.data
    assert f'data-explicit-job-id="{job["job_id"]}"'.encode() in page.data


def test_mock_summary_is_a_practice_assessment_only(client, monkeypatch):
    monkeypatch.setattr(interview_agent, "generate", lambda *a, **k: _payload())
    response = client.post(
        "/interview/summary",
        json={
            "target_role": "AI Engineer",
            "results": [
                {"preparation_area": "model evaluation", "answer": "some text", "score": 80},
                {"preparation_area": "RAG basics", "answer": "", "skipped": True},
            ],
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["questions_attempted"] == 1
    assert payload["questions_skipped"] == 1
    assert "model evaluation" in payload["topics_covered"]
    assert "RAG basics" in payload["topics_to_improve"]
    assert payload["practice_performance"]
    # A practice assessment must never be phrased as a hiring outcome.
    body = json.dumps(payload).casefold()
    for forbidden in ("hired", "hiring probability", "probability of getting", "job selection"):
        assert forbidden not in body


def test_application_tracker_interview_link_targets_the_exact_job(app, client, candidate):
    job = _first_job(app)
    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO applications (user_id, job_id, status)
                VALUES (%s, %s, 'interview')
                ON DUPLICATE KEY UPDATE status = 'interview'
                """,
                (candidate["user_id"], job["job_id"]),
            )
        db.commit()

    page = client.get("/applications/?status=interview")

    assert page.status_code == 200
    assert b"Prepare for Interview" in page.data
    assert f"job_id={job['job_id']}".encode() in page.data


# ---------------------------------------------------------------------------
# Mock Interview persistence, history, and the Skip flow.
# ---------------------------------------------------------------------------


def _generate_for_mock(client, monkeypatch, count=2, category="technical"):
    raw = json.dumps({
        "questions": [
            _question(category=category, difficulty="medium", text=f"Explain concept number {n}.")
            for n in range(1, count + 1)
        ],
        "plan": _plan(),
    })
    monkeypatch.setattr(interview_agent, "generate", lambda *a, **k: raw)
    return client.post(
        "/interview/generate",
        json={"target_role": "AI Engineer", "category": category,
              "difficulty": "medium", "count": count},
    ).get_json()


def test_generation_returns_question_ids_aligned_with_questions(client, monkeypatch):
    payload = _generate_for_mock(client, monkeypatch, count=3)

    assert len(payload["question_ids"]) == len(payload["questions"])
    assert all(isinstance(value, int) for value in payload["question_ids"])


def test_mock_session_persists_answers_and_skips(app, client, candidate, monkeypatch):
    payload = _generate_for_mock(client, monkeypatch, count=2)
    first_id, second_id = payload["question_ids"]

    started = client.post("/interview/mock/start", json={"job_id": None})
    assert started.status_code == 200
    session_id = started.get_json()["session_id"]

    answered = client.post(
        "/interview/mock/answer",
        json={
            "session_id": session_id, "question_id": first_id,
            "answer": "A structured answer about the concept.",
            "feedback": {"did_well": ["Clear definition."], "improve": ["Add an example."],
                         "suggested_answer": "A better answer.", "how_to_improve": "Define, exemplify."},
            "score": 76,
        },
    )
    assert answered.status_code == 200
    assert answered.get_json()["skipped"] is False

    skipped = client.post(
        "/interview/mock/answer",
        json={"session_id": session_id, "question_id": second_id, "answer": ""},
    )
    assert skipped.status_code == 200
    assert skipped.get_json()["skipped"] is True

    # An unfinished session must not appear in history yet.
    in_progress = client.get("/interview/mock/history").get_json()
    assert all(item["session_id"] != session_id for item in in_progress["sessions"])

    finished = client.post("/interview/mock/finish", json={"session_id": session_id})
    assert finished.status_code == 200

    history = client.get("/interview/mock/history").get_json()
    row = next(item for item in history["sessions"] if item["session_id"] == session_id)
    assert row["total_questions"] == 2
    assert row["answered"] == 1
    assert row["skipped"] == 1
    assert row["role"] == "AI Engineer"
    assert row["overall_result"]
    assert row["started_at"] is not None


def test_mock_history_detail_returns_question_by_question_review(client, monkeypatch):
    payload = _generate_for_mock(client, monkeypatch, count=2)
    first_id, second_id = payload["question_ids"]
    session_id = client.post("/interview/mock/start", json={"job_id": None}).get_json()["session_id"]

    client.post("/interview/mock/answer", json={
        "session_id": session_id, "question_id": first_id,
        "answer": "My answer text.", "score": 81,
        "feedback": {"did_well": ["Good structure."], "improve": ["Be more specific."],
                     "suggested_answer": "Stronger answer.", "how_to_improve": "Use a concrete example."},
    })
    client.post("/interview/mock/answer", json={
        "session_id": session_id, "question_id": second_id, "answer": "",
    })
    client.post("/interview/mock/finish", json={"session_id": session_id})

    detail = client.get(f"/interview/mock/history/{session_id}").get_json()
    assert detail["success"] is True
    session = detail["session"]
    assert session["role"] == "AI Engineer"
    assert len(session["items"]) == 2

    answered_item, skipped_item = session["items"]
    assert answered_item["skipped"] is False
    assert answered_item["student_answer"] == "My answer text."
    assert answered_item["did_well"] == ["Good structure."]
    assert answered_item["improve"] == ["Be more specific."]
    assert answered_item["how_to_improve"] == "Use a concrete example."
    assert answered_item["better_answer"] == "Stronger answer."

    assert skipped_item["skipped"] is True
    assert skipped_item["student_answer"] == ""
    # A skipped question still offers the stored practice answer so the user
    # can see how they could have answered it.
    assert skipped_item["suggested_answer"]


def test_mock_history_is_scoped_to_the_current_user(app, client, candidate, monkeypatch):
    payload = _generate_for_mock(client, monkeypatch, count=1)
    session_id = client.post("/interview/mock/start", json={"job_id": None}).get_json()["session_id"]
    client.post("/interview/mock/answer", json={
        "session_id": session_id, "question_id": payload["question_ids"][0],
        "answer": "Answer", "score": 70,
        "feedback": {"did_well": [], "improve": [], "suggested_answer": "", "how_to_improve": ""},
    })
    client.post("/interview/mock/finish", json={"session_id": session_id})

    other = app.test_client()
    with other.session_transaction() as flask_session:
        flask_session["user_id"] = candidate["user_id"] + 1000

    assert other.get("/interview/mock/history").get_json()["sessions"] == []
    assert other.get(f"/interview/mock/history/{session_id}").status_code == 404


def test_mock_answer_rejects_a_session_owned_by_someone_else(app, client, candidate):
    response = client.post(
        "/interview/mock/answer",
        json={"session_id": 999999999, "question_id": 1, "answer": "hello"},
    )
    assert response.status_code == 404


def test_summary_pairs_each_area_with_its_own_score():
    """A skipped question must not shift scores onto the wrong areas."""
    summary = interview_agent.build_mock_summary("AI Engineer", [
        {"preparation_area": "weak area", "answer": "text", "score": 20},
        {"preparation_area": "skipped area", "answer": "", "skipped": True},
        {"preparation_area": "strong area", "answer": "text", "score": 90},
    ])

    assert summary["areas_performed_well"] == ["strong area"]
    # The skipped area belongs with the areas to improve, and the weak answered
    # area must not be credited with the strong area's score.
    assert set(summary["topics_to_improve"]) == {"weak area", "skipped area"}


def test_interview_page_keeps_previous_next_for_practice_session(client):
    page = client.get("/interview/")

    assert page.status_code == 200
    # Practice Session navigation still exists...
    assert b'id="prev-question"' in page.data
    assert b'id="next-question"' in page.data
    assert b"Previous Question" in page.data
    assert b"Next Question" in page.data
    # ...but it is scoped to the practice-nav container, which starts hidden
    # because no session is running yet.
    assert b'id="practice-nav"' in page.data
    assert b'id="practice-nav" style="margin-top:20px;" hidden' in page.data


def test_mock_answer_area_has_only_submit_tip_and_skip(client):
    page = client.get("/interview/").data.decode("utf-8")
    start = page.index('id="mock-answer-area"')
    end = page.index('id="feedback-area"')
    controls = page[start:end]
    for label in ("Submit Answer", ">Tip<", ">Skip<"):
        assert label in controls
    assert "prev-question" not in controls
    assert "next-question" not in controls


def test_interview_page_history_sections_are_hidden_by_default(client):
    page = client.get("/interview/")

    assert page.status_code == 200
    for panel in (b'id="saved-panel"', b'id="recent-panel"', b'id="history-panel"'):
        assert panel in page.data
    # Each panel must open in the hidden state.
    assert page.data.count(b'hidden style="margin-top:18px;"') == 3
    for toggle in (b'id="toggle-saved"', b'id="toggle-recent"', b'id="toggle-history"'):
        assert b'aria-expanded="false"' in page.data
        assert toggle in page.data


def test_interview_page_has_no_emoji(client):
    page = client.get("/interview/")
    text = page.data.decode("utf-8")

    # Every pictograph/emoji code point that the previous UI used.
    emoji_code_points = [
        0x1F4A1,  # light bulb
        0x1F3AF,  # direct hit
        0x1F4A1,
        0x2713,   # check mark
        0x25B3,   # white up-pointing triangle
        0x1F4BB,  # laptop
        0x1F4C1,  # file folder
        0x1F3AF,  # dart
        0x1F5C2,  # cards
        0x1F9E9,  # puzzle piece
        0x1F91D,  # handshake
    ]
    for code in emoji_code_points:
        assert chr(code) not in text, f"emoji still present: U+{code:04X}"
    for entity in ("&#128161;", "&#10003;", "&#9651;", "&#127919;", "&#8592;", "&#8594;"):
        assert entity not in text
