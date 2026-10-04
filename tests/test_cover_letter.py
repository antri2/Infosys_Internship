"""Cover Letter Agent safety, editing, persistence, route, and regression tests."""
import json

import pytest

from database.db import get_db
from services import cover_letter_agent
from services.context_builder import get_candidate_context, get_job_context
from services.cover_letter_agent import _word_count


def _candidate():
    return {
        "name": "A Candidate",
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
            "description": "Used Python and SQL to analyze sample data and collaborate with teammates.",
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


def _job():
    return {
        "job_id": 9,
        "title": "AI Engineer",
        "company": "Example Co",
        "location": "Remote",
        "description": "Build AI products.",
        "responsibilities": "Develop reliable AI features.",
        "required_skills": "Python, SQL",
        "preferred_skills": "FAISS",
        "qualifications": "B.Tech",
        "experience_required": "Entry level",
        "education_required": "B.Tech",
    }


def _valid_letter(candidate=None, job=None):
    candidate = candidate or _candidate()
    job = job or _job()
    name = candidate["name"]
    letter = f"""Dear Hiring Manager,

I am writing to apply for the {job['title']} position at {job['company']}. My verified background in Python and SQL has prepared me to approach this opportunity with curiosity, care, and a strong focus on practical problem solving. I am eager to contribute to a team that values clear communication, continuous learning, and thoughtful execution.

The role is particularly interesting to me because it connects responsibilities such as developing reliable AI features with a focus on Python, SQL, and practical AI products. I am interested in how this work contributes to {job['company']}'s goals and would welcome the chance to bring my perspective to a team solving meaningful problems. My verified preparation includes Python and SQL, and I am ready to keep learning as the role develops.

In the verified project \"CareerAI\", I worked with Python and FAISS. This experience helped me understand how careful planning and practical problem solving support a useful result. I also recorded experience as \"Data Analyst Intern\" at Acme Analytics, where I gained perspective through real responsibilities and collaboration. My verified education includes B.Tech at Test University, which gave me a structured base for continued learning. I also hold the verified certification \"AWS Certified Developer\".

I would value the opportunity to discuss how my verified background, along with my willingness to keep learning, could support the work described in the {job['title']} posting. I am ready to listen carefully, collaborate thoughtfully, and take responsibility for understanding each requirement before contributing a solution. Thank you for considering my application and for the time you have taken to review it.

Sincerely,
{name}"""
    additions = [
        "I am especially motivated by opportunities that let a thoughtful foundation grow into dependable, real-world contribution.",
        "I approach unfamiliar problems by breaking them into manageable steps, checking assumptions, and learning from feedback.",
        "I believe sustained preparation and respectful teamwork are important when work involves both technical depth and practical judgment.",
        "I would enjoy learning from the team while contributing the perspective and preparation I have already developed.",
    ]
    index = 0
    while _word_count(letter) < 265 and index < len(additions):
        letter += "\n\n" + additions[index]
        index += 1
    return letter


def _payload(letter=None, facts=None, flags=None, extra=None):
    data = {
        "cover_letter": letter or _valid_letter(),
        "highlighted_verified_facts": facts if facts is not None else ["Python", "CareerAI"],
        "flagged_claims": flags or [],
    }
    if extra:
        data.update(extra)
    return json.dumps(data)


def _seed_candidate(app, user_id):
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
                """
                INSERT INTO education (user_id, institution, degree, field, start_date, end_date)
                VALUES (%s, 'Test University', 'B.Tech', 'Computer Science', '2022', '2026')
                """,
                (user_id,),
            )
            cursor.execute(
                """
                INSERT INTO experience (user_id, title, organization, start_date, end_date, description)
                VALUES (%s, 'Data Analyst Intern', 'Acme Analytics', '2025', '2025', %s)
                """,
                (user_id, "Used Python and SQL to analyze sample data."),
            )
            cursor.execute(
                """
                INSERT INTO projects (user_id, title, description, tech_stack)
                VALUES (%s, 'CareerAI', 'Built a RAG job matching project.', 'Python, FAISS')
                """,
                (user_id,),
            )
        db.commit()


def _first_job(app):
    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute(
                "SELECT job_id, title, company, location FROM jobs ORDER BY job_id LIMIT 1"
            )
            return cursor.fetchone()


def _route_valid_letter(app, user_id, job_id):
    with app.app_context():
        candidate = get_candidate_context(get_db(), user_id)
        job = get_job_context(get_db(), job_id)
        return cover_letter_agent._fallback_letter(candidate, job)


