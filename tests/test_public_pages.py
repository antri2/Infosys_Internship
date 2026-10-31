"""Public pages: design system, auth validation, and the profile review.

These pin the behaviour the redesign had to get right, not the styling itself:
that the dead menu and dead links are gone, that password and phone rules are
enforced on the server as well as in the browser, that Forgot Password never
claims to have sent something it did not send, and that the profile review page
shows stored values, labels missing ones, and persists edits without ever
creating a second profile row.
"""

import re

import pytest

from routes.auth import password_problems, validate_phone


# --------------------------------------------------------------- password ---

VALID_PASSWORD = "Str0ng!Pass"


def test_a_full_strength_password_has_no_unmet_requirements():
    assert password_problems(VALID_PASSWORD) == []


@pytest.mark.parametrize("password, expected", [
    ("Sh0rt!a", "at least 8 characters"),      # 7 characters
    ("str0ng!pass", "one uppercase letter"),
    ("STR0NG!PASS", "one lowercase letter"),
    ("StrongPass!", "one number"),
    ("StrongPass1", "one special character"),
])
def test_each_requirement_is_reported_individually(password, expected):
    unmet = password_problems(password)
    assert len(unmet) == 1, unmet
    assert unmet[0] == expected


def test_several_missing_requirements_are_all_reported():
    assert password_problems("abc") == [
        "at least 8 characters",
        "one uppercase letter",
        "one number",
        "one special character",
    ]


def test_the_former_six_character_rule_is_gone():
    """The old route accepted anything at six characters.

    Six characters with no digit or symbol used to be enough; it must not be.
    """
    assert password_problems("Abcdef") != []


# ------------------------------------------------------------------ phone ---

@pytest.mark.parametrize("raw, expected", [
    ("9876543210", ("9876543210", None)),
    ("  9876543210  ", ("9876543210", None)),
    ("", (None, None)),                      # optional, stores NULL
    ("   ", (None, None)),
])
def test_ten_digit_phones_are_accepted(raw, expected):
    assert validate_phone(raw) == expected


@pytest.mark.parametrize("raw", [
    "123456789",        # nine digits
    "12345678901",      # eleven digits
    "98765 43210",      # space inside
    "98a6543210",       # a letter
    "+919876543210",    # country code
    "98765-43210",      # punctuation
])
def test_everything_other_than_exactly_ten_digits_is_rejected(raw):
    value, error = validate_phone(raw)
    assert value is None
    assert "exactly 10 digits" in error


# ------------------------------------------------------------- register ---

def _register(client, **overrides):
    data = {
        "name": "Test Person",
        "email": "new-user@example.test",
        "phone": "9876543210",
        "password": VALID_PASSWORD,
        "confirm_password": VALID_PASSWORD,
        "career_status": "Fresher",
    }
    data.update(overrides)
    return client.post("/register", data=data)


def test_a_valid_registration_succeeds_and_redirects_to_the_upload_step(client):
    response = _register(client)
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/resume/upload")


def test_phone_is_optional_and_stored_as_null(client, app):
    assert _register(client, email="nophone@example.test", phone="").status_code == 302

    with app.app_context():
        from database.db import get_db
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT phone FROM users WHERE email = %s",
                           ("nophone@example.test",))
            assert cursor.fetchone()["phone"] is None


@pytest.mark.parametrize("bad_phone", ["12345", "12345678901", "abc1234567", "98765 43210"])
def test_an_invalid_phone_is_rejected_with_an_inline_message(client, bad_phone):
    response = _register(client, phone=bad_phone)
    assert response.status_code == 400
    assert "exactly 10 digits" in response.get_data(as_text=True)


def test_a_weak_password_is_rejected_with_a_named_requirement(client):
    response = _register(client, password="abc", confirm_password="abc")
    assert response.status_code == 400
    body = response.get_data(as_text=True)
    assert "at least 8 characters" in body
    assert "one uppercase letter" in body


def test_mismatched_passwords_are_rejected(client):
    response = _register(client, confirm_password="Different1!")
    assert response.status_code == 400
    assert "Passwords do not match" in response.get_data(as_text=True)


def test_a_rejected_submission_keeps_what_was_typed(client):
    """No retyping: the form comes back with the submitted values."""
    response = _register(client, name="Keep Me", phone="12345")
    body = response.get_data(as_text=True)
    assert 'value="Keep Me"' in body
    assert 'value="new-user@example.test"' in body


def test_a_rejected_registration_creates_no_user(app):
    """The email must be unique to this test, or an earlier one created it."""
    from database.db import get_db
    email = "rejected@example.test"
    _register(app.test_client(), email=email, phone="12345")

    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS n FROM users WHERE email = %s", (email,))
            assert cursor.fetchone()["n"] == 0


