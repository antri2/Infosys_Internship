"""Resume Builder tailoring: role focus, instruction focus, bullet structure,
skill categories, ATS templates, and the no-fabrication guarantee.
"""
import json

from services import resume_agent


def _candidate():
    return {
        "name": "Aarav Sharma",
        "skills": ["Python", "SQL", "Excel", "Pandas", "Scikit-learn", "React", "Git"],
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
            "description": "- Cleaned sales data with Python\n- Built Excel dashboards\n- Wrote SQL reports",
        }],
        "projects": [
            {
                "title": "Document QA System",
                "description": "- Built a retrieval pipeline\n- Evaluated results with Python",
                "tech_stack": "Python, Pandas",
            },
            {
                "title": "Sales Dashboard",
                "description": "- Built reporting views for the team",
                "tech_stack": "Excel",
            },
        ],
        "certifications": [{"name": "AWS Certified Developer", "issuer": "Test Issuer"}],
        "degree": "B.Tech",
        "cgpa": 8.5,
    }


def _build(monkeypatch, role, instructions="", template="professional_ats", model=None):
    """Build a resume with the model either supplying good output or failing."""
    if model is None:
        def boom(prompt, **kwargs):
            raise RuntimeError("simulated LLM outage")
        monkeypatch.setattr(resume_agent, "generate", boom)
    else:
        monkeypatch.setattr(resume_agent, "generate", lambda *a, **k: json.dumps(model))
    tailored = resume_agent.generate_tailored_resume(
        _candidate(),
        {"title": role, "company": "", "required_skills": "", "preferred_skills": ""},
        custom_instructions=instructions,
        target_role=role,
        template=template,
    )
    return tailored, resume_agent.render_resume_text(tailored, template)


def _categories(tailored):
    return [group["label"] for group in tailored["skill_categories"]]


# --- TEST 1: Data Analyst role tailoring -----------------------------------


def test_data_analyst_role_tailors_summary_and_prioritises_data_skills(monkeypatch):
    tailored, text = _build(monkeypatch, "Data Analyst")

    assert "Data Analyst" in tailored["professional_summary"]
    # The verified analytics skills must lead the skills block.
    assert _categories(tailored)[0] == "Data & Analytics"
    assert tailored["highlighted_skills"][:3] == ["SQL", "Excel", "Pandas"]
    assert "Data Analyst" in text


# --- TEST 2: AI Engineer role tailors toward the user's actual AI skills ----


def test_ai_engineer_role_emphasises_actual_ai_skills_and_projects(monkeypatch):
    tailored, _ = _build(monkeypatch, "AI Engineer")

    assert "AI Engineer" in tailored["professional_summary"]
    labels = _categories(tailored)
    # An AI/ML or programming block must come first, and the real ML skill is
    # what makes it relevant.
    assert labels[0] in {"AI / Machine Learning", "Programming Languages"}
    assert "Scikit-learn" in tailored["highlighted_skills"]
    assert tailored["projects"][0]["title"] == "Document QA System"


def test_different_roles_produce_materially_different_resumes(monkeypatch):
    _, data_analyst = _build(monkeypatch, "Data Analyst")
    _, frontend = _build(monkeypatch, "Frontend Developer")

    assert data_analyst != frontend
    assert "Data Analyst" in data_analyst
    assert "Frontend Developer" in frontend
    assert "React" in frontend


# --- TEST 3: Custom instruction "highlight my Excel and SQL skills" --------


def test_custom_instruction_highlighting_existing_skills_reorders_them(monkeypatch):
    plain, _ = _build(monkeypatch, "Data Analyst")
    tailored, _ = _build(
        monkeypatch,
        "Data Analyst",
        instructions="Make this suitable for Data Analyst roles and highlight my Excel and SQL skills.",
    )

    assert tailored["focus_skills"] == ["Excel", "SQL"]
    assert tailored["highlighted_skills"][:2] == ["Excel", "SQL"]
    assert "Excel" in tailored["highlighted_skills"][:2]
    # The instruction must be visible, not silently dropped.
    assert plain["focus_skills"] == []


# --- TEST 4: Custom instruction "Highlight my Document QA project" ---------


def test_custom_instruction_highlighting_a_project_surfaces_it_first(monkeypatch):
    tailored, _ = _build(
        monkeypatch, "AI Engineer", instructions="Highlight my Document QA project."
    )

    assert tailored["projects"][0]["title"] == "Document QA System"


