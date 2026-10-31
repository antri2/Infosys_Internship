import re

from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash

from database.db import get_db

auth_bp = Blueprint("auth", __name__)


# Registration rules. These are the server-side source of truth for the five
# password requirements and the phone format; static/js/auth_forms.js mirrors
# them so the browser and the server never disagree about what is acceptable.
PASSWORD_MIN_LENGTH = 8
PHONE_DIGITS = 10

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$")
_PHONE_RE = re.compile(r"^[0-9]{%d}$" % PHONE_DIGITS)

# Each rule is (key, predicate, message). Ordered so the first failing rule is
# the most useful one to show.
_PASSWORD_CHECKS = (
    ("length", lambda p: len(p) >= PASSWORD_MIN_LENGTH,
     "at least %d characters" % PASSWORD_MIN_LENGTH),
    ("upper", lambda p: any(c.isupper() for c in p), "one uppercase letter"),
    ("lower", lambda p: any(c.islower() for c in p), "one lowercase letter"),
    ("digit", lambda p: any(c.isdigit() for c in p), "one number"),
    ("special", lambda p: any(not c.isalnum() for c in p), "one special character"),
)


def password_problems(password: str) -> list[str]:
    """Return the unmet password requirements, in a stable order.

    An empty result means the password is acceptable. Kept as a module-level
    function so the tests can pin the rules without going through a request.
    """
    return [message for _, check, message in _PASSWORD_CHECKS if not check(password)]


def validate_phone(raw: str) -> tuple[str | None, str | None]:
    """Normalise a submitted phone number.

    Returns ``(value, error)``. Exactly one of the two is set. An empty phone is
    accepted and stored as NULL because the column is nullable and phone has
    never been mandatory; anything present must be exactly ten digits with no
    spaces, punctuation or country code.
    """
    value = " ".join((raw or "").split())
    if not value:
        return None, None
    if not _PHONE_RE.match(value):
        return None, "Phone number must be exactly %d digits." % PHONE_DIGITS
    return value, None


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html")

    form = request.form
    name = form.get("name", "").strip()
    email = form.get("email", "").strip().lower()
    phone_raw = form.get("phone", "").strip()
    password = form.get("password", "")
    confirm_password = form.get("confirm_password", "")
    career_status = form.get("career_status", "Fresher")

    errors: dict[str, str] = {}

    if not name:
        errors["name"] = "Name is required."
    elif len(name) > 255:
        errors["name"] = "Name must be 255 characters or fewer."

    if not email:
        errors["email"] = "Email is required."
    elif not _EMAIL_RE.match(email):
        errors["email"] = "Enter a valid email address."
    elif len(email) > 255:
        errors["email"] = "Email must be 255 characters or fewer."

    # Exactly ten digits, or nothing at all. Never stored partially.
    phone, phone_error = validate_phone(phone_raw)
    if phone_error:
        errors["phone"] = phone_error

    if not password:
        errors["password"] = "Password is required."
    else:
        unmet = password_problems(password)
        if unmet:
            errors["password"] = "Password needs " + ", ".join(unmet) + "."

    if not confirm_password:
        errors["confirm_password"] = "Please confirm your password."
    elif password and confirm_password != password:
        errors["confirm_password"] = "Passwords do not match."

    if not errors:
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
            if cursor.fetchone():
                flash("An account with this email already exists.", "error")
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
        session["just_registered"] = True
        return redirect(url_for("resume.upload"))

    # Re-render with the submitted values so nothing has to be retyped, and
    # list every problem at once rather than one per submit.
    flash("Please correct the highlighted fields.", "error")
    return render_template(
        "register.html",
        form_values={
            "name": name,
            "email": email,
            "phone": phone_raw,
            "career_status": career_status if career_status in ("Fresher", "Experienced") else "Fresher",
        },
        field_errors=errors,
    ), 400


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

    # One message for both a missing account and a wrong password, so the form
    # cannot be used to discover which emails are registered.
    if not user or not check_password_hash(user["password_hash"], password):
        flash("Incorrect email or password.", "error")
        return render_template("login.html"), 401

    session["user_id"] = user["id"]
    session["user_name"] = user["name"]

    with db.cursor() as cursor:
        cursor.execute("SELECT 1 FROM profiles WHERE user_id = %s", (user["id"],))
        session["resume_uploaded"] = cursor.fetchone() is not None

    return redirect(url_for("home.dashboard") if session["resume_uploaded"] else url_for("resume.upload"))


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    """Password reset.

    CareerAI has no outbound email provider configured, so this route cannot
    send a reset link. It therefore says exactly that instead of the previous
    message, which read as a confirmation that an email was on its way when
    nothing had been sent.

    Resetting by emailed token is a real feature that needs an email provider
    and a `password_reset_tokens` table; adding a stub would only reintroduce
    the same problem this message fixes.
    """
    if request.method == "POST":
        flash(
            "Password reset by email is not available in this deployment, so no "
            "reset link was sent. Please contact your CareerAI administrator.",
            "error",
        )
    return render_template("forgot_password.html")


@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("landing"))