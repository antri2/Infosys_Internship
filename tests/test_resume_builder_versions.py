"""Resume Builder: multiple versions, section editing, preview and downloads.

Everything asserted here was implemented in this change:

  * role-based generation that produces materially different resumes, ordered
    by real project relevance rather than by project title alone;
  * a fallback summary that reads professionally and never narrates the
    generator's own behaviour;
  * structured section editing with add / remove / reorder;
  * independent saved versions with rename and delete, ownership-scoped;
  * a professional preview, and TXT / PDF downloads rendered from the same
    document so they cannot disagree;
  * the guarantee that editing a resume touches neither the profile nor a
    sibling version.

The isolation checks are the important ones: this feature writes to a new
table, and the risk is that it quietly starts modifying the candidate's real
profile or an older generated draft.
"""

import json

import pytest

from database.db import get_db
from services import resume_document, resume_versions
from services import resume_agent


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

@pytest.fixture
def skilled_candidate(app, candidate):
    """A candidate with a rich, realistic profile to tailor against."""
    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("DELETE FROM skills WHERE user_id = %s", (candidate["user_id"],))
            for skill in ("Python", "SQL", "Excel", "Pandas", "Scikit-learn", "React", "Git"):
                cursor.execute(
                    "INSERT INTO skills (user_id, name, category) VALUES (%s, %s, 'tool')",
                    (candidate["user_id"], skill),
                )
            cursor.execute(
                "INSERT INTO experience (user_id, title, organization, start_date, end_date, description) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (candidate["user_id"], "Data Analyst Intern", "Acme Analytics",
                 "2025-06", "2025-08", "- Wrote SQL reports"),
            )
            cursor.execute(
                "INSERT INTO projects (user_id, title, description, tech_stack) VALUES (%s, %s, %s, %s)",
                (candidate["user_id"], "Document QA System", "- Built a retrieval pipeline", "Python, Pandas"),
            )
            cursor.execute(
                "INSERT INTO projects (user_id, title, description, tech_stack) VALUES (%s, %s, %s, %s)",
                (candidate["user_id"], "Sales Dashboard", "- Built reporting views", "Excel"),
            )
        db.commit()
    return candidate


def _client(app, candidate):
    client = app.test_client()
    with client.session_transaction() as flask_session:
        flask_session["user_id"] = candidate["user_id"]
        flask_session["user_name"] = "Step1 Candidate"
    return client


def _generate(client, role="Data Analyst", template="professional_ats", instructions=""):
    return client.post(
        "/resume-builder/generate",
        data={"target_role": role, "template": template,
              "custom_instructions": instructions},
        follow_redirects=True,
    )


def _document_from(html):
    """Pull the server-rendered preview out of the page for inspection."""
    start = html.index('<article class="resume-doc">')
    end = html.index("</article>", start) + len("</article>")
    return html[start:end]


def _submitted_document(html):
    """The exact JSON the editor would post, as the client receives it."""
    marker = '<script type="application/json" id="document-json">'
    start = html.index(marker) + len(marker)
    end = html.index("</script>", start)
    return json.loads(html[start:end])


# ==========================================================================
# Role-based generation
# ==========================================================================

def _tailored(role, candidate_dict, monkeypatch, instructions=""):
    def boom(*args, **kwargs):
        raise RuntimeError("simulated LLM outage")

    monkeypatch.setattr(resume_agent, "generate", boom)
    return resume_agent.generate_tailored_resume(
        candidate_dict,
        {"title": role, "company": "", "required_skills": "", "preferred_skills": ""},
        custom_instructions=instructions,
        target_role=role,
        template="professional_ats",
    )