# --- TEST 5: uploaded bullet points stay bullet points ----------------------


def test_existing_bullets_are_preserved_instead_of_merged_into_a_paragraph():
    bullets = resume_agent._description_bullets(
        "• Built a retrieval pipeline\n• Evaluated with Python and Pandas"
    )

    assert bullets == ["Built a retrieval pipeline", "Evaluated with Python and Pandas"]


def test_numbered_and_wrapped_bullets_are_preserved():
    assert resume_agent._description_bullets(
        "1. First item\n2. Second item"
    ) == ["First item", "Second item"]
    assert resume_agent._description_bullets(
        "• Bullet that wraps\n  onto a second line\n• Second bullet"
    ) == ["Bullet that wraps onto a second line", "Second bullet"]


def test_generated_resume_uses_dash_bullets_per_source_line(monkeypatch):
    _, text = _build(monkeypatch, "Data Analyst")

    projects = text.split("PROJECTS\n")[1].split("\n\nEDUCATION")[0]
    assert "- Built a retrieval pipeline" in projects
    assert "- Evaluated results with Python" in projects
    experience = text.split("EXPERIENCE\n")[1].split("\n\n")[0]
    assert "- Cleaned sales data with Python" in experience
    assert "- Wrote SQL reports" in experience


# --- TEST 6: categorised skills --------------------------------------------


def test_skills_are_grouped_into_categories_and_never_invented(monkeypatch):
    tailored, text = _build(monkeypatch, "Data Analyst")

    assert "Data & Analytics:" in text
    assert "Programming Languages:" in text
    # Every listed skill must exist in the profile.
    for group in tailored["skill_categories"]:
        for skill in group["skills"]:
            assert skill in _candidate()["skills"]


# --- TEST 7: templates -----------------------------------------------------


def test_all_ats_templates_are_available_and_ordered():
    expected = {
        "professional_ats", "chronological", "skills_first", "modern_ats",
        "technical_ats", "minimal_ats", "entry_level_ats",
    }
    assert expected == set(resume_agent.TEMPLATES)
    assert set(resume_agent.TEMPLATE_ORDER) == expected
    assert resume_agent.TEMPLATE_ORDER[0] == "professional_ats"
    for item in resume_agent.TEMPLATES.values():
        assert item["label"] and item["description"]
        # Only plain-text section keys are allowed.
        assert set(item["section_order"]) <= {
            "professional_summary", "skills", "experience", "projects", "education",
        }


def test_templates_change_section_order_but_not_the_facts(monkeypatch):
    monkeypatch.setattr(
        resume_agent, "generate",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")),
    )
    rendered = {}
    for key in resume_agent.TEMPLATE_ORDER:
        tailored, rendered[key] = _build(monkeypatch, "Data Analyst", template=key)

    orders = {
        key: [name for name in resume_agent.TEMPLATES[key]["section_order"]]
        for key in resume_agent.TEMPLATE_ORDER
    }
    assert len({tuple(value) for value in orders.values()}) > 1

    facts = ("Aarav Sharma", "Document QA System", "Cleaned sales data with Python")
    for key, text in rendered.items():
        for fact in facts:
            assert fact in text, f"{key} lost {fact}"

    # "Minimal ATS" deliberately omits the summary section.
    assert "PROFESSIONAL SUMMARY" not in rendered["minimal_ats"]
    assert "PROFESSIONAL SUMMARY" in rendered["professional_ats"]


def test_templates_stay_ats_friendly(monkeypatch):
    for key in resume_agent.TEMPLATE_ORDER:
        _, text = _build(monkeypatch, "Data Analyst", template=key)
        for banned in ("%", "█", "▓", "|---", "http://", "https://"):
            assert banned not in text, f"{key} contains {banned!r}"
        # Single column: no pipe-aligned table scaffolding.
        assert text.count("\t") == 0


# --- TEST 8: no fabrication ------------------------------------------------


def test_model_cannot_fabricate_skills_in_the_skill_list(monkeypatch):
    model = {
        "professional_summary": "Data analyst.",
        "highlighted_skills": ["SQL", "Power BI", "Tableau", "AWS", "Kibana"],
        "projects": [],
        "keyword_alignment": ["SQL", "Power BI"],
    }
    tailored, _ = _build(monkeypatch, "Data Analyst", model=model)

    for invented in ("Power BI", "Tableau", "AWS", "Kibana"):
        assert invented not in tailored["highlighted_skills"]
    assert tailored["highlighted_skills"][:4] == ["SQL", "Excel", "Pandas", "Python"]


