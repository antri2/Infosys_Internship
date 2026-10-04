import os
from dotenv import load_dotenv

load_dotenv()

MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "career_ai")

SECRET_KEY = os.getenv("SECRET_KEY", "dev_only_change_this_in_production")

UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
ALLOWED_RESUME_TYPES = {"pdf", "docx"}
MAX_UPLOAD_SIZE_MB = 5

# Profile photos need to be publicly viewable (shown on the profile page),
# unlike resume files -- so they live under static/, where Flask can serve
# them directly via url_for('static', filename='uploads/photos/<name>').
PHOTO_UPLOAD_FOLDER = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "static", "uploads", "photos"
)
ALLOWED_PHOTO_TYPES = {"png", "jpg", "jpeg"}

# LLM via Groq's hosted API -- free tier, no local download, no torch/transformers
# needed. Get a free key at console.groq.com. Check console.groq.com/docs/models
# for the current model ID (Groq's lineup changes -- confirm before demo day).
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL_NAME = os.getenv("GROQ_MODEL_NAME", "openai/gpt-oss-20b")

# Adzuna job-listings API -- free tier, get credentials at developer.adzuna.com
ADZUNA_APP_ID = os.getenv("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY = os.getenv("ADZUNA_APP_KEY", "")