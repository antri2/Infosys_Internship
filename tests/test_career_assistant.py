"""Career Assistant grounding, routing, persistence, and safety tests."""
import json

import pytest

from database.db import get_db
from services import career_assistant_agent, llm_client
from services.agent_orchestrator import AgentOrchestrator
from services.job_matcher import compute_match


def _candidate():
    return {
        "name": "A Candidate",
        "email": "private@example.test",
        "phone": "9999999999",
        "skills": ["Python", "SQL"],
        "education": [{
            "institution": "Test University",
            "degree": "B.Tech",
            "field": "Computer Science",
        }],
        "experience": [{
            "title": "Data Intern",
            "organization": "Acme Analytics",
            "description": "Used Python and SQL.",
        }],
        "projects": [{
            "title": "CareerAI",
            "description": "Built a RAG project.",
            "tech_stack": "Python, FAISS",
        }],
        "certifications": [{"name": "Verified Certificate"}],
        "college": "Test University",
        "degree": "B.Tech",
        "summary": "Interested in AI roles.",
        "resume": {"id": 1, "file_type": "pdf", "parse_status": "parsed"},
    }


def _job():
    return {
        "job_id": 9,
        "title": "AI Engineer",
        "company": "Example Co",
        "location": "Remote",
        "description": "Build AI products.",
        "responsibilities": "Develop AI features.",
        "required_skills": "Python, TensorFlow",
        "preferred_skills": "SQL",
        "qualifications": "B.Tech",
        "experience_required": "Entry level",
        "education_required": "B.Tech",
    }


def _context(mode="target_role", candidate=None, job=None):
    candidate = _candidate() if candidate is None else candidate
    job = job if mode == "selected_job" else None
    target_role = (job or {}).get("title") or "AI Engineer"
    role_hints = career_assistant_agent.role_skill_hints(target_role)
    match_job = job or {
        "title": target_role,
        "required_skills": ", ".join(role_hints),
        "preferred_skills": "",
        "description": "General role guidance.",
    }
    return {
        "candidate": candidate,
        "job": job,
        "match": compute_match(candidate.get("skills", []), match_job),
        "skill_gap": None,
        "tailored_resume": None,
        "interview": {"questions": [], "plans": []},
        "applications": [],
        "pasted_jd": "",
        "target_role": target_role,
        "role_hints": role_hints,
        "context_mode": mode,
        "requirement_source": "test context",
        "job_id": job.get("job_id") if job else None,
    }


def _model_output(answer=None, intent="learning_roadmap", facts=None):
    return json.dumps({
        "intent": intent,
        "answer": answer or "Your verified profile includes Python. For a general AI Engineer target, consider the role hints and choose a small practice project.",
        "grounded_facts": facts if facts is not None else ["Python"],
    })


def _seed(app, user_id):
    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("DELETE FROM skills WHERE user_id = %s", (user_id,))
            cursor.execute("DELETE FROM projects WHERE user_id = %s", (user_id,))
            cursor.execute("DELETE FROM experience WHERE user_id = %s", (user_id,))
            cursor.execute("DELETE FROM education WHERE user_id = %s", (user_id,))
            for skill in ("Python", "SQL"):
                cursor.execute(
                    "INSERT INTO skills (user_id, name, category) VALUES (%s, %s, 'other')",
                    (user_id, skill),
                )
            cursor.execute(
                "INSERT INTO projects (user_id, title, description, tech_stack) VALUES (%s, 'CareerAI', 'Built a RAG project.', 'Python, FAISS')",
                (user_id,),
            )
            cursor.execute(
                "INSERT INTO education (user_id, institution, degree, field) VALUES (%s, 'Test University', 'B.Tech', 'Computer Science')",
                (user_id,),
            )
        db.commit()


def test_assistant_page_requires_authentication(app):
    response = app.test_client().get("/assistant/")

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_assistant_page_loads_for_authenticated_user(client):
    response = client.get("/assistant/")

    assert response.status_code == 200
    assert b"Career Assistant" in response.data
    assert b"Starter Questions" in response.data
    assert b"Selected synchronized job" in response.data
    assert b"Target role" in response.data
    assert b"grounded deterministic fallback" not in response.data