def test_model_cannot_sneak_a_fabricated_tool_into_the_wording(monkeypatch):
    model = {
        "professional_summary": "Data Analyst with Power BI, Tableau and Kibana dashboards.",
        "highlighted_skills": ["SQL"],
        "projects": [{
            "title": "Document QA System",
            "tech_stack": "Python",
            "bullets": ["Built dashboards with Power BI.", "Built a retrieval pipeline with Python."],
        }],
        "keyword_alignment": ["SQL"],
    }
    tailored, text = _build(monkeypatch, "Data Analyst", model=model)

    # The summary fell back to the deterministic one, so no fabricated tool
    # survived there.
    summary = text.split("PROFESSIONAL SUMMARY\n")[1].split("\n\n")[0].casefold()
    for invented in ("power bi", "tableau", "kibana"):
        assert invented not in summary
    # The fabricated bullet was dropped while the factual one was kept.
    project_block = text.split("PROJECTS\n")[1].casefold()
    assert "power bi" not in project_block
    assert "built a retrieval pipeline with python." in project_block


def test_verified_certification_name_is_not_treated_as_fabrication(monkeypatch):
    """A real certification may legitimately contain a technology-like word."""
    model = {
        "professional_summary": "Data analyst with dashboards.",
        "highlighted_skills": ["SQL"],
        "projects": [],
        "keyword_alignment": ["SQL"],
    }
    _, text = _build(monkeypatch, "Data Analyst", model=model)

    assert "AWS Certified Developer" in text


def test_emphasising_a_skill_the_user_does_not_have_adds_nothing(monkeypatch):
    tailored, text = _build(
        monkeypatch, "Data Analyst", instructions="Emphasize Power BI and Tableau."
    )

    assert tailored["focus_skills"] == []
    lowered = text.casefold()
    assert "power bi" not in lowered
    assert "tableau" not in lowered


def test_model_cannot_fabricate_metrics(monkeypatch):
    model = {
        "professional_summary": "Improved reporting efficiency by 40%.",
        "highlighted_skills": ["SQL"],
        "projects": [{
            "title": "Document QA System",
            "tech_stack": "Python",
            "bullets": ["Reduced latency by 35% for 5000 users."],
        }],
        "keyword_alignment": [],
    }
    _, text = _build(monkeypatch, "Data Analyst", model=model)

    assert "40%" not in text
    assert "35%" not in text
    assert "5000" not in text


# --- TEST 9: job-description tailoring -------------------------------------


def test_supplied_job_requirements_tailor_without_inventing(monkeypatch):
    monkeypatch.setattr(
        resume_agent, "generate",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")),
    )
    job = {
        "title": "Data Analyst",
        "company": "ABC Technologies",
        "required_skills": "SQL, Excel, Power BI, Python",
        "preferred_skills": "Tableau",
    }
    tailored = resume_agent.generate_tailored_resume(
        _candidate(), job, custom_instructions="", target_role="Data Analyst",
        template="professional_ats",
    )
    text = resume_agent.render_resume_text(tailored, "professional_ats")

    # The JD skills the user actually has are surfaced first.
    assert tailored["highlighted_skills"][:2] == ["SQL", "Excel"]
    assert "Python" in tailored["highlighted_skills"][:4]
    # The JD skills the user lacks are never claimed.
    lowered = text.casefold()
    assert "power bi" not in lowered
    assert "tableau" not in lowered


# --- section structure -----------------------------------------------------


def test_resume_has_ordered_sections_and_no_empty_blocks(monkeypatch):
    _, text = _build(monkeypatch, "Data Analyst")
    head = text.split("\n", 1)[0]
    assert head == "Aarav Sharma"
    assert "PROFESSIONAL SUMMARY" in text
    assert "SKILLS" in text
    assert "PROJECTS" in text
    assert "EDUCATION" in text
    assert "CERTIFICATIONS" in text
    # CGPA comes from the profile record and must survive.
    assert "CGPA: 8.5" in text
    # No double blank lines / trailing whitespace artefacts.
    assert "\n\n\n" not in text
    assert not any(line != line.rstrip() for line in text.splitlines())


