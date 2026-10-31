"""Cover Letter must never invent a company or a job description.

Two modes are enforced end to end:

* GENERAL ROLE MODE      -- role only. No company, no posting, no invented
                           responsibilities. Addressed to "Dear Hiring Manager".
* COMPANY / JOB MODE     -- only when the user supplied a company name, a job
                           description, or explicitly selected an opportunity.

A role name is not a company, and a role name is not a job description.
"""

import pytest

from services import cover_letter_agent as agent
from services.cover_letter_agent import (
    COMPANY_JOB_MODE,
    GENERAL_ROLE_MODE,
    _build_target_context,
    _contains_invented_company,
    _contains_presumed_posting,
)


CANDIDATE = {
    "name": "Anchal Tripathi",
    "college": "AKS University",
    "degree": "B.Tech",
    "passing_year": 2026,
    "cgpa": 8.66,
    "skills": ["Python", "SQL", "Machine Learning"],
    "education": [{"institution": "AKS University", "degree": "B.Tech"}],
    "experience": [
        {"title": "AI Intern", "organization": "Infosys", "description": "Built models."}
    ],
    "projects": [{"title": "Resume Ranker", "tech_stack": "Python, FAISS"}],
    "certifications": [{"name": "AWS Certified", "issuer": "Amazon"}],
    "summary": "Machine learning student.",
}

FAKE_COMPANY = "Redwood Analytics"


def _letter(body: str, name: str = "Anchal Tripathi") -> str:
    """A structurally valid letter so the mode checks are what is under test."""
    filler = (
        "I have worked on data analysis, model building and evaluation, and I "
        "enjoy turning ambiguous problems into measurable outcomes. "
    ) * 12
    return (
        f"Dear Hiring Manager,\n\n"
        f"{body}\n\n{filler}\n\n"
        f"Sincerely,\n{name}"
    )


# ------------------------------------------------------------- mode routing ---


def test_role_only_selects_general_role_mode():
    target = _build_target_context(None, "Role: Data Scientist")
    assert target["_mode"] == GENERAL_ROLE_MODE
    assert target["title"] == "Data Scientist"
    assert target.get("company") in (None, "")


def test_company_name_switches_to_company_job_mode():
    target = _build_target_context(None, "Role: Data Scientist\nCompany: ABC Technologies")
    assert target["_mode"] == COMPANY_JOB_MODE
    assert target["company"] == "ABC Technologies"


def test_job_description_switches_to_company_job_mode():
    target = _build_target_context(
        None,
        "Role: Data Scientist\nJob description: Build dashboards in Power BI and SQL.",
    )
    assert target["_mode"] == COMPANY_JOB_MODE
    assert "Power BI" in target["description"]


def test_selected_opportunity_switches_to_company_job_mode():
    target = _build_target_context({"title": "Data Scientist", "company": "ABC Tech"}, "")
    assert target["_mode"] == COMPANY_JOB_MODE


# ------------------------------------------------- invented-company detection ---


def test_detects_invented_company_in_at_phrase():
    letter = _letter(
        f"I am writing to express my interest in the Data Scientist position at {FAKE_COMPANY}."
    )
    assert _contains_invented_company(letter, CANDIDATE) is True


def test_detects_invented_company_in_greeting():
    letter = _letter("I am applying for the position.")
    letter = letter.replace("Dear Hiring Manager,", f"Dear {FAKE_COMPANY} Hiring Manager,")
    assert _contains_invented_company(letter, CANDIDATE) is True


def test_detects_invented_company_in_is_looking_phrase():
    letter = _letter(f"{FAKE_COMPANY} is looking for a data scientist to join their team.")
    assert _contains_invented_company(letter, CANDIDATE) is True


def test_allows_the_candidate_own_verified_employer():
    """Mentioning a real internship on the profile is not an invention."""
    letter = _letter(
        "During my internship at Infosys I built data pipelines and evaluation reports."
    )
    assert _contains_invented_company(letter, CANDIDATE) is False


def test_allows_verified_university_name():
    letter = _letter("I studied at AKS University and enjoy applied machine learning work.")
    assert _contains_invented_company(letter, CANDIDATE) is False


