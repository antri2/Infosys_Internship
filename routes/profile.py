"""Profile display and editing.

MySQL is the single source of truth. Every value rendered on /profile/ is read
from the same tables the Resume Parser writes into (routes/resume.py), and every
edit made here is written straight back to those same rows so the candidate
context built by services/context_builder.py stays current. There is no second
profile store and nothing is kept in the browser.
"""

from flask import Blueprint, render_template, request, redirect, url_for, session, flash

from database.db import get_db
from services.job_dates import (
    apply_by_for,
    demo_badge,
    is_demo_listing,
    validated_publication_date,
)
from services.skill_normalizer import normalize_skill, skill_comparison_key

profile_bp = Blueprint("profile", __name__, url_prefix="/profile")
home_bp = Blueprint("home", __name__)

# How many ranked jobs the dashboard asks for. This is the pool the ranking
# produces; the card grid shows HOME_VISIBLE_JOBS of them first and the
# "View More" action reveals the rest without a second request.
HOME_JOB_COUNT = 9

# How many cards are visible before "View More" is pressed.
HOME_VISIBLE_JOBS = 6


def _work_mode(job: dict) -> str:
    """Work mode, only when the job's own text actually states one.

    Neither source carries a work-mode column, so this reads the words the
    source did publish. The description is included because it is the field most
    likely to say "remote" or "hybrid" in context, but only an explicit word
    counts -- proximity, inference or a company name never triggers it.
    Anything else returns "", and the card then omits the row entirely rather
    than showing a placeholder.
    """
    haystack = " ".join(
        str(job.get(field) or "") for field in ("location", "job_type", "description")
    ).lower()

    if "hybrid" in haystack:
        return "Hybrid"
    if "remote" in haystack or "work from home" in haystack or "wfh" in haystack:
        return "Remote"
    if "on-site" in haystack or "onsite" in haystack or "in-office" in haystack:
        return "On-site"
    return ""


def _card_job(job: dict) -> dict:
    """Add the presentation fields a card needs, without inventing any.

    Optional fields are normalised to "" when the source has nothing, so the
    template renders nothing at all for them. That is what removes the literal
    "Not provided" strings from the dashboard.
    """
    enriched = dict(job)

    # Work mode: inferred from the job's own text, "" when not stated.
    enriched["work_mode"] = _work_mode(job)

    # Optional text fields become "" rather than a placeholder string.
    for field in ("company", "location", "job_type", "stipend_or_salary",
                  "description", "experience_required"):
        enriched[field] = str(job.get(field) or "").strip()

    # A publication date is shown only when the source value parses and is
    # plausible. A local row's created_at is an import timestamp, not a posting
    # date, so it is never used here; those listings are badged instead.
    enriched["published_date"] = validated_publication_date(job.get("published_date"))

    # No source publishes a deadline, so this is a suggested planning window.
    # apply_by_for() keeps the employer's own date if one ever appears.
    enriched["apply_by"] = apply_by_for(job)

    # Generated listings are labelled as such rather than passed off as real.
    enriched["is_demo"] = is_demo_listing(job)
    enriched["demo_label"] = demo_badge(job)

    return enriched


# The categories the Resume Parser is instructed to emit (services/resume_parser.py).
SKILL_CATEGORIES = ("programming_language", "framework", "tool", "soft_skill", "other")

CAREER_STATUSES = ("Fresher", "Experienced")

# Column allowlist for the user-owned record tables. The table name and the
# field names are only ever taken from this map, never from the request, so the
# generated SQL cannot be steered by form input.
#
# ``fields`` maps column -> max length, or ``None`` for a free-text column that
# keeps its line breaks (descriptions hold the resume bullet points).
_RECORD_TYPES = {
    "education": {
        "table": "education",
        "label": "Education entry",
        "anchor": "education",
        "required": "institution",
        "fields": {
            "institution": 255,
            "degree": 255,
            "field": 255,
            "start_date": 30,
            "end_date": 30,
        },
    },
    "experience": {
        "table": "experience",
        "label": "Experience entry",
        "anchor": "experience",
        "required": "title",
        "fields": {
            "title": 255,
            "organization": 255,
            "start_date": 30,
            "end_date": 30,
            "description": None,
        },
    },
    "projects": {
        "table": "projects",
        "label": "Project",
        "anchor": "projects",
        "required": "title",
        "fields": {
            "title": 255,
            "description": None,
            "tech_stack": 255,
        },
    },
    "certifications": {
        "table": "certifications",
        "label": "Certification",
        "anchor": "certifications",
        "required": "name",
        "fields": {
            "name": 255,
            "issuer": 255,
            "issue_date": 30,
            "expiry_date": 30,
            "credential_url": 500,
        },
    },
}