def test_missing_optional_sections_are_omitted_entirely(monkeypatch):
    def boom(prompt, **kwargs):
        raise RuntimeError("down")
    monkeypatch.setattr(resume_agent, "generate", boom)
    tailored = resume_agent.generate_tailored_resume(
        {
            "name": "Fresher",
            "skills": ["Python"],
            "education": [],
            "experience": [],
            "projects": [],
            "certifications": [],
        },
        {"title": "Software Engineer", "company": ""},
        custom_instructions="",
        target_role="Software Engineer",
    )
    text = resume_agent.render_resume_text(tailored, "professional_ats")

    for absent in ("EXPERIENCE", "PROJECTS", "EDUCATION", "CERTIFICATIONS"):
        assert absent not in text
    assert "SKILLS" in text


# ---------------------------------------------------------------------------
# Regression: a multi-request custom instruction must be parsed per clause.
# ---------------------------------------------------------------------------

REPORTED_INSTRUCTION = (
    "Make my resume suitable for software engineer role. Add project Book "
    "Recommendation System. Add description: developed a website that recommends "
    "books according to the genre and name of the author and suggests similar "
    "books to reader."
)


def _software_candidate():
    return {
        "name": "Aarav Sharma",
        "skills": [
            "Python", "SQL", "MySQL", "Git", "Docker", "Linux",
            "Scikit-learn", "Pandas", "FAISS", "OOP", "DSA", "DBMS",
        ],
        "projects": [{
            "title": "Document QA System",
            "description": "- Built a retrieval pipeline\n- Evaluated results with Python",
            "tech_stack": "Python, FAISS",
        }],
        "experience": [{
            "title": "Data Analyst Intern",
            "organization": "Acme",
            "start_date": "2025",
            "end_date": "2025",
            "description": "- Cleaned sales data with Python\n- Wrote SQL reports",
        }],
        "education": [{"institution": "TU", "degree": "B.Tech"}],
        "certifications": [],
    }


def test_multi_request_instruction_is_split_into_separate_clauses():
    updates = resume_agent.parse_user_updates(REPORTED_INSTRUCTION)

    assert len(updates["projects"]) == 1
    project = updates["projects"][0]
    # The title must be only the project name, not the rest of the paragraph.
    assert project["title"] == "Book Recommendation System"
    # The trailing sentence must become the description, not part of the title.
    assert project["description"].startswith("developed a website that recommends books")
    assert "Add description" not in project["title"]
    # No technology was supplied, so none may be recorded.
    assert not project["tech_stack"]


def test_reported_instruction_produces_a_proper_project_entry(monkeypatch):
    monkeypatch.setattr(
        resume_agent, "generate",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")),
    )
    tailored = resume_agent.generate_tailored_resume(
        _software_candidate(),
        {"title": "Software Engineer", "company": ""},
        custom_instructions=REPORTED_INSTRUCTION,
        target_role="Software Engineer",
        template="technical_ats",
    )
    text = resume_agent.render_resume_text(tailored, "technical_ats")
    projects = text.split("PROJECTS\n")[1].split("\n\nEDUCATION")[0]

    # The new project is a real PROJECTS entry with bullets, not loose text.
    assert "Book Recommendation System" in projects
    assert projects.count("- ") >= 3
    # No instruction wording may leak into the resume at all.
    for leaked in ("Add project", "Add description", "suitable for software engineer role"):
        assert leaked not in text
    # No technology may be invented for it.
    assert "Book Recommendation System |" not in projects
    # The existing project keeps its structure and tech stack.
    assert "Document QA System | Python, FAISS" in projects
    assert "- Built a retrieval pipeline" in projects


def test_software_engineer_role_prioritises_coding_skills_without_dropping_ai(monkeypatch):
    monkeypatch.setattr(
        resume_agent, "generate",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")),
    )
    tailored = resume_agent.generate_tailored_resume(
        _software_candidate(),
        {"title": "Software Engineer", "company": ""},
        custom_instructions=REPORTED_INSTRUCTION,
        target_role="Software Engineer",
        template="technical_ats",
    )
    labels = [group["label"] for group in tailored["skill_categories"]]

    assert labels[0] in {"Computer Science Fundamentals", "Tools & Platforms"}
    # Existing AI/ML experience is preserved, not removed.
    flat = [s for g in tailored["skill_categories"] for s in g["skills"]]
    for kept in ("Scikit-learn", "FAISS", "Pandas", "Python", "SQL"):
        assert kept in flat
    # Skills are still grouped, not dumped into one paragraph.
    assert len(labels) >= 3


