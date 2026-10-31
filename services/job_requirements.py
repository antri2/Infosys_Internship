"""Deterministic requirement extraction for live job text.

Live Adzuna listings give us a title plus a description that the API truncates
to 500 characters. There is no structured ``required_skills`` field, so this
module recovers what can be recovered *from the real text* and nothing else.

Design rules, in priority order:

1. **Never invent.** A skill is only ever reported when its literal text
   appears in the job's own title or description. No LLM is involved, no
   related-technology guessing, no "SQL role implies MySQL".
2. **Reuse the existing normalizer.** Display names and duplicate detection go
   through ``services.skill_normalizer``, so a live job and a local job
   compare identically inside ``job_matcher.compute_match``.
3. **Honest classification.** Skills are split into required/preferred only
   when the text actually contains a required/preferred section cue. When it
   does not, the skills are reported as the job's requirements rather than
   pretending the posting distinguished them.
4. **No matches means no match.** When a posting genuinely states no
   requirements, the fields stay empty and the UI shows "Not specified".
   That is the correct answer, and better than a fabricated number.
"""

import re

from services.skill_normalizer import normalize_skill, skill_comparison_key


# --------------------------------------------------------------------------
# Skill vocabulary.
#
# Each entry is (canonical display name, regex). Matching is case-insensitive
# and word-bounded, except for entries wrapped in (?-i:...) which are matched
# case-sensitively so short/ambiguous tokens cannot fire inside ordinary words
# ("AI" must not match "said", "SAP" must not match "sappy").
#
# Order is irrelevant here -- the matcher prefers the longest pattern at any
# given position -- but longer, more specific phrases are listed first anyway
# so the vocabulary reads sensibly.
# --------------------------------------------------------------------------
SKILL_VOCABULARY: tuple[tuple[str, str], ...] = (
    # --- data / analytics ---
    ("Power BI", r"power\s?bi"),
    ("Tableau", r"tableau"),
    ("Excel", r"\bexcel\b"),
    ("Pandas", r"pandas"),
    ("NumPy", r"numpy"),
    ("Matplotlib", r"matplotlib"),
    ("Seaborn", r"seaborn"),
    ("Data Analysis", r"data\s+(?:analysis|analyst|analytics)"),
    ("Data Visualization", r"data\s+visuali[sz]ation|data\s?viz"),
    ("Statistics", r"\bstatistics\b|\bstatistical\s+(?:analysis|modeling|modelling|inference|methods?|techniques?|tests?)\b"),
    ("Statistical Modeling", r"statistical\s+model(?:ing|ling)|regression\s+model(?:ing|ling)"),
    ("Data Modeling", r"data\s+model(?:ing|ling)"),
    ("Data Engineering", r"data\s+engineer(?:ing)?"),
    ("Data Cleaning", r"data\s+clean(?:ing|up)"),
    ("ETL", r"\betl\b"),
    ("Data Pipelines", r"\b(?:data|etl|build|streaming)\s+pipelines?\b"),
    ("Spark", r"\bspark\b"),
    ("Hadoop", r"hadoop"),
    ("Hive", r"\bhive\b"),
    ("Airflow", r"airflow"),
    ("Data Warehousing", r"data\s+warehous(?:e|ing)"),
    ("Big Data", r"big\s+data"),
    ("Snowflake", r"snowflake"),
    ("Redshift", r"redshift"),
    ("Kafka", r"\bkafka\b"),
    ("dbt", r"\bdbt\b"),

    # --- ML / AI ---
    ("Machine Learning", r"machine\s+learning"),
    ("Deep Learning", r"deep\s+learning"),
    ("Artificial Intelligence", r"artificial\s+intelligence"),
    ("AI", r"(?-i:\bAI\b)"),
    ("Computer Vision", r"computer\s+vision"),
    ("Natural Language Processing", r"natural\s+language\s+processing|\bNLP\b"),
    ("NLP", r"(?-i:\bNLP\b)"),
    ("Generative AI", r"generative\s+ai|(?-i:\bGenAI\b)"),
    ("LLM", r"(?-i:\bLLMs?\b)|large\s+language\s+models?"),
    ("RAG", r"(?-i:\bRAG\b)|retrieval[- ]augmented\s+generation"),
    ("LangChain", r"langchain"),
    ("Vector Database", r"vector\s+(?:database|store|search)"),
    ("FAISS", r"faiss"),
    ("TensorFlow", r"tensor\s?flow"),
    ("Keras", r"\bkeras\b"),
    ("PyTorch", r"pytorch"),
    ("Scikit-learn", r"scikit[- ]learn|\bsklearn\b"),
    ("XGBoost", r"xgboost"),
    ("Regression", r"\bregression\b"),
    ("Classification", r"classification"),
    ("Time Series", r"time[- ]series"),
    ("Forecasting", r"forecast(?:ing)?"),
    ("A/B Testing", r"a/?b\s+test(?:ing)?"),
    ("MLOps", r"(?-i:\bMLOps\b)"),

    # --- programming languages ---
    ("Python", r"python"),
    ("SQL", r"(?-i:\bSQL\b)"),
    ("Java", r"\bjava\b"),
    ("JavaScript", r"\bjavascript\b"),
    ("TypeScript", r"typescript"),
    ("C++", r"(?-i:\bc\+\+)"),
    ("C#", r"(?-i:\bc#)"),
    ("Scala", r"scala"),
    ("R", r"(?-i:\bR\b)\s+(?:programming|language|scripting)|\brscript\b"),
    ("MATLAB", r"matlab"),

    # --- web / frameworks ---
    ("HTML", r"(?-i:\bHTML5?\b)"),
    ("CSS", r"(?-i:\bCSS3?\b)"),
    ("React", r"react(?:\.js|\s?js)?"),
    ("Angular", r"angular"),
    ("Vue", r"vue(?:\.js)?"),
    ("Node.js", r"node(?:\.js)?"),
    ("Next.js", r"next\.js"),
    ("Flask", r"flask"),
    ("Django", r"django"),
    ("FastAPI", r"fastapi"),
    ("Spring Boot", r"spring\s*boot"),
    ("REST API", r"rest\s*api|restful"),
    ("GraphQL", r"graphql"),
    ("Microservices", r"micro[- ]?services?"),

    # --- databases ---
    ("MySQL", r"mysql"),
    ("PostgreSQL", r"postgre ?sql|postgres"),
    ("MongoDB", r"mongo ?db"),
    ("Oracle", r"oracle\s+(?:db|database)"),
    ("SQL Server", r"sql\s+server|mssql"),
    ("Redis", r"redis"),
    ("DynamoDB", r"dynamodb"),

    # --- cloud / devops ---
    ("AWS", r"(?-i:\bAWS\b)|amazon\s+web\s+services"),
    ("Azure", r"(?-i:\bAzure\b)"),
    ("GCP", r"(?-i:\bGCP\b)|google\s+cloud"),
    ("Docker", r"docker"),
    ("Kubernetes", r"kubernetes|(?-i:\bk8s\b)"),
    ("Terraform", r"terraform"),
    ("Jenkins", r"jenkins"),
    ("CI/CD", r"ci\s*/\s*cd|ci/cd|continuous\s+(?:integration|deployment)"),
    ("Linux", r"\blinux\b|\bunix\b"),
    ("Git", r"(?-i:\bgit\b)"),
    ("GitHub", r"github"),
    ("DevOps", r"dev ?ops"),
    ("Ansible", r"ansible"),
    ("Microservices Architecture", r"micro[- ]?services?"),

    # --- business / analytics ---
    # No bare "BI" token here: it would fire on "Power BI" and claim Business
    # Intelligence for a posting that never mentions it.
    ("Business Intelligence", r"business\s+intelligence"),
    ("Reporting", r"report(?:ing|s)?"),
    ("Stakeholder Management", r"stakeholder\s+(?:management|engagement)"),
    ("Project Management", r"project\s+management|(?-i:\bPMP\b)"),
    ("Agile", r"agile"),
    ("Scrum", r"scrum"),
    ("Six Sigma", r"six\s+sigma"),
    ("Financial Modelling", r"financial\s+model(?:ing|ling)"),
    ("Risk Analysis", r"risk\s+(?:analysis|assessment)"),
    ("Salesforce", r"salesforce"),
    ("SAP", r"(?-i:\bSAP\b)"),
)