def _require_login():
    return "user_id" in session


def _line(value, limit: int):
    """Collapse a form value to a single trimmed line, or None when empty."""
    text = " ".join((value or "").split())
    return text[:limit] or None


def _block(value):
    """Trim a free-text form value while keeping its line breaks."""
    text = (value or "").strip()
    return text or None


def _record_values(spec: dict, form) -> dict:
    return {
        column: (_block(form.get(column)) if limit is None else _line(form.get(column), limit))
        for column, limit in spec["fields"].items()
    }


def _positive_id(raw) -> int | None:
    try:
        value = int(raw or 0)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _record_id(form) -> int | None:
    return _positive_id(form.get("record_id"))


def _skill_id(form) -> int | None:
    return _positive_id(form.get("skill_id"))


def _anchor_redirect(anchor: str):
    """Come back to the section the user was working in."""
    return redirect(f"{url_for('profile.view')}#{anchor}")


def _load_profile(db, user_id: int) -> dict:
    with db.cursor() as cursor:
        cursor.execute("SELECT * FROM profiles WHERE user_id = %s", (user_id,))
        profile = cursor.fetchone() or {}
        cursor.execute("SELECT id, name, category FROM skills WHERE user_id = %s ORDER BY id", (user_id,))
        skills = cursor.fetchall()
        cursor.execute("SELECT * FROM education WHERE user_id = %s ORDER BY id", (user_id,))
        education = cursor.fetchall()
        cursor.execute("SELECT * FROM experience WHERE user_id = %s ORDER BY id", (user_id,))
        experience = cursor.fetchall()
        cursor.execute("SELECT * FROM projects WHERE user_id = %s ORDER BY id", (user_id,))
        projects = cursor.fetchall()
        cursor.execute("SELECT * FROM certifications WHERE user_id = %s ORDER BY id", (user_id,))
        certifications = cursor.fetchall()

    profile["skills"] = skills
    profile["education"] = education
    profile["experience_list"] = experience
    profile["projects"] = projects
    profile["certifications"] = certifications
    return profile