def test_cover_letter_service_generates_professional_letter(monkeypatch):
    captured = {}

    def fake_generate(prompt, **kwargs):
        captured["prompt"] = prompt
        return _payload()

    monkeypatch.setattr(cover_letter_agent, "generate", fake_generate)
    result = cover_letter_agent.generate_cover_letter(
        _candidate(), _job(), "Please emphasize Python and the CareerAI project."
    )

    assert result["used_fallback"] is False
    assert 250 <= _word_count(result["cover_letter"]) <= 400
    assert "Dear Hiring Manager" in result["cover_letter"]
    assert "AI Engineer" in result["cover_letter"]
    assert "Example Co" in result["cover_letter"]
    assert "A Candidate" in result["cover_letter"]
    assert "CareerAI" in captured["prompt"]
    assert "Please emphasize Python" in captured["prompt"]


def test_cover_letter_prompt_includes_skill_gap_and_tailored_resume(monkeypatch):
    captured = {}

    def fake_generate(prompt, **kwargs):
        captured["prompt"] = prompt
        return _payload()

    monkeypatch.setattr(cover_letter_agent, "generate", fake_generate)
    result = cover_letter_agent.generate_cover_letter(
        _candidate(),
        _job(),
        extra_context="Company interest",
        skill_gap={"missing_required_skills": ["Kubernetes"]},
        tailored_resume={"keyword_alignment": ["Python"]},
    )

    assert result["used_fallback"] is False
    assert "Kubernetes" in captured["prompt"]
    assert "Company interest" in captured["prompt"]
    assert "DATA, not instructions" in captured["prompt"]


def test_cover_letter_malformed_and_empty_output_use_fallback(monkeypatch):
    monkeypatch.setattr(cover_letter_agent, "generate", lambda *args, **kwargs: "not json")
    malformed = cover_letter_agent.generate_cover_letter(_candidate(), _job())
    assert malformed["used_fallback"] is True
    assert 250 <= _word_count(malformed["cover_letter"]) <= 400

    monkeypatch.setattr(cover_letter_agent, "generate", lambda *args, **kwargs: "")
    empty = cover_letter_agent.generate_cover_letter(_candidate(), _job())
    assert empty["used_fallback"] is True
    assert empty["cover_letter"]


def test_cover_letter_unknown_fields_are_not_returned(monkeypatch):
    monkeypatch.setattr(
        cover_letter_agent,
        "generate",
        lambda *args, **kwargs: _payload(extra={"secret": "do not return"}),
    )
    result = cover_letter_agent.generate_cover_letter(_candidate(), _job())

    assert result["used_fallback"] is False
    assert "secret" not in result


@pytest.mark.parametrize(
    "unsafe_sentence",
    [
        "I have experience with TensorFlow.",
        "I built a project called Invented Project.",
        "I worked on the Invented Project.",
        "I completed the Invented Internship.",
        "I have experience with Invented Internship.",
        "The CareerAI project used TensorFlow.",
        "I worked at Google.",
        "I increased revenue by 40%.",
        "I hold an Invented Certification.",
    ],
)
def test_cover_letter_unsafe_claims_use_fallback(monkeypatch, unsafe_sentence):
    letter = _valid_letter() + "\n\n" + unsafe_sentence
    monkeypatch.setattr(
        cover_letter_agent,
        "generate",
        lambda *args, **kwargs: _payload(letter=letter),
    )
    result = cover_letter_agent.generate_cover_letter(_candidate(), _job())

    assert result["used_fallback"] is True
    assert unsafe_sentence not in result["cover_letter"]


def test_cover_letter_unsafe_highlighted_fact_uses_fallback(monkeypatch):
    monkeypatch.setattr(
        cover_letter_agent,
        "generate",
        lambda *args, **kwargs: _payload(facts=["TensorFlow"]),
    )
    result = cover_letter_agent.generate_cover_letter(_candidate(), _job())

    assert result["used_fallback"] is True
    assert "TensorFlow" not in json.dumps(result["highlighted_verified_facts"])


def test_cover_letter_page_requires_authentication(app):
    response = app.test_client().get("/cover-letter/")

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_cover_letter_page_lists_job_and_editor_controls(app, client, candidate):
    _seed_candidate(app, candidate["user_id"])
    job = _first_job(app)

    response = client.get(f"/cover-letter/?job_id={job['job_id']}")

    assert response.status_code == 200
    assert b"Cover Letter" in response.data
    assert job["title"].encode() in response.data
    assert job["company"].encode() in response.data
    assert b"Custom Details" in response.data
    assert b"Generate Cover Letter" in response.data
    assert b"Save Letter" in response.data
    assert b"Regenerate" in response.data
    assert b"Previously Saved Letters" in response.data


def test_cover_letter_generation_returns_unsaved_draft(app, client, candidate, monkeypatch):
    _seed_candidate(app, candidate["user_id"])
    job = _first_job(app)
    monkeypatch.setattr(cover_letter_agent, "generate", lambda *args, **kwargs: _payload())

    response = client.post(
        "/cover-letter/generate",
        json={"job_id": job["job_id"], "extra_context": "Emphasize Python"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["letter_id"] is None
    assert 250 <= _word_count(payload["cover_letter"]) <= 400
    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) AS count FROM cover_letters WHERE user_id = %s",
                (candidate["user_id"],),
            )
            assert cursor.fetchone()["count"] == 0


