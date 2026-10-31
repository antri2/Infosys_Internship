"""Resume Agent: custom instructions, factual grounding, and ATS formatting.

The reported symptoms were that the Resume Agent repeated existing content,
ignored custom instructions, and added generic AI filler. These tests pin the
fixes for each of those rather than the whole generation pipeline.
"""
import pytest

from services import resume_agent as R


# ------------------------------------------------------- custom instructions ---

@pytest.mark.parametrize("instruction, expected_project", [
    ("Add a project called Sales Dashboard", "Sales Dashboard"),
    ("Add project called Sales Dashboard", "Sales Dashboard"),
    ("Add the project Sales Dashboard", "Sales Dashboard"),
    ("Add project: Sales Dashboard", "Sales Dashboard"),
    ("Include a project named Portfolio Website", "Portfolio Website"),
])
def test_project_instructions_are_parsed_with_and_without_articles(instruction, expected_project):
    """`Add a project called X` used to match nothing at all.

    The article before "project" was not optional in the pattern, so the most
    natural phrasing of the instruction was silently dropped.
    """
    updates = R.parse_user_updates(instruction)
    assert [p["title"] for p in updates["projects"]] == [expected_project]


@pytest.mark.parametrize("instruction, title, org", [
    ("Add an internship at Infosys as Data Analyst Intern",
     "Data Analyst Intern", "Infosys"),
    ("Add an internship Data Analyst Intern at Infosys",
     "Data Analyst Intern", "Infosys"),
    ("Add internship: Data Analyst Intern | Infosys | Built reports",
     "Data Analyst Intern", "Infosys"),
    ("Add an experience entry called Data Analyst Intern at Acme",
     "Data Analyst Intern", "Acme"),
])
def test_experience_instructions_separate_role_and_employer(instruction, title, org):
    """`at Infosys as X` used to produce a record titled "at Infosys as X"."""
    updates = R.parse_user_updates(instruction)
    assert len(updates["experience"]) == 1
    record = updates["experience"][0]
    assert record["title"] == title
    assert record["organization"] == org


def test_multiple_instructions_in_one_paragraph_are_all_applied():
    updates = R.parse_user_updates(
        "Make my resume suitable for a data analyst role. "
        "Add a project called Sales Dashboard. "
        "Add description: Built dashboards in Power BI."
    )
    assert [p["title"] for p in updates["projects"]] == ["Sales Dashboard"]
    assert updates["projects"][0]["description"] == "Built dashboards in Power BI."


def test_skill_instructions_still_parse():
    updates = R.parse_user_updates("Add React, Redux to my skills")
    assert updates["skills"] == ["React", "Redux"]


def test_a_user_supplied_project_reaches_the_generated_resume():
    """An explicitly supplied project is real content, not padding."""
    candidate = {
        "name": "Anchal Tripathi",
        "college": "AKS University", "degree": "B.Tech", "cgpa": 8.66,
        "skills": ["Python", "SQL"],
        "education": [{"institution": "AKS University", "degree": "B.Tech"}],
        "experience": [], "projects": [], "certifications": [],
    }
    updates = R.parse_user_updates("Add a project called Sales Dashboard")
    enriched = R._candidate_with_user_updates(candidate, updates)

    assert any(p["title"] == "Sales Dashboard" for p in enriched["projects"])


# -------------------------------------------------------- factual grounding ---

SENIORITY_CLAIMS = [
    "Seasoned Data Analyst with hands-on reporting experience.",
    "Senior machine learning engineer with production ownership.",
    "Expert in Python and SQL across large deployments.",
    "Extensive experience leading cross-functional teams.",
    "Proficient in advanced statistical modelling.",
]


@pytest.mark.parametrize("claim", SENIORITY_CLAIMS)
def test_unsupported_seniority_is_rejected(claim):
    """A final-year student must not be described as seasoned or expert.

    Seniority words carry an experience claim just as much as a number does, and
    none of them contain a digit, so the existing numeric guard never saw them.
    """
    source = "python sql b.tech aks university"
    assert R._has_unverified_claim(claim, source) is True


def test_seniority_is_allowed_when_the_profile_uses_that_word():
    source = "seasoned engineer python sql b.tech"
    assert R._has_unverified_claim("Seasoned engineer.", source) is False


@pytest.mark.parametrize("claim, source", [
    ("Improved revenue by 30%", "python sql"),
    ("Won an award for best project", "python sql"),
    ("3 years of experience in SQL", "python sql"),
    ("Served 10,000 users", "python sql"),
])
def test_unverified_claims_are_still_rejected(claim, source):
    assert R._has_unverified_claim(claim, source) is True