def test_llm_client_omits_unsupported_reasoning_parameters(monkeypatch):
    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return type(
                "Response",
                (),
                {"choices": [type("Choice", (), {"message": type("Message", (), {"content": "OK"})()})()]},
            )()

    fake_client = type(
        "FakeClient",
        (),
        {"chat": type("Chat", (), {"completions": FakeCompletions()})()},
    )()
    monkeypatch.setattr(llm_client, "_get_client", lambda: fake_client)

    assert llm_client.generate("hello", max_tokens=32, temperature=0.1) == "OK"
    assert "reasoning_effort" not in captured
    assert "reasoning_format" not in captured
    assert captured["model"]


def test_assistant_accepts_open_ended_llm_answers_without_a_fixed_intent(monkeypatch):
    monkeypatch.setattr(
        career_assistant_agent,
        "generate",
        lambda *args, **kwargs: "A natural conversational answer.",
    )

    result = career_assistant_agent.answer_question("Hi", _context(candidate={}))

    assert result["used_fallback"] is False
    assert result["answer"] == "A natural conversational answer."


def test_project_question_is_answered_by_llm_not_the_legacy_roadmap(monkeypatch):
    captured = {}

    def fake_generate(prompt, **kwargs):
        captured["prompt"] = prompt
        return "Build on your existing RAG work by adding evaluation, deployment, and documentation."

    monkeypatch.setattr(career_assistant_agent, "generate", fake_generate)
    result = career_assistant_agent.answer_question(
        "What projects should I build for an AI Engineer role?",
        _context(),
    )

    assert result["used_fallback"] is False
    assert not result["answer"].casefold().startswith("roadmap for")
    assert "RAG" in captured["prompt"]
    assert "CareerAI" in captured["prompt"]


def test_assistant_logs_provider_failure_without_exposing_credentials(monkeypatch, caplog):
    monkeypatch.setattr(
        career_assistant_agent,
        "generate",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("api_key=super-secret provider unavailable")
        ),
    )

    result = career_assistant_agent.answer_question("Hi", _context(candidate={}))

    assert result["used_fallback"] is True
    assert "super-secret" not in caplog.text
    assert "RuntimeError" in caplog.text


def test_assistant_extracts_target_role_without_selected_job():
    extracted = career_assistant_agent.extract_target_role(
        "I want to become an AI Engineer. What should I learn next?"
    )

    assert extracted == "AI Engineer"


def test_assistant_answers_target_role_question(monkeypatch):
    captured = {}

    def fake_generate(prompt, **kwargs):
        captured["prompt"] = prompt
        return _model_output()

    monkeypatch.setattr(career_assistant_agent, "generate", fake_generate)
    result = career_assistant_agent.answer_question(
        "I want to become an AI Engineer. What should I learn next?",
        _context(),
    )

    assert result["used_fallback"] is False
    assert result["intent"] == "learning_roadmap"
    assert "Python" in captured["prompt"]
    assert "DATA, not instructions" in captured["prompt"]


def test_assistant_answers_selected_job_question(monkeypatch):
    context = _context("selected_job", job=_job())
    monkeypatch.setattr(
        career_assistant_agent,
        "generate",
        lambda *args, **kwargs: _model_output(
            answer="The selected job comparison shows Python as a verified match and TensorFlow as a skill gap.",
            intent="selected_job_analysis",
            facts=["Python", "TensorFlow"],
        ),
    )

    result = career_assistant_agent.answer_question("Am I suitable for this job?", context)

    assert result["used_fallback"] is False
    assert result["intent"] == "selected_job_analysis"
    assert "TensorFlow" in result["answer"]


def test_assistant_supports_pasted_job_description(monkeypatch):
    context = _context("pasted_jd")
    context["pasted_jd"] = "AI Engineer role. Required skills: Python and TensorFlow."
    context["match"] = compute_match(
        ["Python"], {"title": "Pasted role", "required_skills": "Python, TensorFlow", "preferred_skills": ""}
    )
    monkeypatch.setattr(career_assistant_agent, "generate", lambda *args, **kwargs: _model_output())
    result = career_assistant_agent.answer_question(
        "What skills are missing for the pasted role?", context
    )

    assert result["used_fallback"] is False
    assert result["grounded_facts"]