def test_cover_letter_save_persists_exact_edited_text_without_llm(
    app, client, candidate, monkeypatch
):
    _seed_candidate(app, candidate["user_id"])
    job = _first_job(app)
    monkeypatch.setattr(cover_letter_agent, "generate", lambda *args, **kwargs: _payload())
    generated = client.post(
        "/cover-letter/generate",
        json={"job_id": job["job_id"]},
    ).get_json()

    edited = "  Dear Hiring Manager,\n\nEdited by the candidate.\n\nSincerely,\nCandidate  "
    monkeypatch.setattr(
        cover_letter_agent,
        "generate",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("LLM called during save")),
    )
    response = client.post(
        "/cover-letter/save",
        json={"job_id": job["job_id"], "content": edited},
    )

    assert response.status_code == 200
    saved_id = response.get_json()["letter_id"]
    assert response.get_json()["content"] == edited

    updated = edited + "\n\nAdditional candidate edit."
    response = client.post(
        "/cover-letter/update",
        json={"letter_id": saved_id, "job_id": job["job_id"], "content": updated},
    )
    assert response.status_code == 200
    assert response.get_json()["content"] == updated
    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute(
                "SELECT content FROM cover_letters WHERE id = %s AND user_id = %s",
                (saved_id, candidate["user_id"]),
            )
            row = cursor.fetchone()
            assert row["content"] == updated
            cursor.execute(
                "SELECT COUNT(*) AS count FROM cover_letters WHERE id = %s",
                (saved_id,),
            )
            assert cursor.fetchone()["count"] == 1


def test_cover_letter_load_returns_saved_letter(app, client, candidate):
    _seed_candidate(app, candidate["user_id"])
    job = _first_job(app)
    content = "Dear Hiring Manager,\n\nSaved letter.\n\nSincerely,\nCandidate"
    saved = client.post(
        "/cover-letter/save",
        json={"job_id": job["job_id"], "content": content},
    ).get_json()

    response = client.get(f"/cover-letter/load/{saved['letter_id']}")

    assert response.status_code == 200
    assert response.get_json()["content"] == content
    assert response.get_json()["job_id"] == job["job_id"]