def test_bare_add_of_a_named_system_is_treated_as_a_project():
    updates = resume_agent.parse_user_updates(
        "Add Book Recommendation System. Add description: recommends books by genre."
    )

    assert [p["title"] for p in updates["projects"]] == ["Book Recommendation System"]
    assert updates["skills"] == []


def test_bare_add_of_a_real_skill_is_still_treated_as_a_skill():
    for phrase in ("Add Kubernetes", "Add Machine Learning", "Add PyTorch"):
        updates = resume_agent.parse_user_updates(phrase)
        assert updates["projects"] == []
        assert len(updates["skills"]) == 1, phrase


def test_legacy_instruction_forms_still_parse():
    assert resume_agent.parse_user_updates(
        "Add TensorFlow to my skills"
    )["skills"] == ["TensorFlow"]

    piped = resume_agent.parse_user_updates(
        "Add project: My Project | Short description | Python, SQL"
    )["projects"][0]
    assert piped == {
        "title": "My Project",
        "description": "Short description",
        "tech_stack": "Python, SQL",
    }

    multiline = resume_agent.parse_user_updates(
        "Add Python to my skills\nHighlight my IISER internship\n"
        "Add project: Second | Another description"
    )
    assert multiline["skills"] == ["Python"]
    assert multiline["projects"][0]["title"] == "Second"


def test_sentence_splitting_does_not_break_decimals_or_abbreviations():
    updates = resume_agent.parse_user_updates(
        "Improve my resume. I scored 3.5 CGPA. Add project Alpha Tool | A description here"
    )
    assert updates["projects"][0]["title"] == "Alpha Tool"
    assert updates["projects"][0]["description"] == "A description here"


def test_long_single_sentence_description_becomes_several_bullets():
    bullets = resume_agent._description_bullets(
        "developed a website that recommends books according to the genre and name "
        "of the author and suggests similar books to reader."
    )

    assert len(bullets) == 2
    # "genre and name" must not be split; "and suggests" is the real boundary.
    assert "genre and name of the author" in bullets[0]
    assert bullets[1].startswith("suggests")


def test_user_added_project_without_details_is_not_fabricated(monkeypatch):
    monkeypatch.setattr(
        resume_agent, "generate",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")),
    )
    tailored = resume_agent.generate_tailored_resume(
        _software_candidate(),
        {"title": "Software Engineer", "company": ""},
        custom_instructions="Add project Book Recommendation System",
        target_role="Software Engineer",
        template="technical_ats",
    )
    text = resume_agent.render_resume_text(tailored, "technical_ats")
    projects = text.split("PROJECTS\n")[1].split("\n\nEDUCATION")[0]

    assert "Book Recommendation System" in projects
    # A placeholder is shown rather than an invented responsibility.
    assert "to be completed by the user" in projects
    assert "Book Recommendation System |" not in projects


def test_case_a_highlight_existing_project(monkeypatch):
    monkeypatch.setattr(
        resume_agent, "generate",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")),
    )
    tailored = resume_agent.generate_tailored_resume(
        _software_candidate(),
        {"title": "Data Analyst", "company": ""},
        custom_instructions="Highlight my Document QA project.",
        target_role="Data Analyst",
    )

    assert tailored["projects"][0]["title"] == "Document QA System"


def test_case_b_role_only_instruction_adds_no_records():
    updates = resume_agent.parse_user_updates(
        "Make my resume suitable for Data Analyst roles."
    )

    assert updates == {"skills": [], "projects": [], "experience": []}


# ---------------------------------------------------------------------------
# Multi-skill additions: every named skill is a separate entry.
# ---------------------------------------------------------------------------


def test_reported_multi_skill_wording_is_split_into_separate_skills():
    updates = resume_agent.parse_user_updates("Add HTML, CSS and JavaScript in skills.")

    assert updates["skills"] == ["HTML", "CSS", "JavaScript"]
    assert updates["projects"] == []


def test_multi_skill_wording_works_for_every_target_phrase():
    for target in ("in skills.", "to my skills", "into my skills", "under skills"):
        updates = resume_agent.parse_user_updates(f"Add HTML, CSS and JavaScript {target}")
        assert updates["skills"] == ["HTML", "CSS", "JavaScript"], target