def test_a_duplicate_email_is_refused(app):
    """Register once, then again, and the second must be refused."""
    client = app.test_client()
    email = "duplicate@example.test"

    assert _register(client, email=email).status_code == 302
    second = _register(client, email=email)

    assert second.status_code == 409
    assert "already exists" in second.get_data(as_text=True)

    from database.db import get_db
    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS n FROM users WHERE email = %s", (email,))
            assert cursor.fetchone()["n"] == 1


# ----------------------------------------------------------------- login ---

def test_login_rejects_a_wrong_password_without_saying_which_part_failed(app):
    """The message must not reveal whether the address is registered."""
    client = app.test_client()
    response = client.post("/login", data={"email": "step1-missing@example.test",
                                           "password": "wrong"})
    body = response.get_data(as_text=True)
    assert response.status_code == 401
    assert "Incorrect email or password" in body
    assert "no account" not in body.casefold()


# ------------------------------------------------------- forgot password ---

def test_forgot_password_never_claims_to_have_sent_anything(client):
    """The old flash said a link "would be sent", which it never did."""
    response = client.post("/forgot-password", data={"email": "step1-missing@example.test"})
    body = response.get_data(as_text=True).casefold()
    assert response.status_code == 200
    # The old wording promised an email that was never dispatched.
    assert "would be sent" not in body
    assert "not wired up yet" not in body
    assert "reset link would" not in body
    # It must state plainly that nothing was sent.
    assert "no reset link was sent" in body
    assert "not available" in body


def test_forgot_password_explains_the_limitation_before_any_submission(client):
    html = client.get("/forgot-password").get_data(as_text=True)
    assert "no email provider" in html
    assert "Nothing will be emailed" in html


def test_forgot_password_gives_the_user_a_working_way_forward(client):
    html = client.get("/forgot-password").get_data(as_text=True)
    assert 'href="/login"' in html


# ------------------------------------------------------- landing / design ---