def test_assistant_skill_gap_and_match_context_is_grounded(monkeypatch):
    captured = {}
    context = _context("selected_job", job=_job())
    context["skill_gap"] = {"missing_required_skills": ["TensorFlow"]}
    def fake_generate(prompt, **kwargs):
        captured["prompt"] = prompt
        return _model_output(
            answer="The verified matcher shows Python as a match and TensorFlow as a gap.",
            intent="selected_job_analysis",
            facts=["Python", "TensorFlow"],
        )

    monkeypatch.setattr(career_assistant_agent, "generate", fake_generate)

    result = career_assistant_agent.answer_question("Why am I not matching this job?", context)

    assert result["used_fallback"] is False
    assert "TensorFlow" in captured["prompt"]
    assert "Python" in result["answer"]


def test_assistant_missing_context_explicitly_asks_for_it(monkeypatch):
    monkeypatch.setattr(
        career_assistant_agent,
        "generate",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    result = career_assistant_agent.answer_question(
        "What should I learn next?",
        _context(candidate={}),
    )

    assert result["used_fallback"] is True
    assert "enough verified profile information" in result["answer"]


def test_assistant_malformed_or_failed_llm_uses_fallback(monkeypatch):
    monkeypatch.setattr(career_assistant_agent, "generate", lambda *args, **kwargs: "not-json")
    malformed = career_assistant_agent.answer_question("What should I learn next?", _context())
    assert malformed["used_fallback"] is True

    monkeypatch.setattr(
        career_assistant_agent,
        "generate",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("provider down")),
    )
    failed = career_assistant_agent.answer_question("Help me prepare for an interview.", _context())
    assert failed["used_fallback"] is True
    assert failed["answer"]


def test_assistant_rejects_unsupported_grounded_fact_and_claim(monkeypatch):
    monkeypatch.setattr(
        career_assistant_agent,
        "generate",
        lambda *args, **kwargs: _model_output(
            answer="You have extensive TensorFlow experience and a 40% improvement.",
            facts=["TensorFlow"],
        ),
    )
    result = career_assistant_agent.answer_question("What should I learn next?", _context())

    assert result["used_fallback"] is True
    assert "TensorFlow" not in result["grounded_facts"]


def test_assistant_selected_job_route_uses_job_context(app, client, candidate, monkeypatch):
    _seed(app, candidate["user_id"])
    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT job_id, title, required_skills FROM jobs ORDER BY job_id LIMIT 1")
            job = cursor.fetchone()
    captured = {}

    def fake_generate(prompt, **kwargs):
        captured["prompt"] = prompt
        return _model_output(
            answer="The selected job comparison uses the stored role requirements and verified profile.",
            intent="selected_job_analysis",
            facts=["Python"],
        )

    monkeypatch.setattr(career_assistant_agent, "generate", fake_generate)
    response = client.post(
        "/assistant/message",
        json={"job_id": job["job_id"], "message": "Am I suitable for this job?"},
    )

    assert response.status_code == 200
    assert job["title"] in captured["prompt"]
    assert job["required_skills"] in captured["prompt"]


def test_assistant_route_persists_conversation_scoped_to_user(app, client, candidate, monkeypatch):
    _seed(app, candidate["user_id"])
    monkeypatch.setattr(career_assistant_agent, "generate", lambda *args, **kwargs: _model_output())

    first = client.post(
        "/assistant/message",
        json={"message": "I want to become an AI Engineer. What should I learn?"},
    )
    assert first.status_code == 200
    first_payload = first.get_json()
    assert first_payload["success"] is True
    session_id = first_payload["session_id"]

    second = client.post(
        "/assistant/message",
        json={"session_id": session_id, "message": "Help me prepare for an interview."},
    )
    assert second.status_code == 200
    messages = second.get_json()["messages"]
    assert [item["role"] for item in messages] == ["user", "assistant", "user", "assistant"]

    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) AS count FROM chat_messages WHERE session_id = %s",
                (session_id,),
            )
            assert cursor.fetchone()["count"] == 4


def test_assistant_history_rejects_other_user_session(app, client, candidate, monkeypatch):
    _seed(app, candidate["user_id"])
    monkeypatch.setattr(career_assistant_agent, "generate", lambda *args, **kwargs: _model_output())
    saved = client.post(
        "/assistant/message", json={"message": "What should I learn?"}
    ).get_json()

    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute(
                "INSERT INTO users (name, email, password_hash, career_status) VALUES ('Other', 'assistant-other@example.test', 'x', 'Fresher')"
            )
            other_id = cursor.lastrowid
        db.commit()

    other = app.test_client()
    with other.session_transaction() as flask_session:
        flask_session["user_id"] = other_id
    response = other.get(f"/assistant/history/{saved['session_id']}")
    assert response.status_code == 404
    assert response.get_json()["success"] is False


