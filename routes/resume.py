import os
import re
import uuid

from flask import (
    Blueprint,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

import config
from database.db import get_db
from services.file_extraction import extract_text
from services.resume_parser import parse_resume_text, ResumeParsingError
from services.skill_normalizer import normalize_skill

# The exact column allowlist the profile page validates against, so the two
# edit surfaces cannot drift apart on which columns a section owns.
from routes.profile import CAREER_STATUSES
from routes.profile import _RECORD_TYPES as RECORD_TYPES
from routes.auth import validate_phone

# The categories the Resume Parser is instructed to emit
# (services/resume_parser.py). Shared with routes/profile.py so a skill's
# category dropdown is identical on the profile page and the review page.
SKILL_CATEGORIES = ("programming_language", "framework", "tool", "soft_skill", "other")

resume_bp = Blueprint("resume", __name__, url_prefix="/resume")

os.makedirs(config.UPLOAD_FOLDER, exist_ok=True)


def _require_login():
    return "user_id" in session


def _sanitize_cgpa(raw) -> float | None:
    """
    The LLM may return "8.5", "8.5 CGPA", "85%", or similar -- pull out
    just the number so it fits the DECIMAL(4,2) column instead of
    crashing the insert. Returns None if nothing numeric is found or the
    value is out of range for that column (max 99.99).
    """
    if raw is None:
        return None
    match = re.search(r"\d+(\.\d+)?", str(raw))
    if not match:
        return None
    value = float(match.group())
    return value if 0 <= value <= 99.99 else None


@resume_bp.route("/upload", methods=["GET"])
def upload():
    if not _require_login():
        return redirect(url_for("auth.login"))
    return render_template("resume_upload.html")


@resume_bp.route("/parse", methods=["POST"])
def parse():
    """
    Called via fetch() from resume_upload.js. Runs the full M1.4 pipeline:
    save file -> extract text -> LLM -> validate -> save to MySQL.
    Returns JSON so the page can show the result without a full reload.
    """
    if not _require_login():
        return jsonify({"error": "Not logged in."}), 401

    file = request.files.get("resume")
    if not file or file.filename == "":
        return jsonify({"error": "No file selected."}), 400

    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in config.ALLOWED_RESUME_TYPES:
        return jsonify({"error": "Only PDF and DOCX files are supported."}), 400

    user_id = session["user_id"]
    stored_filename = f"{uuid.uuid4()}.{ext}"
    file_path = os.path.join(config.UPLOAD_FOLDER, stored_filename)
    file.save(file_path)

    db = get_db()
    with db.cursor() as cursor:
        cursor.execute(
            "INSERT INTO resumes (user_id, file_path, file_type, parse_status) VALUES (%s, %s, %s, 'uploaded')",
            (user_id, file_path, ext),
        )
        db.commit()
        resume_id = cursor.lastrowid

    try:
        with db.cursor() as cursor:
            cursor.execute("UPDATE resumes SET parse_status = 'parsing' WHERE id = %s", (resume_id,))
            db.commit()

        raw_text = extract_text(file_path, ext)
        extracted = parse_resume_text(raw_text)
        _save_extracted_profile(db, user_id, resume_id, extracted)

        with db.cursor() as cursor:
            cursor.execute("UPDATE resumes SET parse_status = 'parsed' WHERE id = %s", (resume_id,))
            db.commit()

        session["resume_uploaded"] = True
        return jsonify({"status": "parsed", "profile": extracted})

    except ResumeParsingError as e:
        with db.cursor() as cursor:
            cursor.execute("UPDATE resumes SET parse_status = 'failed' WHERE id = %s", (resume_id,))
            db.commit()
        return jsonify({"status": "failed", "error": str(e)}), 422


@resume_bp.route("/review", methods=["GET"])
def review():
    """Show the profile that resume parsing produced, so it can be checked.

    This renders the rows the parser already wrote -- profiles, education,
    experience, projects, certifications and skills -- grouped into labelled
    sections. It never inserts anything, so reloading it cannot create a second
    profile row. Edits post to the existing profile routes and come back here.
    """
    if not _require_login():
        return redirect(url_for("auth.login"))

    db = get_db()
    user_id = session["user_id"]

    with db.cursor() as cursor:
        cursor.execute(
            "SELECT name, email, phone, career_status FROM users WHERE id = %s",
            (user_id,),
        )
        user = cursor.fetchone() or {}

        cursor.execute("SELECT * FROM profiles WHERE user_id = %s", (user_id,))
        profile = cursor.fetchone() or {}

        cursor.execute(
            "SELECT id, name, category FROM skills WHERE user_id = %s ORDER BY id",
            (user_id,),
        )
        skills = cursor.fetchall()

        cursor.execute(
            "SELECT * FROM education WHERE user_id = %s ORDER BY id", (user_id,)
        )
        education = cursor.fetchall()

        cursor.execute(
            "SELECT * FROM experience WHERE user_id = %s ORDER BY id", (user_id,)
        )
        experience = cursor.fetchall()

        cursor.execute(
            "SELECT * FROM projects WHERE user_id = %s ORDER BY id", (user_id,)
        )
        projects = cursor.fetchall()

        cursor.execute(
            "SELECT * FROM certifications WHERE user_id = %s ORDER BY id", (user_id,)
        )
        certifications = cursor.fetchall()

        # How the most recent upload went, so the page can say whether these
        # values came from a parse or were typed in.
        cursor.execute(
            "SELECT file_type, parse_status, uploaded_at FROM resumes "
            "WHERE user_id = %s ORDER BY id DESC LIMIT 1",
            (user_id,),
        )
        latest_resume = cursor.fetchone()

    # Summary lives on the profile row; the parser writes it there and
    # routes/profile.py edits it there, so there is nothing to derive.
    profile["summary"] = profile.get("summary")

    return render_template(
        "profile_review.html",
        user=user,
        profile=profile,
        skills=skills,
        education=education,
        experience=experience,
        projects=projects,
        certifications=certifications,
        latest_resume=latest_resume,
        skill_categories=SKILL_CATEGORIES,
        record_specs=RECORD_TYPES,
    )


# Post/Redirect/Get back to the review page so a refresh never re-posts an edit.
def _back_to_review(message: str, error: bool = False):
    flash(message, "error" if error else "success")
    return redirect(url_for("resume.review"))


@resume_bp.route("/review/save", methods=["POST"])
def review_save():
    """Persist one Review Your Profile edit.

    A dedicated route rather than reusing ``profile.edit``, because that view
    rewrites ``college``, ``degree``, ``passing_year`` and ``experience`` on
    every submission -- posting a phone-only form from here would silently blank
    those columns. Each section here owns exactly the columns it edits.
    """
    if not _require_login():
        return redirect(url_for("auth.login"))

    user_id = session["user_id"]
    section = request.form.get("section", "")
    form = request.form

    if section == "personal":
        name = _line(form.get("name"), 255)
        phone = _line(form.get("phone"), 30)
        career_status = form.get("career_status")
        if career_status not in CAREER_STATUSES:
            career_status = None

        errors = {}
        if not name:
            errors["name"] = "Name is required."
        # Same ten-digit rule as registration, but only when a phone is given.
        if phone:
            validated, phone_error = validate_phone(phone)
            if phone_error:
                errors["phone"] = phone_error
            else:
                phone = validated
        if errors:
            flash("; ".join(errors.values()), "error")
            return redirect(url_for("resume.review"))

        assignments, params = [], []
        if name:
            assignments.append("name = %s")
            params.append(name)
        if phone is not None:
            assignments.append("phone = %s")
            params.append(phone)
        if career_status:
            assignments.append("career_status = %s")
            params.append(career_status)

        if assignments:
            db = get_db()
            with db.cursor() as cursor:
                cursor.execute(
                    f"UPDATE users SET {', '.join(assignments)} WHERE id = %s",
                    (*params, user_id),
                )
                db.commit()
            if name:
                # Keep the shell's greeting in step with the new name.
                session["user_name"] = name
        return _back_to_review("Personal information updated.")

    if section == "summary":
        summary = _block(form.get("summary"), 4000)
        db = get_db()
        with db.cursor() as cursor:
            # Upsert so a user who typed a summary before ever uploading a
            # resume still gets a profile row rather than a silent no-op.
            cursor.execute(
                """
                INSERT INTO profiles (user_id, summary) VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE summary = VALUES(summary)
                """,
                (user_id, summary),
            )
            db.commit()
        return _back_to_review("Professional summary updated.")

    if section == "skills":
        skill_id = _positive_int(form.get("skill_id"))
        name = normalize_skill(form.get("name"))
        category = form.get("category")
        if category not in SKILL_CATEGORIES:
            category = None
        if not name:
            return _back_to_review("Skill name cannot be empty.", error=True)

        db = get_db()
        with db.cursor() as cursor:
            if skill_id is None:
                cursor.execute(
                    "INSERT INTO skills (user_id, name, category) VALUES (%s, %s, %s)",
                    (user_id, name, category),
                )
            else:
                # user_id in the WHERE clause keeps one user off another's rows.
                cursor.execute(
                    "UPDATE skills SET name = %s, category = %s WHERE id = %s AND user_id = %s",
                    (name, category, skill_id, user_id),
                )
                if cursor.rowcount == 0:
                    return _back_to_review("Skill not found.", error=True)
            db.commit()
        return _back_to_review("Skills updated.")

    spec = RECORD_TYPES.get(section)
    if spec is None:
        return _back_to_review("Unknown section.", error=True)

    values = {
        column: (_block(form.get(column), 4000) if limit is None else _line(form.get(column), limit))
        for column, limit in spec["fields"].items()
    }
    if not values[spec["required"]]:
        return _back_to_review(
            f"{spec['label']}: {spec['required'].replace('_', ' ')} is required.", error=True
        )

    record_id = _positive_int(form.get("record_id"))
    db = get_db()
    with db.cursor() as cursor:
        if record_id is None:
            columns = ["user_id", *values]
            placeholders = ", ".join(["%s"] * len(columns))
            cursor.execute(
                f"INSERT INTO {spec['table']} ({', '.join(columns)}) VALUES ({placeholders})",
                (user_id, *values.values()),
            )
        else:
            assignments = ", ".join(f"{column} = %s" for column in values)
            cursor.execute(
                f"UPDATE {spec['table']} SET {assignments} WHERE id = %s AND user_id = %s",
                (*values.values(), record_id, user_id),
            )
            if cursor.rowcount == 0:
                return _back_to_review(f"{spec['label']} not found.", error=True)
        db.commit()
    return _back_to_review(f"{spec['label']} updated.")


def _positive_int(raw) -> int | None:
    try:
        value = int(raw or 0)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _line(value, limit: int):
    return " ".join((value or "").split())[:limit] or None


def _block(value, limit: int):
    return (value or "").strip()[:limit] or None


def _save_extracted_profile(db, user_id: int, resume_id: int, extracted: dict) -> None:
    with db.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO profiles (user_id, resume_id, summary, cgpa)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE resume_id = VALUES(resume_id), summary = VALUES(summary),
                cgpa = COALESCE(VALUES(cgpa), cgpa)
            """,
            (user_id, resume_id, extracted.get("summary"), _sanitize_cgpa(extracted.get("cgpa"))),
        )
        cursor.execute("DELETE FROM skills WHERE user_id = %s", (user_id,))
        cursor.execute("DELETE FROM education WHERE user_id = %s", (user_id,))
        cursor.execute("DELETE FROM experience WHERE user_id = %s", (user_id,))
        cursor.execute("DELETE FROM projects WHERE user_id = %s", (user_id,))
        cursor.execute("DELETE FROM certifications WHERE user_id = %s", (user_id,))

        for s in extracted.get("skills", []):
            cursor.execute(
                "INSERT INTO skills (user_id, name, category) VALUES (%s, %s, %s)",
                (user_id, s.get("name"), s.get("category")),
            )
        for e in extracted.get("education", []):
            cursor.execute(
                "INSERT INTO education (user_id, institution, degree, field, start_date, end_date) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (user_id, e.get("institution"), e.get("degree"), e.get("field"), e.get("start_date"), e.get("end_date")),
            )
            if e.get("institution"):
                cursor.execute(
                    "UPDATE profiles SET college = %s, degree = %s WHERE user_id = %s",
                    (e.get("institution"), e.get("degree"), user_id),
                )
        for x in extracted.get("experience", []):
            cursor.execute(
                "INSERT INTO experience (user_id, title, organization, start_date, end_date, description) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (user_id, x.get("title"), x.get("organization"), x.get("start_date"), x.get("end_date"), x.get("description")),
            )
        for p in extracted.get("projects", []):
            cursor.execute(
                "INSERT INTO projects (user_id, title, description, tech_stack) VALUES (%s, %s, %s, %s)",
                (user_id, p.get("title"), p.get("description"), p.get("tech_stack")),
            )
        for c in extracted.get("certifications", []):
            if not c.get("name"):
                continue
            cursor.execute(
                """
                INSERT INTO certifications
                    (user_id, name, issuer, issue_date, expiry_date, credential_url)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    user_id,
                    c.get("name"),
                    c.get("issuer"),
                    c.get("issue_date"),
                    c.get("expiry_date"),
                    c.get("credential_url"),
                ),
            )
        db.commit()