def _candidate_dict():
    return {
        "name": "Aarav Sharma",
        "skills": ["Python", "SQL", "Excel", "Pandas", "Scikit-learn", "React", "Git"],
        "education": [{"institution": "Test University", "degree": "B.Tech",
                       "field": "Computer Science", "start_date": "2022", "end_date": "2026"}],
        "experience": [{"title": "Data Analyst Intern", "organization": "Acme Analytics",
                        "start_date": "2025", "end_date": "2025",
                        "description": "- Wrote SQL reports"}],
        # Deliberately least-relevant-first for an AI Engineer role.
        "projects": [
            {"title": "Sales Dashboard", "description": "- Built reporting views",
             "tech_stack": "Excel"},
            {"title": "Document QA System", "description": "- Built a retrieval pipeline",
             "tech_stack": "Python, Pandas"},
        ],
        "certifications": [{"name": "AWS Certified Developer", "issuer": "Test Issuer"}],
        "degree": "B.Tech",
        "cgpa": 8.5,
    }


def test_project_relevance_uses_technologies_not_just_the_title(monkeypatch):
    """Regression: relevance used to match on the title only.

    Neither "Sales Dashboard" nor "Document QA System" contains an AI Engineer
    focus term, so the original profile order was kept and the Excel dashboard
    was presented as the most relevant project for an ML role.
    """
    tailored = _tailored("AI Engineer", _candidate_dict(), monkeypatch)

    assert tailored["projects"][0]["title"] == "Document QA System"


def test_the_most_relevant_project_still_leads_when_the_title_matches(monkeypatch):
    candidate = _candidate_dict()
    candidate["projects"] = [
        {"title": "Machine Learning Pipeline", "description": "- Trained a model",
         "tech_stack": "Python"},
        {"title": "Document QA System", "description": "- Built a retrieval pipeline",
         "tech_stack": "Python, Pandas"},
    ]
    tailored = _tailored("AI Engineer", candidate, monkeypatch)

    # Title matches weigh double, so the explicitly named ML project leads.
    assert tailored["projects"][0]["title"] == "Machine Learning Pipeline"


def test_different_roles_produce_materially_different_summaries(monkeypatch):
    analyst = _tailored("Data Analyst", _candidate_dict(), monkeypatch)
    scientist = _tailored("Data Scientist", _candidate_dict(), monkeypatch)
    engineer = _tailored("AI Engineer", _candidate_dict(), monkeypatch)

    summaries = {analyst["professional_summary"],
                 scientist["professional_summary"],
                 engineer["professional_summary"]}
    assert len(summaries) == 3, summaries

    # Each names its own role and leads with that role's own skills.
    assert analyst["highlighted_skills"][:3] == ["SQL", "Excel", "Pandas"]
    assert "Scikit-learn" in engineer["highlighted_skills"][:3]
    assert scientist["highlighted_skills"][0] == "Python"


def test_the_fallback_summary_never_narrates_the_generator(monkeypatch):
    """The old fallback ended with "tailored to emphasize verified experience
    over new claims" -- a description of the tool, not of the candidate."""
    tailored = _tailored("Data Analyst", _candidate_dict(), monkeypatch)
    summary = tailored["professional_summary"]

    assert "Aarav Sharma" in summary
    assert "Data Analyst" in summary
    for banned in ("verified experience over new claims",
                   "tailored to emphasize",
                   "built on verified project and profile experience",
                   "application built on"):
        assert banned not in summary, banned


def test_the_fallback_summary_only_names_real_records(monkeypatch):
    base = _candidate_dict()
    tailored = _tailored("Data Analyst", base, monkeypatch)
    summary = tailored["professional_summary"]

    assert "Acme Analytics" in summary           # a real employer
    assert "Data Analyst Intern" in summary       # a real role
    for invented in ("Google", "Microsoft", "AWS", "3 years"):
        assert invented not in summary, invented


