from flask import Flask, render_template

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


def create_app():
    app = Flask(__name__)
    app.secret_key = config.SECRET_KEY
    app.config["MAX_CONTENT_LENGTH"] = config.MAX_UPLOAD_SIZE_MB * 1024 * 1024

    db.init_app(app)

    app.register_blueprint(auth_bp)
    app.register_blueprint(resume_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(home_bp)
    app.register_blueprint(job_bp)
    app.register_blueprint(opportunities_bp)
    app.register_blueprint(applications_bp)
    app.register_blueprint(interview_bp)
    app.register_blueprint(assistant_bp)

    @app.route("/")
    def landing():
        return render_template("landing.html")

    return app


app = create_app()

if __name__ == "__main__":
    db.init_db()
    app.run(debug=True)