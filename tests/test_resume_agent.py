import json

from services.resume_agent import generate_tailored_resume, render_resume_html


def _candidate():
    return {
        "name": "A Candidate",
        "skills": ["JS", "Python", "SQL"],
        "education": [{
            "institution": "Verified University",
            "degree": "B.Tech",
            "field": "Computer Science",
            "start_date": "2022",
            "end_date": "2026",
        }],
        "experience": [{
            "title": "Software Developer",
            "organization": "Verified Company",
            "start_date": "2024",
            "end_date": "2025",
            "description": "Built Python API features and maintained SQL code.",
        }],
        "projects": [{
            "title": "Verified Project",
            "description": "Built a Python application with SQL.",
            "tech_stack": "Python, React.js",
        }],
        "certifications": [{
            "name": "Verified Certification",
            "issuer": "Verified Issuer",
        }],
        "resume": {"id": 7, "file_type": "pdf", "parse_status": "parsed"},
    }


def _job():
    return {
        "job_id": 1,
        "title": "Software Engineer",
        "company": "Target Company",
        "description": "Build reliable software.",
        "responsibilities": "Develop features.",
        "required_skills": "JavaScript, Docker",
        "preferred_skills": "AWS",
        "qualifications": "Graduate",
        "experience_required": "1-2 years",
        "education_required": "B.Tech",
    }


def _run(monkeypatch, model_output):
    monkeypatch.setattr(
        "services.resume_agent.generate",
        lambda *args, **kwargs: json.dumps(model_output),
    )
    return generate_tailored_resume(_candidate(), _job())


def test_alias_handling_uses_existing_m2_normalization(monkeypatch):
    result = _run(monkeypatch, {
        "professional_summary": "A verified summary.",
        "highlighted_skills": ["JavaScript"],
    })

    assert "JavaScript" in result["highlighted_skills"]
    assert not any(claim["type"] == "skill" for claim in result["flagged_claims"])


def test_unsupported_skill_is_not_added(monkeypatch):
    result = _run(monkeypatch, {
        "highlighted_skills": ["TensorFlow"],
    })

    assert "TensorFlow" not in result["highlighted_skills"]
    assert any(claim["type"] == "skill" for claim in result["flagged_claims"])


def test_missing_required_skill_cannot_become_profile_skill(monkeypatch):
    result = _run(monkeypatch, {
        "highlighted_skills": ["Docker", "JavaScript"],
    })

    assert "Docker" not in result["highlighted_skills"]
    assert "Docker" in [claim["claim"] for claim in result["flagged_claims"]]


def test_unsupported_project_and_technology_are_not_used(monkeypatch):
    result = _run(monkeypatch, {
        "highlighted_skills": ["Python"],
        "projects": [{
            "title": "Verified Project",
            "tech_stack": "Python, TensorFlow",
            "bullets": ["Improved the project workflow."],
        }],
    })

    assert [project["title"] for project in result["projects"]] == ["Verified Project"]
    assert result["projects"][0]["tech_stack"] == "Python, React.js"
    assert any(claim["type"] == "technology" for claim in result["flagged_claims"])


def test_unsupported_project_is_removed_and_flagged(monkeypatch):
    result = _run(monkeypatch, {
        "highlighted_skills": ["Python"],
        "projects": [{"title": "Invented Project", "tech_stack": "Python"}],
    })

    assert all(project["title"] != "Invented Project" for project in result["projects"])
    assert any(claim["type"] == "project" for claim in result["flagged_claims"])


def test_unsupported_experience_identity_and_dates_are_not_used(monkeypatch):
    result = _run(monkeypatch, {
        "highlighted_skills": ["Python"],
        "experience": [{
            "title": "Chief Executive Officer",
            "organization": "Invented Company",
            "start_date": "2030",
            "bullets": ["Managed a large team."],
        }],
    })

    assert result["experience"][0]["title"] == "Software Developer"
    assert result["experience"][0]["organization"] == "Verified Company"
    assert result["experience"][0]["start_date"] == "2024"
    assert any(claim["type"] == "experience" for claim in result["flagged_claims"])


def test_invented_metric_and_achievement_are_removed_from_suggestions(monkeypatch):
    result = _run(monkeypatch, {
        "highlighted_skills": ["Python"],
        "projects": [{
            "title": "Verified Project",
            "tech_stack": "Python, React.js",
            "bullets": ["Increased revenue by 40% and won an award."],
        }],
    })

    assert result["projects"][0]["bullets"] == ["Built a Python application with SQL."]
    assert not result["ai_suggestions"]["projects"]
    assert any(claim["type"] == "metric_or_achievement" for claim in result["flagged_claims"])


def test_unknown_fields_and_unsupported_certifications_are_not_persisted(monkeypatch):
    result = _run(monkeypatch, {
        "highlighted_skills": ["Python"],
        "certifications": [{"name": "Invented Certification"}],
        "secret_metric": "do not persist",
    })

    assert "secret_metric" not in result
    assert result["certifications"] == [{
        "name": "Verified Certification",
        "issuer": "Verified Issuer",
    }]
    assert any(claim["type"] == "unknown_field" for claim in result["flagged_claims"])
    assert any(claim["type"] == "certification" for claim in result["flagged_claims"])


def test_empty_output_is_not_marked_passed(monkeypatch):
    result = _run(monkeypatch, {})

    assert result["used_fallback"] is True
    assert result["fact_check_status"] == "fallback"
    assert result["fact_check_status"] != "passed"


def test_education_and_certification_facts_are_preserved(monkeypatch):
    result = _run(monkeypatch, {
        "highlighted_skills": ["Python"],
        "education": [{"institution": "Invented University"}],
        "certifications": [{"name": "Invented Certification"}],
    })

    assert result["education"] == _candidate()["education"]
    assert result["certifications"] == _candidate()["certifications"]


def test_generated_html_escapes_script_and_html():
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