def test_the_fallback_summary_degrades_without_inventing(monkeypatch):
    """An empty section is omitted, not filled with something plausible."""
    bare = _candidate_dict()
    bare["skills"] = []
    tailored = _tailored("Data Scientist", bare, monkeypatch)
    # Skills are gone, so the sentence stops naming skills -- but the real
    # internship and projects are still there and must still be mentioned.
    summary = tailored["professional_summary"]
    assert "SQL" not in summary
    assert "Acme Analytics" in summary
    assert "Document QA System" in summary

    # With nothing at all to draw on, the fallback is the role alone rather than
    # an invented qualification.
    empty = _candidate_dict()
    empty.update({"skills": [], "experience": [], "projects": []})
    tailored = _tailored("Data Scientist", empty, monkeypatch)
    assert tailored["professional_summary"] == "Aarav Sharma: Data Scientist."


def test_custom_instructions_still_influence_the_resume(monkeypatch):
    tailored = _tailored(
        "Data Scientist", _candidate_dict(), monkeypatch,
        instructions="Highlight my SQL skills",
    )
    # SQL exists in the profile, so the emphasis is honoured.
    assert tailored["highlighted_skills"][0] == "SQL"


def test_an_unverified_skill_request_adds_nothing(monkeypatch):
    tailored = _tailored(
        "Data Scientist", _candidate_dict(), monkeypatch,
        instructions="Highlight my Kubernetes skills",
    )
    assert "Kubernetes" not in tailored["highlighted_skills"]


# ==========================================================================
# Document model
# ==========================================================================

def _sample_document():
    return resume_document.sections_from_tailored({
        "name": "Jane Doe", "email": "jane@example.com", "phone": "+91 9876543210",
        "target_role": "Data Analyst",
        "professional_summary": "Final year CS student with SQL and Power BI work.",
        "highlighted_skills": ["Python", "SQL"],
        "skill_categories": [{"label": "Languages", "skills": ["Python", "SQL"]}],
        "experience": [{"title": "Data Analyst Intern", "organization": "Infosys",
                        "start_date": "2025-06", "end_date": "2025-08",
                        "bullets": ["Built Power BI dashboards."]}],
        "projects": [{"title": "Resume Ranker", "tech_stack": "Python, FAISS",
                      "bullets": ["FAISS based screening tool."]}],
        "education": [{"degree": "B.Tech", "institution": "AKS University",
                       "start_date": "2022", "end_date": "2026"}],
        "certifications": [{"name": "AWS Certified Developer", "issuer": "Amazon"}],
    }, {"cgpa": 8.66})


def test_the_document_renders_name_contact_and_grouped_skills():
    document = _sample_document()
    html = resume_document.render_html(document)
    text = resume_document.render_text(document)

    # Name is the first thing in the document.
    assert text.splitlines()[0] == "Jane Doe"
    assert "jane@example.com" in html and "+91 9876543210" in html
    # Skills are grouped, not one long repetitive list.
    assert "Languages" in html
    assert "Python, SQL" in text


def test_sections_the_user_does_not_have_are_omitted_entirely():
    document = resume_document.sections_from_tailored(
        {"name": "Nobody", "highlighted_skills": [], "experience": [], "projects": [],
         "education": [], "certifications": []},
        {},
    )
    html = resume_document.render_html(document)
    for heading in ("EXPERIENCE", "PROJECTS", "CERTIFICATIONS", "TECHNICAL SKILLS"):
        assert heading not in html, heading


def test_sections_can_be_reordered_and_removed():
    document = _sample_document()
    original = [s["key"] for s in document["sections"]]

    reversed_document = dict(document, sections=list(reversed(document["sections"])))
    assert [s["key"] for s in reversed_document["sections"]] == list(reversed(original))
    text = resume_document.render_text(reversed_document)
    assert text.index("CERTIFICATIONS") < text.index("EXPERIENCE")

    trimmed = dict(document, sections=[s for s in document["sections"] if s["key"] != "projects"])
    assert "PROJECTS" not in resume_document.render_text(trimmed)
    assert "Resume Ranker" not in resume_document.render_text(trimmed)