# Cues that mark a stretch of text as stating requirements.
REQUIRED_CUES = (
    "requirements",
    "required",
    "must have",
    "must-have",
    "must have",
    "mandatory",
    "essential",
    "qualifications",
    "what you will need",
    "you will need",
    "we are looking for",
    "who we are looking for",
    "looking for someone",
    "minimum",
    "skills required",
    "who you are",
    "candidate profile",
)

# Cues that mark a stretch of text as stating preferences.
PREFERRED_CUES = (
    "preferred",
    "nice to have",
    "nice-to-have",
    "good to have",
    "good-to-have",
    "bonus",
    "desired",
    "ideally",
    "a plus",
    "favourable",
    "favorable",
)

# Split inline bullet runs such as "duties: -Write code -Design things".
_BULLET_SPLIT = re.compile(r"\s[-–—•·]\s|(?:^|\s)\d+[.)]\s")

_REQUIRED_COMPILED = [(name, re.compile(pat, re.I)) for name, pat in SKILL_VOCABULARY]
_REQUIRED_CUE_RE = re.compile("|".join(re.escape(c) for c in REQUIRED_CUES), re.I)
_PREFERRED_CUE_RE = re.compile("|".join(re.escape(c) for c in PREFERRED_CUES), re.I)

# "5.1-7 years", "3+ years", "2 years", "0-1 years", "1 to 3 years"
_RANGE_YEARS = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:-|–|—|to)\s*(\d+(?:\.\d+)?)\s*(?:\+)?\s*(?:years?|yrs?)",
    re.I,
)
_PLUS_YEARS = re.compile(r"(\d+(?:\.\d+)?)\s*\+\s*(?:years?|yrs?)", re.I)
_PLAIN_YEARS = re.compile(r"(\d+(?:\.\d+)?)\s*(?:years?|yrs?)\b", re.I)
_FRESHER = re.compile(
    r"\b(?:freshers?|entry[- ]level|graduate\s+trainee|0\s*[-–]?\s*\d?\s*years?|no\s+experience)\b",
    re.I,
)

