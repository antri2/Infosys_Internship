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
#
# These credentials are OPTIONAL. When ADZUNA_APP_ID / ADZUNA_APP_KEY are
# absent or empty, the Adzuna live source is skipped and CareerAI uses its own
# canonical 185-job dataset (CSV -> MySQL -> FAISS) exactly as before. Nothing
# in the app breaks when Adzuna is unconfigured, unreachable, or slow.
ADZUNA_APP_ID = os.getenv("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY = os.getenv("ADZUNA_APP_KEY", "")

# Country/location is a setting, not a hardcoded value, so the integration can be
# pointed at another market later without touching the service. Adzuna uses its
# own ISO-ish codes; "in" is India.
ADZUNA_COUNTRY_CODE = os.getenv("ADZUNA_COUNTRY_CODE", "in")

# Set ADZUNA_ENABLED=false to keep the credentials but force the local pipeline.
ADZUNA_ENABLED = os.getenv("ADZUNA_ENABLED", "true").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}

# Keep failures short so a slow third party can never hold up a page render.
ADZUNA_TIMEOUT_SECONDS = float(os.getenv("ADZUNA_TIMEOUT_SECONDS", "5"))
ADZUNA_MAX_RESULTS = int(os.getenv("ADZUNA_MAX_RESULTS", "50"))

# Default search location and the query used when a signed-in user opens
# Opportunities without typing anything. Both are settings so neither "India"
# nor the fallback phrasing is baked into more than one module.
ADZUNA_DEFAULT_LOCATION = os.getenv("ADZUNA_DEFAULT_LOCATION", "India")
ADZUNA_DEFAULT_QUERY = os.getenv("ADZUNA_DEFAULT_QUERY", "entry level technology jobs")

# How long a fetched live job stays resolvable by its id, so Skill Gap / AI
# Summary / Interview work when clicked straight from the Opportunities list.
ADZUNA_JOB_CACHE_TTL_SECONDS = int(os.getenv("ADZUNA_JOB_CACHE_TTL_SECONDS", "900"))
ADZUNA_JOB_CACHE_MAX_ENTRIES = int(os.getenv("ADZUNA_JOB_CACHE_MAX_ENTRIES", "500"))