def test_validation_rejects_junk_and_bounds_oversized_input():
    assert resume_document.validate_sections("not json at all")["sections"] == []
    assert resume_document.validate_sections([{"kind": "nonsense"}])["sections"] == []
    assert resume_document.validate_sections(["a string", 7, None])["sections"] == []

    big = resume_document.validate_sections(
        [{"kind": "text", "title": "T", "text": "x" * 100_000}], name="y" * 5_000,
    )
    assert len(big["sections"][0]["text"]) == resume_document.MAX_TEXT
    assert len(big["name"]) == 160
    assert len(big["sections"]) <= resume_document.MAX_SECTIONS


def test_rendered_output_escapes_user_supplied_markup():
    document = resume_document.validate_sections(
        [{"kind": "text", "title": "T", "text": "<script>alert(1)</script>"}],
        name="<b>Injected</b>",
    )
    html = resume_document.render_html(document)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "<b>Injected</b>" not in html


# ==========================================================================
# Downloads
# ==========================================================================

def test_the_pdf_contains_real_selectable_text_not_an_image():
    document = _sample_document()
    pdf = resume_document.render_pdf(document)
    text = resume_document.pdf_text(pdf)

    assert pdf[:5] == b"%PDF-"
    assert resume_document.pdf_page_count(pdf) >= 1
    # Section headings are upper case in both the text and PDF renderings, which
    # is the conventional resume format.
    for expected in ("Jane Doe", "jane@example.com", "Data Analyst",
                     "PROFESSIONAL SUMMARY", "TECHNICAL SKILLS",
                     "Built Power BI dashboards",
                     "AWS Certified Developer", "AKS University"):
        assert expected in text, expected


def test_the_pdf_matches_the_text_and_html_renderings():
    """The whole point of one document model: no format can drift."""
    document = _sample_document()
    text = resume_document.render_text(document)
    pdf_text = resume_document.pdf_text(resume_document.render_pdf(document))
    html = resume_document.render_html(document)

    for token in ("Jane Doe", "Infosys", "FAISS", "B.Tech", "Python"):
        assert token in text, f"txt missing {token}"
        assert token in pdf_text, f"pdf missing {token}"
        assert token in html, f"html missing {token}"


def test_pdf_paginates_a_long_resume_instead_of_truncating():
    document = _sample_document()
    document["sections"][0]["text"] = "Verified experience. " * 400
    pdf = resume_document.render_pdf(document)
    assert resume_document.pdf_page_count(pdf) > 1
    assert "Jane Doe" in resume_document.pdf_text(pdf)


def test_an_empty_document_cannot_produce_a_pdf():
    empty = {"name": "", "contact": [], "headline": "", "sections": []}
    with pytest.raises(ValueError):
        resume_document.render_pdf(empty)


# ==========================================================================
# Saved versions
# ==========================================================================

def _save(client, sections, **extra):
    data = {"sections": json.dumps({"sections": sections}), "target_role": "Data Analyst"}
    data.update(extra)
    return client.post("/resume-builder/versions/save", data=data)


def _version_sections(summary="First version"):
    return [{
        "key": "professional_summary", "title": "Professional Summary",
        "kind": "text", "text": summary,
    }, {
        "key": "skills", "title": "Technical Skills", "kind": "skill_groups",
        "groups": [{"label": "Languages", "skills": ["Python"]}],
    }]


def test_a_saved_version_persists_and_reopens(app, skilled_candidate):
    client = _client(app, skilled_candidate)
    response = _save(client, _version_sections(), template="professional_ats")

    assert response.status_code == 200
    assert b"Saved Resumes" in response.data

    with app.app_context():
        versions = resume_versions.list_versions(get_db(), skilled_candidate["user_id"])
    assert len(versions) == 1
    version = versions[0]

    reopened = client.get(f"/resume-builder/?version={version['id']}")
    assert reopened.status_code == 200
    body = reopened.get_data(as_text=True)
    assert "First version" in body
    assert "First version" in _document_from(body)