def test_landing_page_renders(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "CareerAI" in response.get_data(as_text=True)


def test_the_laptop_image_and_emoji_visuals_are_gone(client):
    html = client.get("/").get_data(as_text=True)
    assert "&#128187;" not in html          # the laptop emoji
    assert "hero-illustration" not in html


def test_the_nonfunctional_menu_button_is_removed(client):
    """It toggled a body class that no landing rule ever reacted to."""
    html = client.get("/").get_data(as_text=True)
    assert 'id="hamburger"' not in html
    assert "hamburger" not in html


def test_the_dead_placeholder_links_are_gone(client):
    """Help Center / FAQs / Privacy Policy were href="#" and did nothing."""
    html = client.get("/").get_data(as_text=True)
    assert 'href="#"' not in html
    for dead in ("Help Center", "FAQs", "Privacy Policy"):
        assert dead not in html


def test_every_anchor_on_the_landing_page_resolves(client, app):
    """No link may point at a fragment that does not exist on the page."""
    html = client.get("/").get_data(as_text=True)
    ids = set(re.findall(r'id="([^"]+)"', html))
    for fragment in re.findall(r'href="#([^"]+)"', html):
        assert fragment in ids, f'href="#{fragment}" has no target on the page'


def test_every_internal_link_points_at_a_real_route(client, app):
    html = client.get("/").get_data(as_text=True)
    paths = {rule.rule for rule in app.url_map.iter_rules()}
    for href in re.findall(r'href="(/[^"]*)"', html):
        # Static files are served by Flask's own /static/ handler rather than a
        # named rule, and the asset itself is checked by the test below.
        if href.startswith("/static/"):
            continue
        path = href.split("?")[0].rstrip("/") or "/"
        assert path in paths or (path + "/") in paths, href


def test_landing_has_the_neural_background(client):
    html = client.get("/").get_data(as_text=True)
    assert "sc-neural" in html
    assert "sc-node" in html
    assert "sc-edge" in html


def test_the_public_pages_share_one_design_system(client):
    for path in ("/", "/login", "/register", "/forgot-password"):
        html = client.get(path).get_data(as_text=True)
        assert "sc-neural" in html, path
        assert 'class="sc-brand"' in html, path
        assert "surface" in html, path


def test_public_pages_do_not_use_emoji_icons(client):
    """CareerAI-relevant line icons replaced the generic emoji set."""
    for path in ("/", "/login", "/register"):
        html = client.get(path).get_data(as_text=True)
        assert "&#128269;" not in html, path
        assert "&#10024;" not in html, path


def test_login_page_has_a_password_show_hide_control(client):
    html = client.get("/login").get_data(as_text=True)
    assert 'data-password-toggle="password"' in html
    assert 'aria-label="Show password"' in html
    assert 'aria-pressed="false"' in html
    # The password field starts masked.
    assert 'id="password" name="password" required' in html
    assert 'type="password" id="password"' in html


def test_login_links_to_register_and_forgot_password(client):
    html = client.get("/login").get_data(as_text=True)
    assert 'href="/register"' in html
    assert 'href="/forgot-password"' in html


def test_register_page_declares_the_password_requirements(client):
    html = client.get("/register").get_data(as_text=True)
    for rule in ('data-rule="length"', 'data-rule="upper"', 'data-rule="lower"',
                 'data-rule="digit"', 'data-rule="special"'):
        assert rule in html
    assert "At least 8 characters" in html


def test_register_page_constrains_the_phone_input(client):
    html = client.get("/register").get_data(as_text=True)
    phone_input = re.search(r'<input[^>]*id="phone"[^>]*>', html).group(0)
    assert 'maxlength="10"' in phone_input
    assert 'pattern="[0-9]{10}"' in phone_input
    assert 'inputmode="numeric"' in phone_input


def test_register_page_has_a_live_strength_meter(client):
    html = client.get("/register").get_data(as_text=True)
    assert 'id="strength"' in html
    assert 'data-level="0"' in html
    assert 'id="strength-label"' in html
    assert "data-strength-source" in html


@pytest.mark.parametrize("field", ["name", "email", "phone", "password", "confirm_password"])
def test_every_field_has_an_error_box_the_script_can_write_into(client, field):
    """auth_forms.js finds messages with `<field-id>-error`.

    Without that id the field still turned red but no text ever appeared, which
    is worse than no validation at all.
    """
    html = client.get("/register").get_data(as_text=True)
    assert f'id="{field}-error"' in html, field
    assert f'id="{field}"' in html, field


def test_the_password_meter_starts_empty_even_with_a_stored_value(client):
    """The meter must not claim "strong" before anything is typed.

    A browser that restores a password field would otherwise paint a passing
    score for a value the server has not seen.
    """
    html = client.get("/register").get_data(as_text=True)
    strength = re.search(r'<div class="sc-strength"[^>]*>', html).group(0)
    assert 'data-level="0"' in strength
    label = re.search(r'<span class="sc-strength__label"[^>]*>', html).group(0)
    assert 'data-level="0"' in label
    assert "not set" in html


def test_register_page_keeps_the_original_fields(client):
    """Existing registration fields and their names must not change."""
    html = client.get("/register").get_data(as_text=True)
    for field in ("name", "email", "phone", "password", "confirm_password",
                  "career_status"):
        assert f'name="{field}"' in html, field
    assert 'value="Fresher"' in html
    assert 'value="Experienced"' in html


# ------------------------------------------------------- profile review ---

def _seed(app, user_id):
    """Give the candidate one row in every section the review page reads.

    The ``candidate`` fixture has already inserted the profile row, so the
    profile is updated rather than inserted -- exactly what a re-upload does,
    and the reason a duplicate profile cannot appear here.
    """
    from database.db import get_db
    db = get_db()
    with db.cursor() as cursor:
        cursor.execute(
            "UPDATE profiles SET college = %s, degree = %s, summary = %s "
            "WHERE user_id = %s",
            ("AKS University", "B.Tech",
             "Final year student focused on data analysis.", user_id),
        )
        cursor.execute(
            "INSERT INTO education (user_id, institution, degree, field, start_date, end_date) "
            "VALUES (%s, 'AKS University', 'B.Tech', 'Computer Science', '2022', '2026')",
            (user_id,),
        )
        education_id = cursor.lastrowid
        for name, category in (("Python", "programming_language"), ("SQL", "tool")):
            cursor.execute("INSERT INTO skills (user_id, name, category) VALUES (%s, %s, %s)",
                           (user_id, name, category))
        cursor.execute(
            "INSERT INTO experience (user_id, title, organization, start_date, end_date, description) "
            "VALUES (%s, 'Data Analyst Intern', 'Infosys', '2025-06', '2025-08', %s)",
            (user_id, "Built Power BI dashboards."),
        )
        cursor.execute(
            "INSERT INTO projects (user_id, title, description, tech_stack) "
            "VALUES (%s, 'Resume Ranker', %s, 'Python, FAISS')",
            (user_id, "FAISS based resume screening."),
        )
        cursor.execute(
            "INSERT INTO certifications (user_id, name, issuer) "
            "VALUES (%s, 'AWS Certified Developer', 'Amazon')",
            (user_id,),
        )
    db.commit()
    return education_id


@pytest.fixture
def reviewed(app, client, candidate):
    with app.app_context():
        education_id = _seed(app, candidate["user_id"])
    return {"education_id": education_id}


def test_review_requires_authentication(app):
    assert app.test_client().get("/resume/review").status_code == 302


def test_review_renders_all_seven_sections(client, reviewed):
    html = client.get("/resume/review").get_data(as_text=True)
    for section in ("Personal Information", "Professional Summary", "Education",
                    "Skills", "Work Experience", "Projects", "Certifications"):
        assert f">{section}<" in html, section


def test_review_shows_the_values_that_are_stored(client, reviewed):
    html = client.get("/resume/review").get_data(as_text=True)
    for value in ("AKS University", "B.Tech", "Computer Science", "Python", "SQL",
                  "Infosys", "Data Analyst Intern", "Resume Ranker",
                  "AWS Certified Developer", "Final year student"):
        assert value in html, value


def test_review_shows_the_graduation_year_when_one_is_stored(client, reviewed):
    html = client.get("/resume/review").get_data(as_text=True)
    assert "Graduation 2026" in html


def test_review_labels_a_missing_field_instead_of_inventing_it(client, reviewed):
    """The candidate fixture has no phone, so the row must say so."""
    html = client.get("/resume/review").get_data(as_text=True)
    assert "Not provided" in html
    assert 'class="sc-none">Not provided<' in html


def test_a_record_missing_its_organisation_says_so(client, reviewed, app):
    from database.db import get_db
    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("UPDATE experience SET organization = NULL")
        db.commit()

    html = client.get("/resume/review").get_data(as_text=True)
    assert "Organisation not provided" in html


def test_an_education_row_without_a_year_gets_no_made_up_one(client, reviewed, app):
    """The seeded row ends in 2026; a row with no end_date must say so."""
    from database.db import get_db
    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute(
                "INSERT INTO education (user_id, institution, degree, field) "
                "VALUES ((SELECT id FROM users ORDER BY id DESC LIMIT 1), "
                "'Somewhere College', 'B.Sc', '')")
        db.commit()

    html = client.get("/resume/review").get_data(as_text=True)
    assert "Graduation year not provided" in html
    # The row that does have a year still shows it.
    assert "Graduation 2026" in html


def test_review_distinguishes_the_professional_summary(client, reviewed):
    """The summary is prose in its own panel, not another key/value row."""
    html = client.get("/resume/review").get_data(as_text=True)
    summary_panel = html.split('id="panel-summary"', 1)[1].split('</section>', 1)[0]
    assert "Final year student focused on data analysis." in summary_panel
    assert 'class="sc-summary"' in summary_panel


def test_review_offers_an_empty_state_for_a_section_with_nothing_in_it(client, reviewed):
    """Certifications were seeded, so delete them to exercise the empty state."""
    from database.db import get_db
    with client.application.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("DELETE FROM certifications")
        db.commit()

    html = client.get("/resume/review").get_data(as_text=True)
    assert "No certifications were extracted" in html


def test_every_section_has_an_edit_control(client, reviewed):
    html = client.get("/resume/review").get_data(as_text=True)
    for section in ("personal", "summary", "education", "skills",
                    "experience", "projects", "certifications"):
        assert f'data-edit-toggle="edit-{section}"' in html, section
        assert f'id="edit-{section}"' in html, section


def test_edit_regions_start_closed(client, reviewed):
    html = client.get("/resume/review").get_data(as_text=True)
    for section in ("personal", "summary", "education", "skills",
                    "experience", "projects", "certifications"):
        assert f'<div class="sc-panel__edit" id="edit-{section}" hidden>' in html, section


def test_saving_personal_information_persists(client, reviewed, app, candidate):
    from database.db import get_db

    response = client.post("/resume/review/save", data={
        "section": "personal", "name": "Renamed Candidate",
        "phone": "9123456789", "career_status": "Experienced",
    })
    assert response.status_code == 302

    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute(
                "SELECT name, phone, career_status FROM users WHERE id = %s",
                (candidate["user_id"],))
            row = cursor.fetchone()

    assert row["name"] == "Renamed Candidate"
    assert row["phone"] == "9123456789"
    assert row["career_status"] == "Experienced"


def test_a_personal_save_rejects_an_invalid_phone(client, reviewed):
    response = client.post("/resume/review/save", data={
        "section": "personal", "name": "Renamed Candidate", "phone": "12345",
    }, follow_redirects=True)
    assert "exactly 10 digits" in response.get_data(as_text=True)


def test_a_personal_save_does_not_blank_the_profile_columns(client, reviewed, app,
                                                             candidate):
    """profile.edit rewrites college/degree on every POST; this must not.

    The review page has its own endpoint precisely so that saving a phone
    number cannot clear the education the parser stored.
    """
    from database.db import get_db
    client.post("/resume/review/save", data={
        "section": "personal", "name": "Renamed Candidate",
        "phone": "9123456789", "career_status": "Experienced",
    })

    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT college, degree, summary FROM profiles "
                           "WHERE user_id = %s", (candidate["user_id"],))
            row = cursor.fetchone()

    assert row is not None
    assert row["college"] == "AKS University"
    assert row["degree"] == "B.Tech"
    assert row["summary"] == "Final year student focused on data analysis."


