"""Deterministic requirement extraction for live job text.

The important property is that nothing is ever invented. These tests pin both
halves of that: real requirements are recovered from real text, and ordinary
prose never turns into a fabricated requirement.

The regression cases matter as much as the happy paths -- an earlier version of
the degree regexes turned the English word "be" into a "B.E." requirement and
"TensorFlow JS" into "JavaScript". Both are covered below so they cannot return.
"""

import pytest

from services.job_requirements import (
    classify_segments,
    extract_education,
    extract_experience,
    extract_requirements,
    find_skills,
    infer_job_type,
)


# ------------------------------------------------------------------- skills ---


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Python and SQL required", {"Python", "SQL"}),
        ("Experience with Power BI preferred", {"Power BI"}),
        ("Strong knowledge of Python, machine learning and TensorFlow", {"Python", "Machine Learning", "TensorFlow"}),
        ("Familiarity with Docker, Kubernetes and AWS", {"Docker", "Kubernetes", "AWS"}),
        ("Tableau, Excel, Pandas and NumPy", {"Tableau", "Excel", "Pandas", "NumPy"}),
        ("Deep learning with PyTorch and computer vision", {"Deep Learning", "PyTorch", "Computer Vision"}),
        ("No technology whatsoever mentioned here", set()),
    ],
)
def test_finds_only_literally_present_skills(text, expected):
    assert set(find_skills(text)) == expected


@pytest.mark.parametrize(
    "text,must_not_contain",
    [
        # "be" is an English word, not a B.E. degree.
        ("You will be responsible for optimizing system performance.", {"B.E."}),
        # "me" is an English word, not an M.E. degree.
        ("Send me an email if you are interested.", {"M.E."}),
        # Nothing here is a degree at all.
        ("We are looking for a highly capable engineer.", {"B.E.", "M.E.", "B.Tech", "MBA"}),
    ],
)
def test_prose_never_becomes_a_degree(text, must_not_contain):
    assert not (must_not_contain & set(find_skills(text)))
    assert extract_education(text) == ""


def test_case_sensitive_tokens_do_not_match_inside_words():
    # "AI" must not fire inside "said", "SAP" inside "sappy", "NLP" inside "help".
    assert find_skills("he said the sapper needed help") == []


def test_javascript_is_not_inferred_from_tensorflow_js():
    """"TensorFlow JS" is TensorFlow's JS build, not evidence of JavaScript."""
    text = "You will be working with technologies like TensorFlow JS, TensorFlow and Keras."
    found = find_skills(text)
    assert "TensorFlow" in found
    assert "JavaScript" not in found


def test_skills_are_deduplicated_case_insensitively():
    text = "Python python PYTHON and Python"
    assert find_skills(text).count("Python") == 1


# ------------------------------------------------ required vs preferred ---


def test_classifies_required_and_preferred_sections():
    description = (
        "About the role\n"
        "You will be working on our platform.\n"
        "Requirements:\n"
        "- Strong Python and SQL experience\n"
        "- Familiarity with Docker\n"
        "Preferred:\n"
        "- Tableau experience is a plus\n"
        "- AWS certification preferred\n"
    )
    required, preferred, saw_cues = classify_segments(description)
    assert saw_cues is True
    required_text = " ".join(required)
    preferred_text = " ".join(preferred)
    assert "Python" in required_text
    assert "Docker" in required_text
    assert "Tableau" in preferred_text
    assert "AWS" in preferred_text


def test_required_and_preferred_are_separated():
    result = extract_requirements(
        "Data Analyst",
        "Requirements: Python and SQL are required. Preferred: Power BI is preferred.",
        {},
    )
    required = [s.strip() for s in result["required_skills"].split(",") if s.strip()]
    preferred = [s.strip() for s in result["preferred_skills"].split(",") if s.strip()]
    assert "Python" in required and "SQL" in required
    assert "Power BI" in preferred
    assert "Power BI" not in required


def test_no_section_cues_reports_skills_as_requirements():
    """Without cues we do not pretend the posting distinguished anything."""
    result = extract_requirements(
        "Engineer",
        "You will work with Python and Kafka on our billing platform.",
        {},
    )
    assert "Python" in result["required_skills"]
    assert "Kafka" in result["required_skills"]
    assert result["preferred_skills"] == ""


def test_skills_in_the_title_are_requirements():
    result = extract_requirements("Power BI Analyst", "", {})
    assert "Power BI" in result["required_skills"]


def test_a_posting_with_no_requirements_yields_empty_fields():
    """An employer-boilerplate posting must report nothing, not guess.

    The title is deliberately neutral: a title such as "Data Analyst" would
    legitimately yield "Data Analysis" from its own text.
    """
    result = extract_requirements(
        "Business Operations Associate",
        "This job is with Kyndryl, an inclusive employer and a member of myGwork. "
        "We run mission-critical technology systems for the world's leading businesses.",
        {},
    )
    assert result["required_skills"] == ""
    assert result["preferred_skills"] == ""
    assert result["experience_required"] == ""
    assert result["education_required"] == ""