def test_multi_skill_separators_all_split():
    cases = {
        "Add HTML, CSS and JavaScript in skills": ["HTML", "CSS", "JavaScript"],
        "Add React/Node.js/Bootstrap in skills": ["React", "Node.js", "Bootstrap"],
        "Add Python, SQL/React and Docker in skills": ["Python", "SQL", "React", "Docker"],
        "Add HTML & CSS in skills": ["HTML", "CSS"],
        "Add skills: HTML, CSS and JavaScript": ["HTML", "CSS", "JavaScript"],
        "Add HTML, CSS and JavaScript": ["HTML", "CSS", "JavaScript"],
    }
    for instruction, expected in cases.items():
        updates = resume_agent.parse_user_updates(instruction)
        assert updates["skills"] == expected, instruction
        assert updates["projects"] == [], instruction


def test_skill_names_are_normalised_individually():
    updates = resume_agent.parse_user_updates("Add javascript, nodejs and css in skills")

    # Normalised casing per item, not one merged string.
    assert updates["skills"] == ["JavaScript", "Node.js", "CSS"]
    assert all("," not in skill for skill in updates["skills"])


def test_added_skills_render_as_separate_bullets_in_one_category(monkeypatch):
    monkeypatch.setattr(
        resume_agent, "generate",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")),
    )
    tailored = resume_agent.generate_tailored_resume(
        {
            "name": "Aarav Sharma",
            "skills": ["Python", "SQL"],
            "projects": [],
            "experience": [],
            "education": [],
            "certifications": [],
        },
        {"title": "Frontend Developer", "company": ""},
        custom_instructions="Add HTML, CSS and JavaScript in skills.",
        target_role="Frontend Developer",
        template="technical_ats",
    )
    text = resume_agent.render_resume_text(tailored, "technical_ats")
    skills_block = text.split("SKILLS\n")[1].split("\n\nPROFESSIONAL")[0]

    # One bullet per skill, all under a single existing category.
    assert "Web & UI:" in skills_block
    for skill in ("HTML", "CSS", "JavaScript"):
        assert f"- {skill}\n" in skills_block
    # Never merged into a single entry.
    assert "- HTML, CSS" not in skills_block
    for group in tailored["skill_categories"]:
        assert not any("," in skill for skill in group["skills"])


def test_only_explicitly_requested_skills_are_added(monkeypatch):
    monkeypatch.setattr(
        resume_agent, "generate",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")),
    )
    tailored = resume_agent.generate_tailored_resume(
        {
            "name": "Aarav Sharma",
            "skills": ["Python"],
            "projects": [],
            "experience": [],
            "education": [],
            "certifications": [],
        },
        {"title": "Frontend Developer", "company": ""},
        custom_instructions="Add HTML in skills.",
        target_role="Frontend Developer",
    )
    flat = [s for g in tailored["skill_categories"] for s in g["skills"]]

    assert flat == ["HTML", "Python"]
    # No related technology may be inferred from the target role.
    for unrequested in ("React", "Node.js", "Bootstrap", "TypeScript", "CSS", "JavaScript"):
        assert unrequested not in flat


def test_multi_skill_parsing_does_not_capture_the_trailing_target_as_a_skill():
    updates = resume_agent.parse_user_updates("Add Python, SQL in my skill list")

    assert updates["skills"] == ["Python", "SQL"]


def test_skill_category_mapping_is_deterministic():
    lookup = resume_agent._SKILL_CATEGORY_LOOKUP
    key = resume_agent.skill_comparison_key
    expected = {
        "HTML": "Web & UI",
        "CSS": "Web & UI",
        "JavaScript": "Web & UI",
        "React": "Web & UI",
        "SQL": "Data & Analytics",
        "Python": "Programming Languages",
        "Git": "Tools & Platforms",
        "Docker": "Tools & Platforms",
        "DSA": "Computer Science Fundamentals",
        "OOP": "Computer Science Fundamentals",
    }
    for skill, label in expected.items():
        assert lookup.get(key(skill)) == label, skill


def test_duplicate_skills_are_collapsed_case_insensitively():
    updates = resume_agent.parse_user_updates("Add HTML, html and Html in skills")

    assert updates["skills"] == ["HTML"]
