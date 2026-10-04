"""Focused natural-language Career Assistant guidance tests."""
from services import career_assistant_agent as assistant
from services.job_matcher import compute_match


def _candidate():
    return {
        "name": "A Candidate",
        "skills": ["Python", "SQL"],
        "education": [{"institution": "Test University", "degree": "B.Tech"}],
        "experience": [{"title": "Data Intern", "organization": "Acme Analytics"}],
        "projects": [{"title": "CareerAI", "tech_stack": "Python, FAISS"}],
        "certifications": [],
        "summary": "Interested in AI roles.",
        "resume": {},
    }


def _context(role="AI Engineer", job=None):
    candidate = _candidate()
    hints = assistant.role_skill_hints(role)
    match_job = job or {
        "title": role,
        "required_skills": ", ".join(hints),
        "preferred_skills": "",
    }
    return {
        "candidate": candidate,
        "job": job,
        "match": compute_match(candidate["skills"], match_job),
        "skill_gap": None,
        "tailored_resume": None,
        "interview": {"questions": [], "plans": []},
        "applications": [],
        "pasted_jd": "",
        "target_role": role,
        "role_hints": hints,
        "context_mode": "selected_job" if job else "target_role",
        "job_id": job.get("job_id") if job else None,
    }


def _disable_llm(monkeypatch):
    monkeypatch.setattr(
        assistant,
        "generate",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("offline")),
    )


def test_want_to_become_ai_engineer_returns_profile_based_roadmap(monkeypatch):
    _disable_llm(monkeypatch)
    result = assistant.answer_question("I want to become an AI Engineer", _context())

    assert result["intent"] == "learning_roadmap"
    answer = result["answer"]
    assert "Already have" in answer
    assert "Need to learn" in answer
    assert "Suggested learning order" in answer
    assert "Practical projects" in answer
    assert "Next steps" in answer
    assert "Python" in answer
    assert "RAG" in answer
    assert "not exact job requirements" in answer


def test_prepare_for_ai_engineer_is_inferred_and_answered(monkeypatch):
    _disable_llm(monkeypatch)
    message = "What should I prepare for AI Engineer role?"
    assert assistant.extract_target_role(message) == "AI Engineer"
    assert assistant.classify_intent(message) == "learning_roadmap"

    result = assistant.answer_question(message, _context())
    answer = result["answer"]
    assert "Preparation plan for AI Engineer" in answer
    assert "deep learning" in answer.casefold()
    assert "GenAI" in answer
    assert "RAG" in answer
    assert "interview practice" in answer.casefold()


def test_selected_job_suitability_uses_actual_requirements(monkeypatch):
    _disable_llm(monkeypatch)
    job = {
        "job_id": 9,
        "title": "AI Engineer",
        "company": "Example Co",
        "required_skills": "Python, TensorFlow",
        "preferred_skills": "SQL",
    }
    result = assistant.answer_question(
        "Am I suitable for the selected job?",
        _context(job=job),
    )

    answer = result["answer"]
    assert result["intent"] == "selected_job_analysis"
    assert "Example Co" in answer
    assert "Python" in answer
    assert "TensorFlow" in answer
    assert "Missing required skills" in answer
    assert "not a hiring probability" in answer


def test_selected_job_question_without_job_asks_for_job_context(monkeypatch):
    _disable_llm(monkeypatch)
    result = assistant.answer_question(
        "Am I suitable for the selected job?",
        _context(role="AI Engineer"),
    )

    assert result["intent"] == "selected_job_analysis"
    assert "No selected job is active" in result["answer"]
    assert "select" in result["answer"].casefold()
    assert "Tell me about a target role" not in result["answer"]


def test_profile_based_skill_gap_is_actionable(monkeypatch):
    _disable_llm(monkeypatch)
    context = _context(role="AI Engineer")
    context["match"] = compute_match(
        ["Python"],
        {"title": "AI Engineer", "required_skills": "Python, TensorFlow, SQL"},
    )
    result = assistant.answer_question("What am I missing for an AI Engineer role?", context)

    answer = result["answer"]
    assert "Need to learn" in answer
    assert "TensorFlow" in answer
    assert "SQL" in answer
    assert "Practical projects" in answer


def test_route_infers_role_and_uses_verified_profile(app, client, candidate, monkeypatch):
    from database.db import get_db

    _disable_llm(monkeypatch)
    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("DELETE FROM skills WHERE user_id = %s", (candidate["user_id"],))
            cursor.execute(
                "INSERT INTO skills (user_id, name, category) VALUES (%s, %s, %s)",
                (candidate["user_id"], "Python", "other"),
            )
        db.commit()

    response = client.post(
        "/assistant/message",
        json={"message": "I want to become an AI Engineer"},
    )

    assert response.status_code == 200
    answer = response.get_json()["answer"]
    assert response.get_json()["intent"] == "learning_roadmap"
    assert "Roadmap for AI Engineer" in answer
    assert "Python" in answer
    assert "Suggested learning order" in answer


def test_selected_job_context_persists_for_the_next_chat_turn(app, client, candidate, monkeypatch):
    from database.db import get_db

    _disable_llm(monkeypatch)
    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT job_id, title, company FROM jobs ORDER BY job_id LIMIT 1")
            job = cursor.fetchone()

    first = client.post(
        "/assistant/message",
        json={"job_id": job["job_id"], "message": "Give me general career guidance."},
    )
    assert first.status_code == 200
    session_id = first.get_json()["session_id"]

    second = client.post(
        "/assistant/message",
        json={"session_id": session_id, "message": "Am I suitable for the selected job?"},
    )
    assert second.status_code == 200
    answer = second.get_json()["answer"]
    assert "No selected job is active" not in answer
    assert job["title"] in answer