# Degree patterns.
#
# Short abbreviations are the trap here: a naive r"\bb\.?\s?e\b" matches the
# English word "be" (and r"\bm\.?\s?e\b" matches "me"), which would invent a
# B.E./M.E. requirement out of ordinary prose. Anything that can collide with
# a real word therefore requires either a literal dot or an uppercase-only
# match, both written with an inline case-sensitivity flag.
_DEGREE_PATTERNS = (
    (re.compile(r"\bbachelor(?:'s)?\s+degree\s+in\s+([a-z&\s]{3,40})", re.I), "Bachelor's degree in {0}"),
    (re.compile(r"\bmaster(?:'s)?\s+degree\s+in\s+([a-z&\s]{3,40})", re.I), "Master's degree in {0}"),
    (re.compile(r"\bbachelor(?:'s)?\s+degree\b", re.I), "Bachelor's degree"),
    (re.compile(r"\bmaster(?:'s)?\s+degree\b", re.I), "Master's degree"),
    (re.compile(r"\bph\.?\s?d\b", re.I), "PhD"),
    (re.compile(r"\bdegree\s+in\s+computer\s+science\b|\bcomputer\s+science\s+degree\b", re.I), "Bachelor's degree in Computer Science"),
    (re.compile(r"\bm\.?\s?tech\b", re.I), "M.Tech"),
    (re.compile(r"\bmca\b", re.I), "Master's degree"),
    (re.compile(r"\bm\.?\s?sc\b", re.I), "Master's degree"),
    (re.compile(r"\bm\.e\.?\b", re.I), "Master's degree"),
    (re.compile(r"(?-i:\bME\b)"), "Master's degree"),
    (re.compile(r"\bmba\b", re.I), "MBA"),
    (re.compile(r"\bb\.?\s?tech\b", re.I), "B.Tech"),
    (re.compile(r"\bb\.e\.?\b", re.I), "B.E."),
    (re.compile(r"(?-i:\bBE\b)"), "B.E."),
    (re.compile(r"\bb\.?\s?sc\b", re.I), "B.Sc"),
    (re.compile(r"\bb\.?\s?com\b", re.I), "B.Com"),
    (re.compile(r"\bbca\b", re.I), "Bachelors degree"),
    (re.compile(r"\bbba\b", re.I), "Bachelors degree"),
    (re.compile(r"\bdiploma\b", re.I), "Diploma"),
    (re.compile(r"\b10\s*\+\s*2\b|\b12th\b|\bintermediate\s+board\b", re.I), "12th / Higher Secondary"),
)


def _clean(value: str | None) -> str:
    return " ".join((value or "").split())


def _dedupe(skills: list[str]) -> list[str]:
    """Canonicalize through the shared normalizer and drop duplicates."""
    out: list[str] = []
    seen: set[str] = set()
    for skill in skills:
        display = normalize_skill(skill)
        key = skill_comparison_key(display)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(display)
    return out


def find_skills(text: str) -> list[str]:
    """Every vocabulary skill literally present in ``text``."""
    if not text:
        return []
    found: list[str] = []
    for name, pattern in _REQUIRED_COMPILED:
        if pattern.search(text):
            found.append(name)
    return _dedupe(found)


def _segments(text: str) -> list[str]:
    """Split a description into candidate requirement lines."""
    if not text:
        return []
    parts: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        for piece in _BULLET_SPLIT.split(line):
            piece = piece.strip(" -–—•·\t")
            if piece:
                parts.append(piece)
    return parts or ([text.strip()] if text.strip() else [])