def test_general_role_letter_is_clean():
    letter = _letter(
        "I am writing to express my interest in the Data Scientist position. "
        "With a background in machine learning and hands-on Python work, I am "
        "keen to apply these skills to practical problems."
    )
    assert _contains_invented_company(letter, CANDIDATE) is False


# ----------------------------------------------- invented-job-detail detection ---


@pytest.mark.parametrize(
    "sentence",
    [
        "The opportunity description highlights the need for strong SQL skills.",
        "The stated responsibilities include building dashboards.",
        "The stated requirements include Python and SQL.",
        "Your job posting states that the team is growing fast.",
        "As described in the job posting, the role is entry level.",
        "The role's core requirements include cloud experience.",
    ],
)
def test_detects_presumed_posting_language(sentence):
    assert _contains_presumed_posting(_letter(sentence)) is True


def test_clean_general_letter_has_no_presumed_posting():
    letter = _letter(
        "I am writing to express my interest in the Data Scientist position and "
        "would welcome the chance to discuss how my background fits."
    )
    assert _contains_presumed_posting(letter) is False


# ------------------------------------------------------------------- prompts ---


def test_general_role_prompt_forbids_company_and_posting_language():
    prompt = agent._build_prompt(CANDIDATE, None, "Role: Data Scientist", None, None)
    assert "GENERAL ROLE MODE" in prompt
    assert "DO NOT name or imply any company" in prompt
    assert 'GENERAL ROLE MODE' in prompt
    assert '"mode": "general_role"' in prompt.replace("'", '"')


def test_company_job_prompt_allows_the_supplied_company():
    prompt = agent._build_prompt(
        CANDIDATE, None, "Role: Data Scientist\nCompany: ABC Technologies", None, None
    )
    assert "COMPANY / JOB-SPECIFIC MODE" in prompt
    assert "You may name the supplied company." in prompt
    assert "DO NOT name or imply any company" not in prompt


# ----------------------------------------------- route-level mode separation ---


def _companies_from_db(app):
    from database.db import get_db

    with app.app_context():
        with get_db().cursor() as cursor:
            cursor.execute("SELECT DISTINCT company FROM jobs")
            return [row["company"] for row in cursor.fetchall()]


@pytest.fixture
def profile_user(app, candidate):
    """A candidate with real skills so generated letters can be meaningful."""
    from database.db import get_db

    with app.app_context():
        connection = get_db()
        with connection.cursor() as cursor:
            for name in ("Python", "SQL", "Machine Learning", "Pandas"):
                cursor.execute(
                    "INSERT INTO skills (user_id, name, category) VALUES (%s, %s, 'tool')",
                    (candidate["user_id"], name),
                )
            cursor.execute(
                "UPDATE profiles SET college = 'AKS University', degree = 'B.Tech', "
                "summary = %s, cgpa = 8.66 WHERE user_id = %s",
                (
                    "Machine learning student with hands-on Python and SQL experience.",
                    candidate["user_id"],
                ),
            )
            cursor.execute(
                "INSERT INTO education (user_id, institution, degree) "
                "VALUES (%s,'AKS University','B.Tech')",
                (candidate["user_id"],),
            )
            cursor.execute(
                "INSERT INTO experience (user_id, title, organization, description) "
                "VALUES (%s,'AI Intern','Infosys','Built data pipelines.')",
                (candidate["user_id"],),
            )
        connection.commit()
    return candidate


# TEST 1 -------------------------------------------------------------------
def test_test1_role_only_produces_a_general_letter(app, client, profile_user):
    """Role: Data Scientist | Company: empty | JD: empty."""
    response = client.post(
        "/cover-letter/generate",
        json={"generic": True, "target_role": "Data Scientist"},
    )
    assert response.status_code == 200
    payload = response.get_json()

    assert payload["job_id"] is None
    assert payload["job"] is None
    assert payload["validation_status"] in {"validated", "fallback"}

    letter = payload["cover_letter"]
    assert "Dear Hiring Manager" in letter
    assert "Data Scientist" in letter

    lowered = letter.casefold()
    for company in _companies_from_db(app):
        assert company.casefold() not in lowered, company
    assert _contains_invented_company(letter, CANDIDATE) is False
    assert _contains_presumed_posting(letter) is False