def test_assistant_reset_starts_new_user_scoped_session(client, monkeypatch):
    monkeypatch.setattr(career_assistant_agent, "generate", lambda *args, **kwargs: _model_output())
    first = client.post("/assistant/message", json={"message": "What should I learn?"}).get_json()
    reset = client.post("/assistant/reset")
    assert reset.status_code == 200
    assert reset.get_json()["session_id"] != first["session_id"]


def test_assistant_user_message_is_html_escaped_on_page(client, monkeypatch):
    monkeypatch.setattr(career_assistant_agent, "generate", lambda *args, **kwargs: _model_output())
    response = client.post(
        "/assistant/message",
        json={"message": "<script>alert('unsafe')</script> What should I learn?"},
    )
    assert response.status_code == 200
    page = client.get("/assistant/")
    assert b"<script>alert('unsafe')</script>" not in page.data
    assert b"&lt;script&gt;" in page.data


def test_assistant_does_not_expose_private_contact_fields_to_prompt(monkeypatch):
    captured = {}

    def fake_generate(prompt, **kwargs):
        captured["prompt"] = prompt
        return _model_output()

    monkeypatch.setattr(career_assistant_agent, "generate", fake_generate)
    career_assistant_agent.answer_question("What should I learn next?", _context())
    assert "private@example.test" not in captured["prompt"]
    assert "9999999999" not in captured["prompt"]


def test_assistant_does_not_modify_profile_or_resume(app, client, candidate, monkeypatch):
    _seed(app, candidate["user_id"])
    before = {}
    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS count FROM skills WHERE user_id = %s", (candidate["user_id"],))
            before["skills"] = cursor.fetchone()["count"]
            cursor.execute("SELECT COUNT(*) AS count FROM tailored_resumes WHERE user_id = %s", (candidate["user_id"],))
            before["resumes"] = cursor.fetchone()["count"]
    monkeypatch.setattr(career_assistant_agent, "generate", lambda *args, **kwargs: _model_output())
    response = client.post("/assistant/message", json={"message": "What should I learn next?"})
    assert response.status_code == 200
    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS count FROM skills WHERE user_id = %s", (candidate["user_id"],))
            assert cursor.fetchone()["count"] == before["skills"]
            cursor.execute("SELECT COUNT(*) AS count FROM tailored_resumes WHERE user_id = %s", (candidate["user_id"],))
            assert cursor.fetchone()["count"] == before["resumes"]


def test_assistant_multi_topic_conversation_keeps_history_and_uses_llm(
    app, client, candidate, monkeypatch
):
    _seed(app, candidate["user_id"])
    prompts = []

    def fake_generate(prompt, **kwargs):
        prompts.append(prompt)
        return json.dumps({
            "answer": "I will use the conversation so far and give you a practical next step.",
            "intent": "open_career_coaching",
            "grounded_facts": [],
        })

    monkeypatch.setattr(career_assistant_agent, "generate", fake_generate)
    questions = [
        "Hi",
        "I want to become an AI Engineer.",
        "I already know Python and ML.",
        "How can I improve my resume?",
        "Which project should I highlight?",
        "Help me prepare for an interview.",
        "Why am I not getting shortlisted?",
        "What should I learn next?",
    ]

    session_id = None
    responses = []
    for question in questions:
        payload = {"message": question}
        if session_id is not None:
            payload["session_id"] = session_id
        response = client.post("/assistant/message", json=payload)
        assert response.status_code == 200
        data = response.get_json()
        assert data["used_fallback"] is False
        responses.append(data)
        session_id = data["session_id"]

    assert len(prompts) == len(questions)
    assert "I want to become an AI Engineer." in prompts[1]
    assert "I already know Python and ML." in prompts[2]
    assert "CareerAI" in prompts[4]
    assert "conversation_history" in prompts[2]
    assert responses[0]["intent"] == "open_career_coaching"
    assert all("deterministic fallback" not in data["answer"].casefold() for data in responses)