def test_saving_the_summary_persists(client, reviewed, app, candidate):
    from database.db import get_db
    client.post("/resume/review/save", data={
        "section": "summary", "summary": "Rewritten by the user.",
    })

    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT summary FROM profiles WHERE user_id = %s",
                           (candidate["user_id"],))
            assert cursor.fetchone()["summary"] == "Rewritten by the user."


def test_editing_an_education_row_persists(client, reviewed):
    response = client.post("/resume/review/save", data={
        "section": "education", "record_id": str(reviewed["education_id"]),
        "institution": "IIT Delhi", "degree": "B.Tech", "field": "CS",
        "start_date": "2021", "end_date": "2025",
    }, follow_redirects=True)
    assert "IIT Delhi" in response.get_data(as_text=True)


def test_adding_an_education_row_inserts_without_touching_the_others(client, reviewed):
    client.post("/resume/review/save", data={
        "section": "education", "institution": "New College",
        "degree": "B.Sc", "field": "Physics",
        "start_date": "2026", "end_date": "2029",
    }, follow_redirects=True)

    from database.db import get_db
    with client.application.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS n FROM education")
            assert cursor.fetchone()["n"] >= 2


def test_adding_a_skill_persists(client, reviewed):
    response = client.post("/resume/review/save", data={
        "section": "skills", "skill_id": "", "name": "FastAPI", "category": "framework",
    }, follow_redirects=True)
    assert "FastAPI" in response.get_data(as_text=True)