# TEST 2 -------------------------------------------------------------------
def test_test2_company_only_may_use_the_company(app, client, profile_user):
    """Role: Data Scientist | Company: ABC Technologies | JD: empty."""
    response = client.post(
        "/cover-letter/generate",
        json={
            "generic": True,
            "target_role": "Data Scientist",
            "extra_context": "Role: Data Scientist\nCompany: ABC Technologies",
        },
    )
    assert response.status_code == 200
    payload = response.get_json()

    letter = payload["cover_letter"]
    assert payload["job_id"] is None

    lowered = letter.casefold()
    # No dataset company may leak in.
    for company in _companies_from_db(app):
        assert company.casefold() not in lowered, company
    # Only the company the user actually supplied may be named.
    assert (
        _contains_invented_company(letter, CANDIDATE, allowed_companies="ABC Technologies")
        is False
    )
    # No invented posting detail: a company alone is not a job description.
    assert _contains_presumed_posting(letter) is False


# TEST 3 -------------------------------------------------------------------
def test_test3_company_and_jd_are_used(app, client, profile_user):
    """Role: Data Scientist | Company: ABC Technologies | JD: provided."""
    response = client.post(
        "/cover-letter/generate",
        json={
            "generic": True,
            "target_role": "Data Scientist",
            "extra_context": (
                "Role: Data Scientist\n"
                "Company: ABC Technologies\n"
                "Job description: The role involves building dashboards in Power BI "
                "and writing SQL queries against a large warehouse."
            ),
        },
    )
    assert response.status_code == 200
    payload = response.get_json()
    letter = payload["cover_letter"]

    # Company mode is allowed to name the supplied company, but nothing else.
    assert (
        _contains_invented_company(letter, CANDIDATE, allowed_companies="ABC Technologies")
        is False
    )
    lowered = letter.casefold()
    for company in _companies_from_db(app):
        assert company.casefold() not in lowered, company


# TEST 4 -------------------------------------------------------------------
def test_test4_role_only_intern_general_letter(app, client, profile_user):
    """Role: Data Science Intern | Company: empty | JD: empty."""
    response = client.post(
        "/cover-letter/generate",
        json={"generic": True, "target_role": "Data Science Intern"},
    )
    assert response.status_code == 200
    payload = response.get_json()

    letter = payload["cover_letter"]
    assert "Data Science Intern" in letter
    assert payload["job_id"] is None

    lowered = letter.casefold()
    for company in _companies_from_db(app):
        assert company.casefold() not in lowered, company
    assert _contains_presumed_posting(letter) is False


# TEST 5 -------------------------------------------------------------------
def test_test5_previous_company_does_not_leak_into_a_general_letter(
    app, client, profile_user
):
    """After using a company-specific job, a role-only letter must be clean."""
    from database.db import get_db

    with app.app_context():
        with get_db().cursor() as cursor:
            cursor.execute(
                "SELECT job_id, title, company FROM jobs ORDER BY job_id LIMIT 1"
            )
            job = cursor.fetchone()
    company = job["company"]

    # 1. Generate a company-specific letter for that job.
    specific = client.post(
        "/cover-letter/generate",
        json={"generic": True, "job_id": int(job["job_id"])},
    )
    assert specific.status_code == 200
    assert specific.get_json()["job_id"] == int(job["job_id"])

    # 2. Save it, so the saved row carries the company/job association.
    saved = client.post(
        "/cover-letter/save",
        json={"job_id": int(job["job_id"]), "content": specific.get_json()["cover_letter"]},
    )
    assert saved.status_code == 200
    letter_id = saved.get_json()["letter_id"]

    # 3. Now regenerate/generate a role-only letter. Neither path may reuse it.
    for path, body in (
        ("/cover-letter/generate", {"generic": True, "target_role": "Data Scientist"}),
        (
            "/cover-letter/regenerate",
            {"letter_id": letter_id, "generic": True, "target_role": "Data Scientist"},
        ),
    ):
        response = client.post(path, json=body)
        assert response.status_code == 200, path
        payload = response.get_json()
        letter = payload["cover_letter"]

        assert payload["job_id"] is None, f"{path} reused the saved job"
        assert company.casefold() not in letter.casefold(), f"{path} leaked {company}"
        for name in _companies_from_db(app):
            assert name.casefold() not in letter.casefold(), f"{path}: {name}"