def test_several_versions_of_the_same_role_stay_independent(app, skilled_candidate):
    client = _client(app, skilled_candidate)
    _save(client, _version_sections("Version A"), title="Acme application")
    _save(client, _version_sections("Version B"), title="Globex application")
    _save(client, _version_sections("Version C"), title="Initech application")

    with app.app_context():
        db = get_db()
        versions = resume_versions.list_versions(db, skilled_candidate["user_id"])
        titles = sorted(v["title"] for v in versions)
        assert titles == ["Acme application", "Globex application", "Initech application"]

        # Editing one must not touch the others.
        target = next(v for v in versions if v["title"] == "Globex application")
        resume_versions.save_version(
            db, skilled_candidate["user_id"], _profile(app, skilled_candidate),
            sections=_version_sections("Version B edited"),
            target_role="Data Analyst", version_id=target["id"],
        )
        after = resume_versions.list_versions(db, skilled_candidate["user_id"])
        by_title = {v["title"]: v for v in after}
        assert "Version B edited" in resume_document.render_text(
            resume_versions.document_for(by_title["Globex application"])
        )
        assert "Version A" in resume_document.render_text(
            resume_versions.document_for(by_title["Acme application"])
        )
        assert "Version C" in resume_document.render_text(
            resume_versions.document_for(by_title["Initech application"])
        )


def _profile(app, candidate):
    from services.context_builder import get_candidate_context
    with app.app_context():
        return get_candidate_context(get_db(), candidate["user_id"])


def test_editing_a_version_does_not_touch_the_profile(app, skilled_candidate):
    """The core isolation guarantee: a resume is not the profile."""
    client = _client(app, skilled_candidate)

    with app.app_context():
        db = get_db()
        before = _profile_snapshot(db, skilled_candidate["user_id"])

    _save(client, _version_sections("Edited summary"),
          sections_override="Edited summary")

    with app.app_context():
        db = get_db()
        after = _profile_snapshot(db, skilled_candidate["user_id"])

    assert after == before, "saving a resume must not alter the profile"


def _profile_snapshot(db, user_id):
    snapshot = {}
    for table, columns in (
        ("skills", ("name",)),
        ("projects", ("title", "description", "tech_stack")),
        ("experience", ("title", "organization", "description")),
        ("education", ("institution", "degree")),
        ("certifications", ("name", "issuer")),
        ("profiles", ("college", "degree", "summary")),
    ):
        with db.cursor() as cursor:
            select = ", ".join(columns)
            cursor.execute(f"SELECT {select} FROM {table} WHERE user_id = %s", (user_id,))
            snapshot[table] = sorted(str(row) for row in cursor.fetchall())
    return snapshot


def test_a_version_cannot_be_read_or_written_by_another_user(app, skilled_candidate):
    client = _client(app, skilled_candidate)
    _save(client, _version_sections("Private summary"), title="Mine")

    with app.app_context():
        db = get_db()
        version_id = resume_versions.list_versions(db, skilled_candidate["user_id"])[0]["id"]

        with db.cursor() as cursor:
            cursor.execute(
                "INSERT INTO users (name, email, password_hash, career_status) "
                "VALUES ('Other', 'other-person@example.test', 'x', 'Fresher')"
            )
            other_id = cursor.lastrowid
        db.commit()

        # Not visible at all, so there is no path to read or overwrite it.
        assert resume_versions.get_version(db, other_id, version_id) is None
        assert resume_versions.delete_version(db, other_id, version_id) is False
        with pytest.raises(resume_versions.VersionError):
            resume_versions.rename_version(db, other_id, version_id, "Hijacked")
        with pytest.raises(resume_versions.VersionError):
            resume_versions.save_version(
                db, other_id, {"name": "Other", "email": "o@e.test"},
                sections=_version_sections("Overwritten"), version_id=version_id,
            )

        # The owner's copy is untouched.
        assert resume_versions.get_version(db, skilled_candidate["user_id"], version_id)["title"] == "Mine"

        with db.cursor() as cursor:
            cursor.execute("DELETE FROM users WHERE id = %s", (other_id,))
        db.commit()