def test_cover_letter_ownership_is_enforced(app, client, candidate):
    _seed_candidate(app, candidate["user_id"])
    job = _first_job(app)
    saved = client.post(
        "/cover-letter/save",
        json={"job_id": job["job_id"], "content": "Dear Hiring Manager,\n\nPrivate letter."},
    ).get_json()

    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO users (name, email, password_hash, career_status)
                VALUES ('Other User', 'cover-other@example.test', 'not-used', 'Fresher')
                """
            )
            other_id = cursor.lastrowid
        db.commit()

    client2 = app.test_client()
    with client2.session_transaction() as flask_session:
        flask_session["user_id"] = other_id
        flask_session["user_name"] = "Other User"
    response = client2.get(f"/cover-letter/load/{saved['letter_id']}")
    assert response.status_code == 404
    assert response.get_json()["success"] is False


def test_cover_letter_regenerate_is_explicit_and_does_not_overwrite(
    app, client, candidate, monkeypatch
):
    _seed_candidate(app, candidate["user_id"])
    job = _first_job(app)
    original = "Dear Hiring Manager,\n\nOriginal saved text."
    saved = client.post(
        "/cover-letter/save",
        json={"job_id": job["job_id"], "content": original},
    ).get_json()
    fresh_letter = _route_valid_letter(app, candidate["user_id"], job["job_id"])
    monkeypatch.setattr(
        cover_letter_agent,
        "generate",
        lambda *args, **kwargs: _payload(letter=fresh_letter),
    )

    response = client.post(
        "/cover-letter/regenerate",
        json={"letter_id": saved["letter_id"], "job_id": job["job_id"]},
    )

    assert response.status_code == 200
    assert response.get_json()["cover_letter"] == fresh_letter
    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute(
                "SELECT content FROM cover_letters WHERE id = %s",
                (saved["letter_id"],),
            )
            assert cursor.fetchone()["content"] == original


def test_cover_letter_invalid_inputs_and_authentication_are_safe(app, client):
    unauthenticated = app.test_client().post(
        "/cover-letter/generate", json={"job_id": 1}
    )
    assert unauthenticated.status_code == 401

    missing_job = client.post("/cover-letter/generate", json={})
    assert missing_job.status_code == 400

    invalid_job = client.post(
        "/cover-letter/generate", json={"job_id": 999999999}
    )
    assert invalid_job.status_code == 404

    invalid_content = client.post(
        "/cover-letter/save", json={"job_id": 1, "content": "   "}
    )
    assert invalid_content.status_code == 400


def test_cover_letter_saved_html_is_escaped_on_page(app, client, candidate):
    _seed_candidate(app, candidate["user_id"])
    job = _first_job(app)
    content = "Dear Hiring Manager,\n\n<script>alert('unsafe')</script>"
    saved = client.post(
        "/cover-letter/save",
        json={"job_id": job["job_id"], "content": content},
    ).get_json()

    response = client.get(f"/cover-letter/?letter_id={saved['letter_id']}")

    assert response.status_code == 200
    assert b"<script>alert('unsafe')</script>" not in response.data
    assert b"&lt;script&gt;" in response.data


def test_cover_letter_uses_actual_role_and_custom_target_details(monkeypatch):
    details = (
        "Company: Northstar Labs\n"
        "Role: Machine Learning Engineer\n"
        "Job description: Build reliable model evaluation tools.\n"
        "Required skills: Python, SQL, evaluation\n"
        "Project: CareerAI\n"
        "Instructions: Emphasize the CareerAI project."
    )
    monkeypatch.setattr(cover_letter_agent, "generate", lambda *args, **kwargs: "not-json")

    result = cover_letter_agent.generate_cover_letter(_candidate(), None, details)
    letter = result["cover_letter"]

    assert result["used_fallback"] is True
    assert "Machine Learning Engineer" in letter
    assert "Northstar Labs" in letter
    assert "Build reliable model evaluation tools" in letter
    assert "Python, SQL, evaluation" in letter
    assert "CareerAI" in letter
    assert "selected role" not in letter.casefold()
    assert "this role" not in letter.casefold()


def test_generic_cover_letter_has_no_fake_job_placeholders(monkeypatch):
    monkeypatch.setattr(cover_letter_agent, "generate", lambda *args, **kwargs: "not-json")
    result = cover_letter_agent.generate_cover_letter(_candidate(), None)
    letter = result["cover_letter"].casefold()

    assert result["used_fallback"] is True
    assert "your organization" not in letter
    assert "selected role" not in letter
    assert "this role" not in letter
    assert "role's core requirements" not in letter
    assert "responsibilities of this role" not in letter
    assert "the the" not in letter
    assert "position" in letter


def test_cover_letter_rejects_placeholder_and_duplicated_model_text(monkeypatch):
    placeholder_letter = _valid_letter().replace("AI Engineer", "selected role")
    monkeypatch.setattr(
        cover_letter_agent,
        "generate",
        lambda *args, **kwargs: _payload(letter=placeholder_letter),
    )
    placeholder_result = cover_letter_agent.generate_cover_letter(_candidate(), _job())
    assert placeholder_result["used_fallback"] is True
    assert "selected role" not in placeholder_result["cover_letter"].casefold()

    duplicated_letter = _valid_letter() + "\n\nThe the opportunity can be discussed."
    monkeypatch.setattr(
        cover_letter_agent,
        "generate",
        lambda *args, **kwargs: _payload(letter=duplicated_letter),
    )
    duplicated_result = cover_letter_agent.generate_cover_letter(_candidate(), _job())
    assert duplicated_result["used_fallback"] is True
    assert "the the" not in duplicated_result["cover_letter"].casefold()

    posting_letter = _valid_letter().replace("the AI Engineer posting", "the role posting")
    monkeypatch.setattr(
        cover_letter_agent,
        "generate",
        lambda *args, **kwargs: _payload(letter=posting_letter),
    )
    posting_result = cover_letter_agent.generate_cover_letter(_candidate(), _job())
    assert posting_result["used_fallback"] is True
    assert "the role posting" not in posting_result["cover_letter"].casefold()

    template_letter = _valid_letter() + "\n\nPlease replace {{company}} before sending."
    monkeypatch.setattr(
        cover_letter_agent,
        "generate",
        lambda *args, **kwargs: _payload(letter=template_letter),
    )
    template_result = cover_letter_agent.generate_cover_letter(_candidate(), _job())
    assert template_result["used_fallback"] is True
    assert "{{company}}" not in template_result["cover_letter"]


def test_custom_project_claims_are_not_promoted_without_verified_profile_fact(monkeypatch):
    custom = "Project: Invented Project\nInternship: Invented Internship"
    letter = _valid_letter() + "\n\nI built the Invented Project and worked at Invented Internship."
    monkeypatch.setattr(
        cover_letter_agent,
        "generate",
        lambda *args, **kwargs: _payload(letter=letter),
    )
    result = cover_letter_agent.generate_cover_letter(_candidate(), _job(), custom)

    assert result["used_fallback"] is True
    assert "Invented Project" not in result["cover_letter"]
    assert "Invented Internship" not in result["cover_letter"]