def _build_checklist(db, user_id: int, profile: dict) -> list[dict]:
    with db.cursor() as cursor:
        cursor.execute("SELECT name, phone FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone() or {}
        cursor.execute("SELECT 1 FROM resumes WHERE user_id = %s LIMIT 1", (user_id,))
        has_resume = cursor.fetchone() is not None

    has_experience = bool(profile.get("experience_list")) or bool((profile.get("experience") or "").strip())

    # Education is complete as soon as one usable education record is saved.
    # It used to require college AND degree AND cgpa, but the parser copies
    # college/degree onto the profile from the first entry only, and cgpa stays
    # NULL whenever a resume has none -- so a single valid B.Tech record still
    # showed as Pending. One Diploma + one B.Tech is not required either.
    # The profile-level pair is kept as a fallback so someone who typed their
    # college and degree on the Profile page is not now marked Pending.
    has_education = any(
        (e.get("institution") or "").strip() or (e.get("degree") or "").strip()
        for e in profile.get("education") or []
    ) or bool((profile.get("college") or "").strip() and (profile.get("degree") or "").strip())

    return [
        {"name": "Personal Information", "done": bool(user.get("name") and user.get("phone"))},
        {"name": "Education Details", "done": has_education},
        {"name": "Skills", "done": bool(profile.get("skills"))},
        {"name": "Experience", "done": has_experience},
        {"name": "Projects", "done": bool(profile.get("projects"))},
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

    # pop(), not get() -- this should say "Welcome" exactly once, right after
    # registration, then always "Welcome back" on every visit after that.
    is_new_user = session.pop("just_registered", False)

    user_skills = [s["name"] for s in profile["skills"]]

    # Uses the same semantic + Profile Skill Fit ranking as Opportunities.
    # top_k is only how many ranked rows the Dashboard renders; the retrieval,
    # the 0.65 similarity floor and the ranking itself are untouched.
    from services.opportunity_service import recommend_jobs

    # The Home page ranks this many rows and renders them in a 3-column grid,
    # six at a time behind a "View More" action. Retrieval, the similarity
    # floor and the ranking itself are untouched; only the count differs.
    top_jobs = recommend_jobs("", user_skills, top_k=HOME_JOB_COUNT)

    # Presentation fields for the compact card. The ranking and the rows
    # themselves are untouched; only what the card shows is prepared here.
    top_jobs = [_card_job(job) for job in top_jobs]

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
        is_new_user=is_new_user,
        profile=profile,
        checklist=checklist,
        completeness=completeness,
        resume_uploaded=resume_uploaded,
        top_jobs=top_jobs,
        home_visible_count=min(HOME_VISIBLE_JOBS, len(top_jobs)),
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

    # Group skills by the category the parser assigned so the page mirrors how
    # the rest of the app reads the skills table, without changing the order.
    grouped_skills: dict[str, list] = {}
    for skill in profile["skills"]:
        grouped_skills.setdefault(skill.get("category") or "other", []).append(skill)

    return render_template(
        "profile.html",
        active_page="profile",
        profile=profile,
        user=user,
        completeness=completeness,
        record_types=sorted(_RECORD_TYPES),
        record_specs=_RECORD_TYPES,
        skill_categories=SKILL_CATEGORIES,
        career_statuses=CAREER_STATUSES,
        grouped_skills=grouped_skills,
    )


@profile_bp.route("/edit", methods=["POST"])
def edit():
    """Update the single-row profile details and the authentication row."""
    if not _require_login():
        return redirect(url_for("auth.login"))

    user_id = session["user_id"]
    form = request.form

    name = _line(form.get("name"), 255)
    phone = _line(form.get("phone"), 30)
    career_status = form.get("career_status")
    if career_status not in CAREER_STATUSES:
        career_status = None

    college = _line(form.get("college"), 255)
    degree = _line(form.get("degree"), 255)
    summary = _block(form.get("summary"))
    notes = _block(form.get("experience"))

    passing_year = _line(form.get("passing_year"), 4)
    if passing_year is not None and not passing_year.isdigit():
        flash("Passing year must be a number.", "error")
        passing_year = None

    cgpa = _line(form.get("cgpa"), 5)
    if cgpa is not None:
        try:
            float(cgpa)
        except ValueError:
            flash("CGPA must be a number.", "error")
            cgpa = None

    db = get_db()
    with db.cursor() as cursor:
        # NOTE: skills are intentionally untouched here. They used to be
        # deleted and rebuilt from a comma string, which dropped the
        # parser-assigned `category` on every save. They now have their own
        # add/edit/remove controls below.
        cursor.execute(
            """
            INSERT INTO profiles (user_id, college, degree, passing_year, cgpa, summary, experience)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE college=VALUES(college), degree=VALUES(degree),
                passing_year=VALUES(passing_year), cgpa=COALESCE(VALUES(cgpa), cgpa),
                summary=COALESCE(VALUES(summary), summary), experience=VALUES(experience)
            """,
            (user_id, college, degree, passing_year, cgpa, summary, notes),
        )
        if name or phone or career_status:
            assignments, params = [], []
            if name:
                assignments.append("name=%s")
                params.append(name)
            if phone is not None:
                assignments.append("phone=%s")
                params.append(phone)
            if career_status:
                assignments.append("career_status=%s")
                params.append(career_status)
            if assignments:
                cursor.execute(
                    f"UPDATE users SET {', '.join(assignments)} WHERE id = %s",
                    (*params, user_id),
                )
                if name:
                    session["user_name"] = name
        db.commit()

    flash("Profile updated.")
    return _anchor_redirect("personal")


@profile_bp.route("/record/add", methods=["POST"])
def record_add():
    if not _require_login():
        return redirect(url_for("auth.login"))

    spec = _RECORD_TYPES.get(request.form.get("record_type", ""))
    if spec is None:
        flash("Unknown section.", "error")
        return redirect(url_for("profile.view"))

    values = _record_values(spec, request.form)
    if not values[spec["required"]]:
        flash(f"{spec['label']}: {spec['required'].replace('_', ' ')} is required.", "error")
        return _anchor_redirect(spec["anchor"])

    columns = ["user_id", *values]
    placeholders = ", ".join(["%s"] * len(columns))
    db = get_db()
    with db.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {spec['table']} ({', '.join(columns)}) VALUES ({placeholders})",
            (session["user_id"], *values.values()),
        )
        db.commit()

    flash(f"{spec['label']} added.")
    return _anchor_redirect(spec["anchor"])


@profile_bp.route("/record/update", methods=["POST"])
def record_update():
    if not _require_login():
        return redirect(url_for("auth.login"))

    spec = _RECORD_TYPES.get(request.form.get("record_type", ""))
    record_id = _record_id(request.form)
    if spec is None or record_id is None:
        flash("Unknown section.", "error")
        return redirect(url_for("profile.view"))

    values = _record_values(spec, request.form)
    if not values[spec["required"]]:
        flash(f"{spec['label']}: {spec['required'].replace('_', ' ')} is required.", "error")
        return _anchor_redirect(spec["anchor"])

    assignments = ", ".join(f"{column}=%s" for column in values)
    db = get_db()
    with db.cursor() as cursor:
        # user_id in the WHERE clause keeps one user from editing another's rows.
        cursor.execute(
            f"UPDATE {spec['table']} SET {assignments} WHERE id = %s AND user_id = %s",
            (*values.values(), record_id, session["user_id"]),
        )
        updated = cursor.rowcount
        db.commit()

    flash(f"{spec['label']} updated." if updated else f"{spec['label']} not found.")
    return _anchor_redirect(spec["anchor"])


@profile_bp.route("/record/delete", methods=["POST"])
def record_delete():
    if not _require_login():
        return redirect(url_for("auth.login"))

    spec = _RECORD_TYPES.get(request.form.get("record_type", ""))
    record_id = _record_id(request.form)
    if spec is None or record_id is None:
        flash("Unknown section.", "error")
        return redirect(url_for("profile.view"))

    db = get_db()
    with db.cursor() as cursor:
        cursor.execute(
            f"DELETE FROM {spec['table']} WHERE id = %s AND user_id = %s",
            (record_id, session["user_id"]),
        )
        deleted = cursor.rowcount
        db.commit()

    flash(f"{spec['label']} removed." if deleted else f"{spec['label']} not found.")
    return _anchor_redirect(spec["anchor"])


@profile_bp.route("/skill/add", methods=["POST"])
def skill_add():
    if not _require_login():
        return redirect(url_for("auth.login"))

    user_id = session["user_id"]
    form = request.form
    category = form.get("category")
    if category not in SKILL_CATEGORIES:
        category = None

    added = 0
    db = get_db()
    with db.cursor() as cursor:
        cursor.execute("SELECT name FROM skills WHERE user_id = %s", (user_id,))
        existing = {skill_comparison_key(row["name"]) for row in cursor.fetchall()}

        for raw in form.get("skills", "").split(","):
            name = normalize_skill(raw)
            key = skill_comparison_key(name)
            if not key or key in existing:
                continue
            existing.add(key)
            cursor.execute(
                "INSERT INTO skills (user_id, name, category) VALUES (%s, %s, %s)",
                (user_id, name, category),
            )
            added += 1
        db.commit()

    if added:
        flash(f"Added {added} skill{'s' if added != 1 else ''}.")
    else:
        flash("No new skills to add.", "error")
    return _anchor_redirect("skills")


@profile_bp.route("/skill/update", methods=["POST"])
def skill_update():
    if not _require_login():
        return redirect(url_for("auth.login"))

    user_id = session["user_id"]
    skill_id = _skill_id(request.form)
    if skill_id is None:
        flash("Skill not found.", "error")
        return _anchor_redirect("skills")

    form = request.form
    name = normalize_skill(form.get("name"))
    category = form.get("category")
    if category not in SKILL_CATEGORIES:
        category = None

    if not name:
        flash("Skill name cannot be empty.", "error")
        return _anchor_redirect("skills")

    db = get_db()
    with db.cursor() as cursor:
        cursor.execute(
            "UPDATE skills SET name = %s, category = COALESCE(%s, category) "
            "WHERE id = %s AND user_id = %s",
            (name, category, skill_id, user_id),
        )
        updated = cursor.rowcount
        db.commit()

    flash("Skill updated." if updated else "Skill not found.")
    return _anchor_redirect("skills")


@profile_bp.route("/skill/delete", methods=["POST"])
def skill_delete():
    if not _require_login():
        return redirect(url_for("auth.login"))

    skill_id = _skill_id(request.form)
    if skill_id is None:
        flash("Skill not found.", "error")
        return _anchor_redirect("skills")

    db = get_db()
    with db.cursor() as cursor:
        cursor.execute("DELETE FROM skills WHERE id = %s AND user_id = %s", (skill_id, session["user_id"]))
        deleted = cursor.rowcount
        db.commit()

    flash("Skill removed." if deleted else "Skill not found.")
    return _anchor_redirect("skills")