def test_a_version_can_be_renamed_and_deleted(app, skilled_candidate):
    client = _client(app, skilled_candidate)
    _save(client, _version_sections(), title="Before")

    with app.app_context():
        db = get_db()
        version_id = resume_versions.list_versions(db, skilled_candidate["user_id"])[0]["id"]

    renamed = client.post(
        f"/resume-builder/versions/{version_id}/rename",
        data={"title": "After"},
        follow_redirects=True,
    )
    assert renamed.status_code == 200

    with app.app_context():
        assert resume_versions.get_version(
            get_db(), skilled_candidate["user_id"], version_id
        )["title"] == "After"

    deleted = client.post(
        f"/resume-builder/versions/{version_id}/delete",
        data={},
        follow_redirects=True,
    )
    assert deleted.status_code == 200
    with app.app_context():
        assert resume_versions.get_version(
            get_db(), skilled_candidate["user_id"], version_id
        ) is None


def test_deleting_an_unknown_version_reports_failure_not_success(app, skilled_candidate):
    client = _client(app, skilled_candidate)

    # A JSON caller gets a real status code.
    response = client.post("/resume-builder/versions/999999/delete", json={})
    assert response.status_code == 404
    assert response.get_json()["success"] is False

    # A form post comes back to the page with the reason on it, rather than
    # silently pretending the delete worked.
    page = client.post("/resume-builder/versions/999999/delete", data={},
                       follow_redirects=True)
    assert page.status_code == 200
    assert "could not be found" in page.get_data(as_text=True)


def test_a_version_can_be_attached_to_a_company(app, skilled_candidate):
    client = _client(app, skilled_candidate)
    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute(
                "SELECT job_id, company FROM jobs WHERE job_id < 1000000000 "
                "AND company IS NOT NULL AND company <> '' ORDER BY job_id LIMIT 1"
            )
            job = cursor.fetchone()

    _save(client, _version_sections(), job_id=job["job_id"], job_description="Paste the posting here")

    with app.app_context():
        version = resume_versions.list_versions(get_db(), skilled_candidate["user_id"])[0]
    # The company is taken from the database, never from the form.
    assert version["company"] == job["company"]
    assert version["job_description"] == "Paste the posting here"


def test_saving_an_empty_resume_is_refused(app, skilled_candidate):
    client = _client(app, skilled_candidate)
    empty = json.dumps({"sections": []})

    response = client.post("/resume-builder/versions/save", json={"sections": empty})
    assert response.status_code == 400
    assert response.get_json()["success"] is False

    page = client.post("/resume-builder/versions/save", data={"sections": empty},
                       follow_redirects=True)
    assert page.status_code == 200
    assert "nothing to save" in page.get_data(as_text=True).lower()

    with app.app_context():
        assert resume_versions.count_versions(get_db(), skilled_candidate["user_id"]) == 0


def test_malformed_section_json_is_refused_clearly(app, skilled_candidate):
    client = _client(app, skilled_candidate)
    response = client.post("/resume-builder/versions/save", json={"sections": "{not json"})
    assert response.status_code == 400
    body = response.get_json()
    assert body["success"] is False
    assert "could not be read" in body["error"]

    with app.app_context():
        assert resume_versions.count_versions(get_db(), skilled_candidate["user_id"]) == 0


# ==========================================================================
# Download endpoints
# ==========================================================================

def test_downloading_txt_returns_the_edited_content(app, skilled_candidate):
    client = _client(app, skilled_candidate)
    response = client.post(
        "/resume-builder/download/txt",
        data={"sections": json.dumps({"sections": _version_sections("Downloaded summary")}),
              "target_role": "Data Analyst"},
    )
    assert response.status_code == 200
    assert "text/plain" in response.headers["Content-Type"]
    assert "attachment" in response.headers["Content-Disposition"]
    body = response.get_data(as_text=True)
    assert "Downloaded summary" in body
    assert "Languages" in body


