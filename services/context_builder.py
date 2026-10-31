"""
Assembles the two inputs every M3 agent needs -- the candidate's profile
and one specific job's requirements -- as plain dicts. Every agent below
calls this instead of re-writing the same DB lookups.

Job lookup goes straight to MySQL (SELECT ... WHERE job_id = %s), not
through services.opportunity_service.search_jobs(): that does semantic
*search* (best top_k matches for a query text), the right tool for the
Opportunities list page, the wrong tool for "give me exactly job #47".
"""


def get_candidate_context(db, user_id: int) -> dict:
    with db.cursor() as cursor:
        cursor.execute("SELECT name, category FROM skills WHERE user_id = %s", (user_id,))
        skills = cursor.fetchall()

        cursor.execute(
            "SELECT institution, degree, field, start_date, end_date FROM education WHERE user_id = %s",
            (user_id,),
        )
        education = cursor.fetchall()

        cursor.execute(
            "SELECT title, organization, start_date, end_date, description FROM experience WHERE user_id = %s",
            (user_id,),
        )
        experience = cursor.fetchall()

        cursor.execute(
            "SELECT title, description, tech_stack FROM projects WHERE user_id = %s",
            (user_id,),
        )
        projects = cursor.fetchall()

        cursor.execute(
            """
            SELECT name, issuer, issue_date, expiry_date, credential_url
            FROM certifications WHERE user_id = %s
            ORDER BY id
            """,
            (user_id,),
        )
        certifications = cursor.fetchall()

        cursor.execute(
            """
            SELECT summary, college, degree, passing_year, cgpa, resume_id
            FROM profiles WHERE user_id = %s
            """,
            (user_id,),
        )
        profile_row = cursor.fetchone() or {}

        cursor.execute(
            "SELECT name, email, phone FROM users WHERE id = %s", (user_id,)
        )
        user_row = cursor.fetchone() or {}

        resume_row = {}
        if profile_row.get("resume_id"):
            cursor.execute(
                """
                SELECT id, file_type, parse_status, uploaded_at
                FROM resumes WHERE id = %s AND user_id = %s
                """,
                (profile_row["resume_id"], user_id),
            )
            resume_row = cursor.fetchone() or {}

    return {
        "name": user_row.get("name"),
        "email": user_row.get("email"),
        "phone": user_row.get("phone"),
        "skills": [s["name"] for s in skills],
        "education": education,
        "experience": experience,
        "projects": projects,
        "certifications": certifications,
        "college": profile_row.get("college"),
        "degree": profile_row.get("degree"),
        "passing_year": profile_row.get("passing_year"),
        "cgpa": profile_row.get("cgpa"),
        "summary": profile_row.get("summary"),
        "resume": resume_row,
    }


def get_job_context(db, job_id: int) -> dict | None:
    """Resolve one job by id, from either job source.

    Local jobs come from MySQL exactly as before. Ids in the reserved Adzuna
    range have no MySQL row, so they are resolved from the short-lived live
    cache that services.adzuna_service fills when it fetches listings. Every
    caller (Skill Gap, AI Summary, Interview, Cover Letter, Resume Builder and
    the orchestrator) therefore keeps working for live jobs without knowing
    which source produced them.
    """
    with db.cursor() as cursor:
        cursor.execute("SELECT * FROM jobs WHERE job_id = %s", (job_id,))
        row = cursor.fetchone()
    if row:
        return row

    try:
        from services import live_job_store

        return live_job_store.get(job_id)
    except Exception:  # pragma: no cover - never let a lookup break an agent
        return None


def build_agent_context(db, user_id: int, job_id: int | None) -> tuple[dict, dict | None]:
    """job_id may be None (cover letters can be for a custom/off-platform
    job) -- returns (candidate, None) in that case rather than erroring."""
    candidate = get_candidate_context(db, user_id)
    job = get_job_context(db, job_id) if job_id else None
    return candidate, job


def flatten_candidate_text(candidate: dict) -> str:
    """A plain-text rendering of everything the candidate has, used by the
    fact-checker in resume_agent.py to verify the LLM didn't invent a
    skill/claim that isn't actually anywhere in the source profile."""
    parts = [
        "Skills: " + ", ".join(candidate.get("skills", [])),
    ]
    for e in candidate.get("education", []):
        parts.append(f"Education: {e.get('degree')} {e.get('field') or ''} at {e.get('institution')}")
    for x in candidate.get("experience", []):
        parts.append(f"Experience: {x.get('title')} at {x.get('organization')}: {x.get('description') or ''}")
    for p in candidate.get("projects", []):
        parts.append(f"Project: {p.get('title')} ({p.get('tech_stack') or ''}): {p.get('description') or ''}")
    for c in candidate.get("certifications", []):
        issuer = f" from {c.get('issuer')}" if c.get("issuer") else ""
        parts.append(f"Certification: {c.get('name')}{issuer}")
    profile_bits = []
    if candidate.get("college"):
        profile_bits.append(f"College: {candidate['college']}")
    if candidate.get("degree"):
        profile_bits.append(f"Degree: {candidate['degree']}")
    if candidate.get("passing_year") is not None:
        profile_bits.append(f"Passing year: {candidate['passing_year']}")
    if candidate.get("cgpa") is not None:
        profile_bits.append(f"CGPA: {candidate['cgpa']}")
    if profile_bits:
        parts.append("Profile: " + "; ".join(profile_bits))
    if candidate.get("summary"):
        parts.append("Summary: " + candidate["summary"])
    return "\n".join(parts)