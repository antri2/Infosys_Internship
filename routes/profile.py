from flask import Blueprint, render_template, request, redirect, url_for, session, flash

from database.db import get_db

profile_bp = Blueprint("profile", __name__, url_prefix="/profile")
home_bp = Blueprint("home", __name__)


def _require_login():
    return "user_id" in session


def _load_profile(db, user_id: int) -> dict:
    with db.cursor() as cursor:
        cursor.execute("SELECT * FROM profiles WHERE user_id = %s", (user_id,))
        profile = cursor.fetchone() or {}
        cursor.execute("SELECT name, category FROM skills WHERE user_id = %s", (user_id,))
        skills = cursor.fetchall()
        cursor.execute("SELECT * FROM education WHERE user_id = %s", (user_id,))
        education = cursor.fetchall()
        cursor.execute("SELECT * FROM experience WHERE user_id = %s", (user_id,))
        experience = cursor.fetchall()
        cursor.execute("SELECT * FROM projects WHERE user_id = %s", (user_id,))
        projects = cursor.fetchall()

    profile["skills"] = skills
    profile["education"] = education
    profile["experience_list"] = experience
    profile["projects"] = projects
    return profile


def _build_checklist(db, user_id: int, profile: dict) -> list[dict]:
    with db.cursor() as cursor:
        cursor.execute("SELECT name, phone FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone() or {}
        cursor.execute("SELECT 1 FROM resumes WHERE user_id = %s LIMIT 1", (user_id,))
        has_resume = cursor.fetchone() is not None

    return [
        {"name": "Personal Information", "done": bool(user.get("name") and user.get("phone"))},
        {"name": "Education Details", "done": bool(profile.get("college") and profile.get("degree"))},
        {"name": "Skills & Experience", "done": bool(profile.get("skills"))},
        {"name": "Resume Uploaded", "done": has_resume},
    ]


@home_bp.route("/home")
def dashboard():
    if not _require_login():
        return redirect(url_for("auth.login"))

    db = get_db()
    user_id = session["user_id"]
    profile = _load_profile(db, user_id)
    checklist = _build_checklist(db, user_id, profile)
    completeness = round(sum(1 for c in checklist if c["done"]) / len(checklist) * 100)
    resume_uploaded = next(c["done"] for c in checklist if c["name"] == "Resume Uploaded")

    user_skills = [s["name"] for s in profile["skills"]]

    # Top opportunity previews (reuses the same search/match logic as the
    # full Opportunities page, just capped to a handful for the home preview)
    from services.opportunity_service import search_jobs
    from services.job_matcher import compute_match

    query = ", ".join(user_skills) if user_skills else "internship entry level"
    top_jobs = []
    for job in search_jobs(query, top_k=5):
        match_info = compute_match(user_skills, job)
        top_jobs.append({**job, "job_id": int(job["job_id"]), **match_info})
    top_jobs.sort(key=lambda j: j["match_percent"], reverse=True)

    with db.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) AS n FROM applications WHERE user_id = %s", (user_id,))
        applications_count = cursor.fetchone()["n"]
        cursor.execute(
            """
            SELECT a.job_id, a.status, a.applied_on, j.title, j.company
            FROM applications a JOIN jobs j ON j.job_id = a.job_id
            WHERE a.user_id = %s ORDER BY a.updated_at DESC LIMIT 5
            """,
            (user_id,),
        )
        recent_applications = cursor.fetchall()

    return render_template(
        "home.html",
        active_page="home",
        user_name=session.get("user_name"),
        profile=profile,
        checklist=checklist,
        completeness=completeness,
        resume_uploaded=resume_uploaded,
        top_jobs=top_jobs,
        applications_count=applications_count,
        recent_applications=recent_applications,
    )


@profile_bp.route("/", methods=["GET"])
def view():
    if not _require_login():
        return redirect(url_for("auth.login"))

    db = get_db()
    user_id = session["user_id"]
    profile = _load_profile(db, user_id)
    checklist = _build_checklist(db, user_id, profile)
    completeness = round(sum(1 for c in checklist if c["done"]) / len(checklist) * 100)

    with db.cursor() as cursor:
        cursor.execute("SELECT name, email, phone, career_status FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()

    return render_template(
        "profile.html",
        active_page="profile",
        profile=profile,
        user=user,
        completeness=completeness,
    )


@profile_bp.route("/edit", methods=["POST"])
def edit():
    if not _require_login():
        return redirect(url_for("auth.login"))

    user_id = session["user_id"]
    college = request.form.get("college", "").strip()
    degree = request.form.get("degree", "").strip()
    passing_year = request.form.get("passing_year") or None
    cgpa = request.form.get("cgpa") or None
    skills_raw = request.form.get("skills", "")
    experience = request.form.get("experience", "").strip()

    db = get_db()
    with db.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO profiles (user_id, college, degree, passing_year, cgpa, experience)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE college=VALUES(college), degree=VALUES(degree),
                passing_year=VALUES(passing_year), cgpa=VALUES(cgpa), experience=VALUES(experience)
            """,
            (user_id, college, degree, passing_year, cgpa, experience),
        )
        cursor.execute("DELETE FROM skills WHERE user_id = %s", (user_id,))
        for name in [s.strip() for s in skills_raw.split(",") if s.strip()]:
            cursor.execute("INSERT INTO skills (user_id, name) VALUES (%s, %s)", (user_id, name))
        db.commit()

    flash("Profile updated.")
    return redirect(url_for("profile.view"))