def test_verified_facts_are_not_rejected():
    source = "built dashboards python sql b.tech aks university"
    assert R._has_unverified_claim("Built dashboards with Python and SQL.", source) is False


def test_unverified_technology_is_still_rejected_in_bullets():
    """A named tool the profile does not have is still blocked."""
    candidate = {"skills": ["Python", "SQL"], "projects": [], "experience": [],
                 "certifications": [], "education": []}
    verified = R._verified_technology_keys(candidate)
    assert R._unverified_technologies("Built charts in Tableau.", verified)
    assert not R._unverified_technologies("Built charts with Python.", verified)


# ---------------------------------------------------------------- formatting ---

def _section_headings(text: str) -> list[str]:
    """Upper-case standalone lines that are section headings, not content."""
    headings = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or not stripped.isupper():
            continue
        if stripped.startswith("- ") or ":" in stripped:
            continue        # a bullet, or a "CGPA: 8.66" style detail line
        headings.append(stripped)
    return headings


def _resume(**overrides):
    tailored = {
        "name": "Anchal Tripathi",
        "professional_summary": "Data Analyst with Python and SQL experience.",
        "cgpa": "8.66",
        "highlighted_skills": ["Python", "SQL", "Power BI"],
        "skill_categories": [{"label": "Programming", "skills": ["Python", "SQL"]},
                             {"label": "Analytics", "skills": ["Power BI"]}],
        "experience": [{"title": "Data Analyst Intern", "organization": "Infosys",
                        "start_date": "2025-06", "end_date": "2025-08",
                        "bullets": ["Built Power BI dashboards",
                                    "Wrote SQL reports for stakeholders"]}],
        "projects": [{"title": "Resume Ranker", "tech_stack": "Python, FAISS",
                      "bullets": ["Built a FAISS screening tool"]}],
        "education": [{"degree": "B.Tech", "institution": "AKS University",
                       "start_date": "2022", "end_date": "2026"}],
        "certifications": [{"name": "AWS Certified Developer", "issuer": "Amazon"}],
        "template": "professional_ats",
    }
    tailored.update(overrides)
    return tailored


def test_ats_layout_has_consistent_sections_and_bullets():
    text = R.render_resume_text(_resume(), "professional_ats")

    # Section headings are whole upper-case lines, in the template's order.
    assert _section_headings(text) == [
        "PROFESSIONAL SUMMARY", "SKILLS", "EXPERIENCE", "PROJECTS",
        "EDUCATION", "CERTIFICATIONS"]

    # Bullets use one consistent marker.
    assert "- Built Power BI dashboards" in text
    assert "•" not in text and "* " not in text
    # No more than one blank line between blocks.
    assert "\n\n\n" not in text


def test_ats_layout_preserves_dates_and_names():
    text = R.render_resume_text(_resume(), "professional_ats")
    assert "Anchal Tripathi" in text
    assert "Infosys" in text
    assert "2025-06 - 2025-08" in text or "2025-06 - 2025-08" in text
    assert "Resume Ranker" in text
    assert "AWS Certified Developer" in text
    assert "CGPA: 8.66" in text


def test_existing_templates_still_render():
    """Every stored template keeps rendering, with its own section order.

    Headings are rendered in each template's own casing, so the order is checked
    by position rather than by string equality.
    """
    for key in R.TEMPLATE_ORDER:
        text = R.render_resume_text(_resume(), key)
        assert "Anchal Tripathi" in text

        sections = list(R.TEMPLATES[key]["section_order"])
        if "certifications" not in sections:
            sections.append("certifications")   # always appended last

        # render_resume_text passes the display name, not the section key.
        display = {
            "professional_summary": "Professional Summary",
            "skills": "Skills",
            "experience": "Experience",
            "projects": "Projects",
            "education": "Education",
            "certifications": "Certifications",
        }
        rendered = [
            R._plain_heading(display[section], R.TEMPLATES[key])
            for section in sections
        ]
        positions = []
        for heading in rendered:
            index = text.find(heading)
            assert index != -1, f"{key}: missing heading {heading!r}"
            positions.append(index)
        assert positions == sorted(positions), f"{key}: sections out of order"


# ------------------------------------------------------------------- budget ---

def test_token_budget_leaves_room_for_the_payload():
    """A reasoning model needs a budget big enough for reasoning plus content."""
    assert R.RESUME_MAX_TOKENS >= 4000