def test_downloading_pdf_returns_a_pdf_with_the_edited_content(app, skilled_candidate):
    client = _client(app, skilled_candidate)
    response = client.post(
        "/resume-builder/download/pdf",
        data={"sections": json.dumps({"sections": _version_sections("Downloaded summary")}),
              "target_role": "Data Analyst"},
    )
    assert response.status_code == 200
    assert response.mimetype == "application/pdf"
    assert response.get_data()[:5] == b"%PDF-"
    text = resume_document.pdf_text(response.get_data())
    assert "Downloaded summary" in text


def test_a_saved_version_downloads_the_stored_content(app, skilled_candidate):
    """A stale form must not be able to change what a saved resume produces."""
    client = _client(app, skilled_candidate)
    _save(client, _version_sections("Stored summary"), title="Stored")

    with app.app_context():
        version_id = resume_versions.list_versions(get_db(), skilled_candidate["user_id"])[0]["id"]

    response = client.post(
        f"/resume-builder/download/txt?version_id={version_id}",
        data={"version_id": version_id,
              "sections": json.dumps({"sections": _version_sections("Tampered")})},
    )
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Stored summary" in body
    assert "Tampered" not in body


def test_downloading_without_content_reports_an_error(app, skilled_candidate):
    client = _client(app, skilled_candidate)
    response = client.post("/resume-builder/download/pdf", data={"sections": ""},
                           headers={"X-Requested-With": "fetch"})
    assert response.status_code == 400
    assert response.get_json()["success"] is False


def test_downloading_another_users_version_is_refused(app, skilled_candidate):
    client = _client(app, skilled_candidate)
    _save(client, _version_sections())
    with app.app_context():
        version_id = resume_versions.list_versions(get_db(), skilled_candidate["user_id"])[0]["id"]

    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute(
                "INSERT INTO users (name, email, password_hash, career_status) "
                "VALUES ('Other', 'other-dl@example.test', 'x', 'Fresher')"
            )
            other_id = cursor.lastrowid
        db.commit()

    other_client = app.test_client()
    with other_client.session_transaction() as flask_session:
        flask_session["user_id"] = other_id
        flask_session["user_name"] = "Other"

    # A JSON caller gets a 400 with the reason.
    response = other_client.get(
        f"/resume-builder/download/txt?version_id={version_id}",
        headers={"X-Requested-With": "fetch", "Accept": "application/json"},
    )
    assert response.status_code == 400
    assert "could not be found" in response.get_json()["error"]

    # A plain link redirects back to the builder. It must NOT return 200 with an
    # HTML page, because the browser would save that page as the .txt file.
    page = other_client.get(
        f"/resume-builder/download/txt?version_id={version_id}", follow_redirects=True
    )
    assert page.status_code == 200
    assert page.mimetype == "text/html", "an error page must not be served as a download"
    assert "could not be found" in page.get_data(as_text=True)

    with app.app_context():
        with get_db().cursor() as cursor:
            cursor.execute("DELETE FROM users WHERE id = %s", (other_id,))
        get_db().commit()


# ==========================================================================
# Page contract
# ==========================================================================

def test_the_page_offers_every_existing_template(app, skilled_candidate):
    client = _client(app, skilled_candidate)
    body = client.get("/resume-builder/").get_data(as_text=True)

    for label in ("Classic Chronological", "Skills-First", "Professional ATS",
                  "Modern ATS", "Technical ATS", "Minimal ATS", "Entry-Level ATS"):
        assert label in body, label

    # The target-role selector and custom instructions are still present.
    assert 'name="target_role"' in body
    assert 'name="custom_instructions"' in body


