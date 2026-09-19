from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash

from database.db import get_db

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html")

    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    phone = request.form.get("phone", "").strip()
    password = request.form.get("password", "")
    confirm_password = request.form.get("confirm_password", "")
    career_status = request.form.get("career_status", "Fresher")

    if not name or not email or not password:
        flash("Name, email, and password are required.")
        return render_template("register.html"), 400
    if password != confirm_password:
        flash("Passwords do not match.")
        return render_template("register.html"), 400
    if len(password) < 6:
        flash("Password must be at least 6 characters.")
        return render_template("register.html"), 400
    if career_status not in ("Fresher", "Experienced"):
        career_status = "Fresher"

    db = get_db()
    with db.cursor() as cursor:
        cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
        if cursor.fetchone():
            flash("An account with this email already exists.")
            return render_template("register.html"), 409

        cursor.execute(
            "INSERT INTO users (name, email, phone, password_hash, career_status) "
            "VALUES (%s, %s, %s, %s, %s)",
            (name, email, phone, generate_password_hash(password), career_status),
        )
        db.commit()
        user_id = cursor.lastrowid

    session["user_id"] = user_id
    session["user_name"] = name
    session["resume_uploaded"] = False
    return redirect(url_for("resume.upload"))


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    db = get_db()
    with db.cursor() as cursor:
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()

    if not user or not check_password_hash(user["password_hash"], password):
        flash("Incorrect email or password.")
        return render_template("login.html"), 401

    session["user_id"] = user["id"]
    session["user_name"] = user["name"]

    with db.cursor() as cursor:
        cursor.execute("SELECT 1 FROM profiles WHERE user_id = %s", (user["id"],))
        session["resume_uploaded"] = cursor.fetchone() is not None

    return redirect(url_for("home.dashboard") if session["resume_uploaded"] else url_for("resume.upload"))


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    # Placeholder -- real email-based reset flow is a later addition.
    # Kept as its own route/template now so the link works and the intent
    # is clear, rather than a dead link on the login page.
    if request.method == "POST":
        flash("If that email is registered, a reset link would be sent. (Not wired up yet.)")
    return render_template("forgot_password.html")


@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("landing"))