def classify_segments(text: str) -> tuple[list[str], list[str], bool]:
    """Split description text into (required_text, preferred_text, saw_cues).

    Sectioning is done by *cue position* rather than by line, because Adzuna
    returns descriptions as one long single line with inline markers
    ("Requirements: Python and SQL. Preferred: Tableau."). Splitting on
    newlines or bullets silently dropped the entire posting in that case.
    """
    if not text or not text.strip():
        return [], [], False

    markers: list[tuple[int, str]] = []
    for match in _REQUIRED_CUE_RE.finditer(text):
        markers.append((match.start(), "required"))
    for match in _PREFERRED_CUE_RE.finditer(text):
        markers.append((match.start(), "preferred"))
    markers.sort()

    if not markers:
        return [text], [], False

    required: list[str] = []
    preferred: list[str] = []

    # Anything before the first cue is context; treat it as requirements.
    head = text[: markers[0][0]]
    if head.strip():
        required.append(head)

    for index, (position, kind) in enumerate(markers):
        end = markers[index + 1][0] if index + 1 < len(markers) else len(text)
        segment = text[position:end]
        (required if kind == "required" else preferred).append(segment)

    return required, preferred, True


def extract_experience(*texts: str) -> str:
    """First explicit experience statement found, or "" when none exists."""
    for text in texts:
        if not text:
            continue
        match = _RANGE_YEARS.search(text)
        if match:
            return f"{match.group(1)}-{match.group(2)} years"
        match = _PLUS_YEARS.search(text)
        if match:
            return f"{match.group(1)}+ years"
        match = _PLAIN_YEARS.search(text)
        if match:
            return f"{match.group(1)} years"
        if _FRESHER.search(text):
            return "Fresher"
    return ""


def extract_education(*texts: str) -> str:
    """First explicit education requirement found, or "" when none exists."""
    for text in texts:
        if not text:
            continue
        for pattern, template in _DEGREE_PATTERNS:
            match = pattern.search(text)
            if not match:
                continue
            if "{0}" in template and match.groups():
                subject = _clean(match.group(1)).strip(" .,")
                subject = re.sub(r"\s+", " ", subject).title()
                return template.format(subject)
            return template
    return ""


def infer_job_type(raw: dict, title: str = "") -> str:
    """Derive a human job type from Adzuna's own fields, else the title."""
    def _pretty(value) -> str:
        text = _clean(value).replace("_", " ").replace("-", " ")
        return " ".join(word.capitalize() for word in text.split()) if text else ""

    contract_time = _pretty(raw.get("contract_time"))
    contract_type = _pretty(raw.get("contract_type"))

    parts = [part for part in (contract_time, contract_type) if part]
    if parts:
        # Avoid "Full Time Permanent Contract"-style piles.
        return " / ".join(dict.fromkeys(parts))[:60]

    lowered = (title or "").lower()
    if "intern" in lowered:
        return "Internship"
    if "trainee" in lowered or "apprentice" in lowered:
        return "Trainee"
    if "freelance" in lowered:
        return "Freelance"
    return ""


def extract_requirements(title: str, description: str, raw: dict | None = None) -> dict:
    """Build the requirement fields CareerAI needs from one live listing.

    Returns ``required_skills`` / ``preferred_skills`` as comma-separated
    strings (the same shape ``compute_match`` already reads via
    ``split_skill_text``), plus ``experience_required`` and
    ``education_required``.
    """
    raw = raw or {}
    title = _clean(title)
    description = description or ""

    required_parts, preferred_parts, saw_cues = classify_segments(description)

    # A skill in the job title is central to the role, so it is a requirement.
    title_skills = find_skills(title)
    required_skills = list(title_skills)
    required_skills += find_skills(" \n ".join(required_parts))
    preferred_skills = find_skills(" \n ".join(preferred_parts))

    required_skills = _dedupe(required_skills)

    if not saw_cues and not required_skills and preferred_skills:
        # No sections at all: the posting does not distinguish them, so do not
        # pretend it does -- report the skills as the role's requirements.
        required_skills = _dedupe(preferred_skills)
        preferred_skills = []

    preferred_skills = [s for s in _dedupe(preferred_skills) if s not in required_skills]

    # If everything ended up "preferred", Skill Gap would report no missing
    # skills at all. Promote to required so the extracted skills are usable.
    if not required_skills and preferred_skills:
        required_skills = _dedupe(preferred_skills)
        preferred_skills = []

    return {
        "required_skills": ", ".join(required_skills),
        "preferred_skills": ", ".join(preferred_skills),
        "experience_required": extract_experience(
            " \n ".join(required_parts), title, description
        ),
        "education_required": extract_education(
            " \n ".join(required_parts), title, description
        ),
        "job_type": infer_job_type(raw, title),
    }