def test_all_preferred_skills_are_promoted_so_skill_gap_still_works():
    """Otherwise Skill Gap would report 'no missing skills' for every live job."""
    result = extract_requirements(
        "Engineer",
        "Nice to have: Python and Docker experience.",
        {},
    )
    assert result["preferred_skills"] == ""
    assert "Python" in result["required_skills"]
    assert "Docker" in result["required_skills"]


# ------------------------------------------------------------- experience ---


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Python with Spark Developer (5.1-7 years)", "5.1-7 years"),
        ("3+ years of experience in analytics", "3+ years"),
        ("We need 4 years of Python coding", "4 years"),
        ("0-2 years of experience to join our team", "0-2 years"),
        ("1 to 3 years in a similar role", "1-3 years"),
        ("Freshers may apply", "Fresher"),
        ("Entry-level position available", "Fresher"),
        ("Graduate trainee role", "Fresher"),
    ],
)
def test_experience_extraction(text, expected):
    assert extract_experience(text) == expected


def test_experience_absent_stays_empty():
    assert extract_experience("We need a curious team player.") == ""
    assert extract_experience("") == ""


def test_experience_is_taken_from_the_title_when_present():
    result = extract_requirements("Python with Spark Developer (5.1-7 years)-Chennai", "", {})
    assert result["experience_required"] == "5.1-7 years"


# --------------------------------------------------------------- education ---


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Candidates must hold a B.Tech degree", "B.Tech"),
        ("B.E. in Computer Science is required", "B.E."),
        ("MBA preferred", "MBA"),
        ("MCA holders can apply", "Master's degree"),
        ("Bachelor's degree required", "Bachelor's degree"),
        ("Master's degree in Computer Science", "Master's degree in Computer Science"),
        ("Diploma in engineering", "Diploma"),
        ("Must be a 12th pass", "12th / Higher Secondary"),
    ],
)
def test_education_extraction(text, expected):
    assert extract_education(text) == expected


def test_education_absent_stays_empty():
    """A category such as 'IT Jobs' must never become an education requirement."""
    assert extract_education("Engineering Jobs") == ""
    assert extract_education("IT Jobs") == ""
    assert extract_education("Sales Jobs") == ""


def test_category_label_is_not_used_as_education():
    result = extract_requirements(
        "Data Analyst / Engineer",
        "This job is with an inclusive employer. We run mission critical systems.",
        {"contract_time": "full_time", "category": {"label": "IT Jobs"}},
    )
    assert result["education_required"] == ""


# --------------------------------------------------------------- job type ---


@pytest.mark.parametrize(
    "raw,title,expected",
    [
        ({"contract_time": "full_time"}, "", "Full Time"),
        ({"contract_time": "part_time"}, "", "Part Time"),
        ({"contract_type": "permanent"}, "", "Permanent"),
        ({"contract_time": "full_time", "contract_type": "permanent"}, "", "Full Time / Permanent"),
        ({}, "Marketing Internship", "Internship"),
        ({}, "Graduate Trainee Programme", "Trainee"),
        ({}, "Senior Engineer", ""),
    ],
)
def test_job_type_comes_from_contract_fields_or_title(raw, title, expected):
    assert infer_job_type(raw, title) == expected


def test_job_type_is_never_the_word_live():
    result = extract_requirements("Data Analyst", "", {})
    assert "live" not in result["job_type"].lower()


# -------------------------------------------------------------- end-to-end ---


def test_matches_the_adzuna_response_the_service_receives():
    """Shape taken from a real Adzuna India search result."""
    raw = {
        "id": "5855006986",
        "title": "Senior Power BI Analyst / Developer (Azure Cloud)",
        "company": {"display_name": "TopGrep"},
        "location": {"display_name": "Bengaluru"},
        "description": (
            "Job Description We are hiring a senior analyst. "
            "Requirements: 4+ years with Power BI, strong SQL and DAX. "
            "Preferred: Azure and experience with ETL Pipelines."
        ),
        "category": {"label": "IT Jobs"},
        "contract_time": "full_time",
        "contract_type": None,
    }
    result = extract_requirements(raw["title"], raw["description"], raw)

    required = [s.strip() for s in result["required_skills"].split(",") if s.strip()]
    preferred = [s.strip() for s in result["preferred_skills"].split(",") if s.strip()]
    assert {"Power BI", "SQL"} <= set(required)
    # "Azure" appears in the title, and a title skill is always a requirement.
    assert "Azure" in required
    # "ETL Pipelines" is named in the preferred section of the description.
    assert "ETL" in preferred
    assert result["experience_required"] == "4+ years"
    assert result["job_type"] == "Full Time"
    assert result["education_required"] == ""
