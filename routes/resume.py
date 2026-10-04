import os
import re
import uuid

from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify

import config
from database.db import get_db
from services.file_extraction import extract_text
from services.resume_parser import parse_resume_text, ResumeParsingError

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