def test_the_page_exposes_the_five_primary_actions_after_generation(app, skilled_candidate, monkeypatch):
    client = _client(app, skilled_candidate)
    monkeypatch.setattr(resume_agent, "generate", lambda *a, **k: json.dumps(
        {"professional_summary": "Analyst with SQL experience.",
         "highlighted_skills": ["SQL"], "experience": [], "projects": []}
    ))
    body = _generate(client, "Data Analyst").get_data(as_text=True)

    assert "Tailored Resume Preview" in body
    assert 'id="toggle-editor"' in body
    assert 'id="save-resume"' in body
    assert 'id="download-pdf"' in body
    assert 'id="download-txt"' in body
    assert 'id="resume-editor-panel"' in body
    assert 'id="document-json"' in body


def test_the_preview_is_rendered_before_the_profile_reference(app, skilled_candidate, monkeypatch):
    """The resume is the point of the page; the profile is supporting material."""
    client = _client(app, skilled_candidate)
    monkeypatch.setattr(resume_agent, "generate", lambda *a, **k: json.dumps(
        {"professional_summary": "Analyst with SQL experience.",
         "highlighted_skills": ["SQL"], "experience": [], "projects": []}
    ))
    body = _generate(client, "Data Analyst").get_data(as_text=True)

    assert body.index("resume-doc") < body.index("Reference: your profile")
    # And the two are labelled so they cannot be mistaken for each other.
    assert "Reference: your profile" in body
    assert "Current Profile" in body


def test_a_model_outage_falls_back_rather_than_failing(app, skilled_candidate, monkeypatch):
    """An unreachable model is not an error: the agent has a safe fallback.

    That behaviour predates this change and is covered by the existing suite;
    this pins it alongside the new preview so a future change to the fallback
    cannot quietly turn an outage into a blank page.
    """
    client = _client(app, skilled_candidate)
    monkeypatch.setattr(resume_agent, "generate",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("LLM down")))
    response = client.post(
        "/resume-builder/generate",
        data={"target_role": "Data Scientist"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "AI fallback used" in body
    # A document is still produced, so the preview is never empty.
    assert "resume-doc" in body


def test_generation_failure_preserves_previous_content_and_explains(app, skilled_candidate, monkeypatch):
    """A genuine hard failure is reported and destroys nothing."""
    client = _client(app, skilled_candidate)
    _save(client, _version_sections("Content that must survive"), title="Keeper")

    from services.agent_orchestrator import AgentOrchestrator

    monkeypatch.setattr(
        AgentOrchestrator, "run_resume_builder",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("agent exploded")),
    )
    response = client.post(
        "/resume-builder/generate",
        data={"target_role": "Data Scientist"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "could not be generated" in response.get_data(as_text=True)

    with app.app_context():
        version = resume_versions.list_versions(get_db(), skilled_candidate["user_id"])[0]
    assert "Content that must survive" in resume_document.render_text(
        resume_versions.document_for(version)
    )


def test_the_page_requires_authentication(app):
    for path in ("/resume-builder/", "/resume-builder/download/pdf",
                 "/resume-builder/download/txt"):
        response = app.test_client().get(path)
        assert response.status_code in (302, 405), path
        if response.status_code == 302:
            assert "/login" in response.headers["Location"]


def test_no_new_frontend_dependency_was_introduced():
    source = open("templates/resume_builder.html", encoding="utf-8").read()
    for script in ["static/js/resume_builder.js"]:
        # Nothing new is loaded; the editor is inline and framework-free.
        assert script not in source
    for word in ("react", "vue", "angular", "tailwind", "alpine"):
        assert word not in source.lower(), word


def test_pdf_generation_uses_the_existing_pymupdf_dependency():
    """reportlab is installed on this machine but is not a declared
    requirement, so relying on it would be a hidden dependency."""
    requirements = open("requirements.txt", encoding="utf-8").read()
    assert "PyMuPDF" in requirements
    assert "reportlab" not in requirements

    source = open("services/resume_document.py", encoding="utf-8").read()
    assert "import pymupdf" in source
    assert "reportlab" not in source