def test_a_skill_save_with_a_blank_name_is_refused(client, reviewed):
    response = client.post("/resume/review/save", data={
        "section": "skills", "skill_id": "", "name": "   ",
    }, follow_redirects=True)
    assert "cannot be empty" in response.get_data(as_text=True)


def test_an_unknown_section_is_refused(client, reviewed):
    response = client.post("/resume/review/save",
                           data={"section": "drop_tables"}, follow_redirects=True)
    assert "Unknown section" in response.get_data(as_text=True)


def test_saving_requires_authentication(app):
    response = app.test_client().post("/resume/review/save", data={"section": "summary"})
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_another_user_cannot_edit_someone_elses_record(client, reviewed, app):
    """Ownership is enforced in SQL, so a foreign id changes nothing."""
    client.post("/resume/review/save", data={
        "section": "education", "record_id": "999999999",
        "institution": "Hijacked",
    }, follow_redirects=True)

    from database.db import get_db
    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS n FROM education WHERE institution = 'Hijacked'")
            assert cursor.fetchone()["n"] == 0


def test_reviewing_twice_creates_no_duplicate_profile_row(client, reviewed, app,
                                                         candidate):
    """Loading the page must never insert anything."""
    client.get("/resume/review")
    client.get("/resume/review")

    from database.db import get_db
    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS n FROM profiles WHERE user_id = %s",
                           (candidate["user_id"],))
            assert cursor.fetchone()["n"] == 1


def test_the_resume_pipeline_itself_is_unchanged():
    """The review step is additive; the parse pipeline must still be intact."""
    from routes import resume as resume_routes
    assert hasattr(resume_routes, "parse")
    assert hasattr(resume_routes, "_save_extracted_profile")
    assert resume_routes.SKILL_CATEGORIES == (
        "programming_language", "framework", "tool", "soft_skill", "other")


def test_the_app_shell_never_loads_the_public_design_system(client, candidate):
    """landing.css is opt-in per template, so the app shell cannot see it."""
    for path in ("/home", "/profile/", "/opportunities/"):
        html = client.get(path).get_data(as_text=True)
        assert "landing.css" not in html, path
        assert "sc-neural" not in html, path
        assert 'class="sc-brand"' not in html, path


def test_every_public_page_does_load_the_design_system(client):
    for path in ("/", "/login", "/register", "/forgot-password"):
        html = client.get(path).get_data(as_text=True)
        assert "css/landing.css" in html, path