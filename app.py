from flask import Flask, g, render_template, session

import config
from database import db
from routes.auth import auth_bp
from routes.resume import resume_bp
from routes.profile import profile_bp, home_bp
from routes.job_routes import job_bp
from routes.opportunities import opportunities_bp
from routes.applications import applications_bp
from routes.interview import interview_bp
from routes.assistant import assistant_bp
from routes.resume_builder import resume_builder_bp
from routes.cover_letter import cover_letter_bp
from routes.skill_gap import skill_gap_bp
from routes.notifications import notifications_bp


def create_app():
    app = Flask(__name__)
    app.secret_key = config.SECRET_KEY
    app.config["MAX_CONTENT_LENGTH"] = config.MAX_UPLOAD_SIZE_MB * 1024 * 1024

    db.init_app(app)

    @app.context_processor
    def _notification_badge():
        """Unread count for the header bell on every authenticated page.

        Any failure degrades to zero so an unread-count problem can never block
        a page render. The count is only shown to a signed-in user.
        """
        if "user_id" not in session:
            return {"notification_unread_count": 0}
        try:
            connection = db.get_db()
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*) AS total FROM notifications "
                    "WHERE user_id = %s AND is_read = 0",
                    (session["user_id"],),
                )
                row = cursor.fetchone()
            return {"notification_unread_count": int((row or {}).get("total") or 0)}
        except Exception:
            connection = g.get("db")
            if connection is not None:
                connection.rollback()
            return {"notification_unread_count": 0}

    app.register_blueprint(auth_bp)
    app.register_blueprint(resume_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(home_bp)
    app.register_blueprint(job_bp)
    app.register_blueprint(opportunities_bp)
    app.register_blueprint(applications_bp)
    app.register_blueprint(interview_bp)
    app.register_blueprint(assistant_bp)
    app.register_blueprint(resume_builder_bp)
    app.register_blueprint(cover_letter_bp)
    app.register_blueprint(skill_gap_bp)
    app.register_blueprint(notifications_bp)

    @app.route("/")
    def landing():
        return render_template("landing.html")

    return app


app = create_app()

if __name__ == "__main__":
    db.init_db()
    app.run(debug=True)