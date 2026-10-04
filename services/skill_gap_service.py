"""
M3.1 -- Skill Gap Analysis Agent. Compares a candidate against an explicitly
selected job, a user-provided job description, or advisory role-level context
and classifies gaps into 5 buckets (skill_gap_reports' columns): critical,
partial, preferred, experience, qualification -- each with a plain-English
reason, plus recommendations.

Same reliability pattern as resume_parser.py: try Groq first; if it's
unreachable/errors/returns bad JSON, fall back to a rule-based skills-only
comparison so the student gets *something*. The fallback only covers
skills (same set-difference services.job_matcher.compute_match already
does, kept consistent on purpose) -- judging "partially demonstrated" or
an experience/qualification shortfall needs real reasoning a rule can't
do, and it says so rather than faking it.
"""
import json as _json
import re

from services.llm_client import generate, extract_json_object
from services.context_builder import flatten_candidate_text
from services.job_matcher import compute_match
from services.skill_normalizer import skill_comparison_key
from services.role_catalog import canonical_role
from services.career_assistant_agent import extract_skill_mentions, role_skill_hints

GAP_KEYS = ("critical_gaps", "partial_gaps", "preferred_gaps", "experience_gaps", "qualification_gaps")

# Role-level guidance is advisory context, not a hidden job selection.  The
# Skill Gap agent receives the same shape for a role, a pasted JD, or an
# explicitly selected database job.
ROLE_REQUIREMENTS = {
    "ai engineer": {
        "required": ["Python", "statistics", "machine learning", "data structures", "SQL", "model training", "model evaluation"],
        "preferred": ["deep learning", "LLMs", "RAG", "model deployment", "APIs", "Docker", "cloud platforms"],
        "responsibilities": "Build, evaluate, and deploy machine-learning features that solve practical product problems.",
        "qualifications": "Strong programming, statistics, and data-processing fundamentals.",
    },
    "ml engineer": {
        "required": ["Python", "statistics", "machine learning", "model training", "model evaluation", "data pipelines"],
        "preferred": ["MLOps", "model deployment", "Docker", "cloud platforms", "experiment tracking"],
        "responsibilities": "Train, validate, deploy, and monitor machine-learning models.",
        "qualifications": "Strong mathematics, programming, and data preparation.",
    },
    "machine learning engineer": {
        "required": ["Python", "statistics", "machine learning", "model training", "model evaluation", "data pipelines"],
        "preferred": ["MLOps", "model deployment", "Docker", "cloud platforms", "experiment tracking"],
        "responsibilities": "Train, validate, deploy, and monitor machine-learning models.",
        "qualifications": "Strong mathematics, programming, and data preparation.",
    },
    "data scientist": {
        "required": ["Python", "SQL", "statistics", "data analysis", "data visualization", "experimentation"],
        "preferred": ["machine learning", "pandas", "Tableau", "communication", "data storytelling"],
        "responsibilities": "Analyze data, communicate findings, and support evidence-based decisions.",
        "qualifications": "Statistics, data handling, and clear communication.",
    },
    "data analyst": {
        "required": ["SQL", "statistics", "data analysis", "data visualization", "Python"],
        "preferred": ["business analysis", "communication", "Excel", "reporting", "data storytelling"],
        "responsibilities": "Turn reliable data into dashboards, reports, and actionable insights.",
        "qualifications": "Structured problem solving and communication.",
    },
    "genai engineer": {
        "required": ["Python", "LLMs", "prompting", "RAG", "evaluation", "APIs"],
        "preferred": ["model deployment", "vector databases", "Docker", "cloud platforms", "safety evaluation"],
        "responsibilities": "Build and evaluate reliable generative-AI applications and integrations.",
        "qualifications": "Programming, machine learning fundamentals, and API integration.",
    },
    "software engineer": {
        "required": ["programming", "algorithms", "data structures", "APIs", "databases", "testing", "version control"],
        "preferred": ["system design", "cloud platforms", "Docker", "CI/CD", "code review"],
        "responsibilities": "Design, build, test, and maintain reliable software features.",
        "qualifications": "Strong programming fundamentals and collaborative development habits.",
    },
    "full stack developer": {
        "required": ["HTML", "CSS", "JavaScript", "APIs", "databases", "testing", "version control"],
        "preferred": ["React", "cloud platforms", "CI/CD", "accessibility", "system design"],
        "responsibilities": "Build responsive front-end interfaces and reliable back-end services.",
        "qualifications": "Practical web development and debugging experience.",
    },
    "frontend developer": {
        "required": ["HTML", "CSS", "JavaScript", "responsive design", "testing"],
        "preferred": ["React", "accessibility", "performance", "build tools", "browser APIs"],
        "responsibilities": "Build accessible, responsive, and maintainable user interfaces.",
        "qualifications": "Strong JavaScript and web fundamentals.",
    },
    "backend developer": {
        "required": ["Python", "APIs", "databases", "testing", "version control", "system design"],
        "preferred": ["Docker", "cloud platforms", "authentication", "caching", "CI/CD"],
        "responsibilities": "Build secure, scalable services and data-backed application features.",
        "qualifications": "Strong programming and data modeling fundamentals.",
    },
    "devops engineer": {
        "required": ["Linux", "CI/CD", "Docker", "cloud platforms", "monitoring", "automation"],
        "preferred": ["Kubernetes", "Terraform", "security", "infrastructure as code", "incident response"],
        "responsibilities": "Build and operate reliable delivery, deployment, and monitoring systems.",
        "qualifications": "Strong automation and systems thinking.",
    },
    "product analyst": {
        "required": ["product thinking", "data analysis", "SQL", "user research", "experimentation"],
        "preferred": ["communication", "product management", "A/B testing", "dashboards"],
        "responsibilities": "Use data and user insight to improve product decisions.",
        "qualifications": "Analytical thinking and clear communication.",
    },
    "business analyst": {
        "required": ["requirements analysis", "SQL", "data analysis", "communication", "stakeholder management"],
        "preferred": ["process mapping", "reporting", "business intelligence", "documentation"],
        "responsibilities": "Translate business needs into clear requirements and measurable outcomes.",
        "qualifications": "Structured analysis and stakeholder communication.",
    },
    "digital marketing analyst": {
        "required": ["data analysis", "SEO", "content strategy", "campaign measurement", "communication"],
        "preferred": ["marketing automation", "Google Analytics", "social media", "A/B testing"],
        "responsibilities": "Measure campaigns and improve marketing decisions with data.",
        "qualifications": "Analytical, communication, and digital marketing fundamentals.",
    },
}


JD_SKILL_TERMS = {
    "python", "java", "javascript", "typescript", "sql", "nosql", "r", "c++", "c#",
    "django", "flask", "fastapi", "node.js", "react", "angular", "vue", "graphql",
    "rest", "restful", "api", "apis", "microservices", "system design", "algorithms",
    "data structures", "databases", "mysql", "postgresql", "mongodb", "redis",
    "machine learning", "deep learning", "statistics", "data analysis", "data visualization",
    "data preprocessing", "data pipelines", "feature engineering", "model training",
    "model evaluation", "model deployment", "mlops", "nlp", "computer vision",
    "llm", "llms", "rag", "prompting", "embeddings", "vector search", "vector database",
    "langchain", "transformers", "hugging face", "pytorch", "tensorflow", "keras",
    "faiss", "pinecone", "weaviate", "chroma", "openai", "numpy", "pandas", "scikit-learn",
    "opencv", "spacy", "nltk", "tableau", "power bi", "excel", "looker", "snowflake",
    "docker", "kubernetes", "aws", "azure", "gcp", "cloud platforms", "linux", "git",
    "github", "ci/cd", "terraform", "monitoring", "pytest", "unit testing", "testing",
    "version control", "code review", "communication", "teamwork", "leadership",
    "problem solving", "product management", "user research", "experimentation",
    "streamlit", "gradio", "web development", "mobile development",
}


def _jd_skill_mentions(text: str) -> list[str]:
    lowered = str(text or "").casefold()
    found = []
    for term in sorted(JD_SKILL_TERMS, key=len, reverse=True):
        if re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", lowered):
            found.append(term)
    return _unique_skills(found)


def _role_key(value: str) -> str:
    return canonical_role(value or "").casefold()


def _role_requirements(target_role: str) -> dict:
    key = _role_key(target_role)
    if key in ROLE_REQUIREMENTS:
        return ROLE_REQUIREMENTS[key]
    hints = role_skill_hints(target_role)
    return {
        "required": hints[:4] or ["problem solving", "technical fundamentals", "communication"],
        "preferred": hints[4:] or ["portfolio project", "collaboration", "continuous learning"],
        "responsibilities": f"Practical work relevant to a {target_role or 'chosen'} role.",
        "qualifications": "Relevant foundational knowledge and demonstrated evidence.",
    }


def _unique_skills(values) -> list[str]:
    result = []
    seen = set()
    for value in values or []:
        if not isinstance(value, str):
            continue
        cleaned = re.sub(r"^[\s\-\*\u2022]+\d*[.)]?\s*", "", value).strip(" .,;:-()")
        if not cleaned or len(cleaned) > 80 or not re.search(r"[A-Za-z]", cleaned):
            continue
        if len(cleaned.split()) > 2 and re.search(
            r"\b(?:build|develop|create|work|experience|knowledge|familiar|understanding|ability|role|years|strong)\b",
            cleaned,
            re.IGNORECASE,
        ):
            continue
        key = skill_comparison_key(cleaned)
        if key and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


def _jd_sections(text: str) -> dict[str, str]:
    source = str(text or "")
    marker = re.compile(
        r"("
        r"preferred\s+skills?|preferred|nice\s+to\s+have|good\s+to\s+have|bonus|"
        r"required\s+skills?|required|must\s+have|skills?\s+required|skills|"
        r"job\s+requirements?|requirements?|technical\s+skills?|"
        r"responsibilities|what\s+you\s+will\s+do|duties|"
        r"qualifications?|education|experience"
        r")\s*:",
        re.IGNORECASE,
    )
    matches = list(marker.finditer(source))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        label = re.sub(r"\s+", " ", match.group(1).strip().casefold())
        if label in {"preferred skills", "preferred", "nice to have", "good to have", "bonus"}:
            key = "preferred"
        elif label in {
            "required", "must have", "skills required", "required skills",
            "job requirements", "requirements", "technical skills", "skills",
        }:
            key = "required"
        elif label in {"responsibilities", "what you will do", "duties"}:
            key = "responsibilities"
        else:
            key = "qualifications"
        end = matches[index + 1].start() if index + 1 < len(matches) else len(source)
        value = source[match.end():end].strip(" \n\t.;")
        if value:
            sections[key] = value
    return sections


def build_role_context(target_role: str, company: str = "") -> dict:
    """Create role-level analysis context without selecting a database job."""
    role = str(target_role or "chosen role").strip()
    requirements = _role_requirements(role)
    return {
        "title": role,
        "company": str(company or "").strip(),
        "required_skills": ", ".join(requirements["required"]),
        "preferred_skills": ", ".join(requirements["preferred"]),
        "qualifications": requirements["qualifications"],
        "experience_required": "",
        "education_required": "",
        "responsibilities": requirements["responsibilities"],
        "description": f"Advisory role-level requirements for {role}; these are not exact job requirements.",
        "_analysis_mode": "role",
        "_analysis_label": f"Role-level advisory requirements for {role} (not an exact job description)",
    }


def build_jd_context(target_role: str, company: str, pasted_jd: str) -> dict:
    """Extract normalized requirements from the user-provided JD."""
    sections = _jd_sections(pasted_jd)
    mentioned = _unique_skills(extract_skill_mentions(pasted_jd) + _jd_skill_mentions(pasted_jd))
    required = _unique_skills(_split_jd_skills(sections.get("required", "")) + mentioned)
    preferred = _unique_skills(_split_jd_skills(sections.get("preferred", "")))
    preferred_keys = {skill_comparison_key(skill) for skill in preferred}
    if preferred_keys:
        required = [skill for skill in required if skill_comparison_key(skill) not in preferred_keys]
    if not required:
        required = _unique_skills(mentioned) or ["communication", "problem solving", "technical fundamentals"]
    title = str(target_role or "Provided job description").strip() or "Provided job description"
    return {
        "title": title,
        "company": str(company or "provided job description").strip(),
        "required_skills": ", ".join(required),
        "preferred_skills": ", ".join(preferred),
        "qualifications": sections.get("qualifications", ""),
        "experience_required": "",
        "education_required": "",
        "responsibilities": sections.get("responsibilities", "") or str(pasted_jd or ""),
        "description": str(pasted_jd or "").strip(),
        "_analysis_mode": "jd",
        "_analysis_label": f"Provided job description for {title}",
    }


def _split_jd_skills(text: str) -> list[str]:
    return _unique_skills(re.split(r"[,;|\n\u2022]+|\.\s+", str(text or "")))

PROMPT_TEMPLATE = """You are a career-advising assistant. Compare this candidate against \
this job and identify skill/experience/qualification gaps.

Return ONLY valid JSON (no other text, no markdown fences) matching exactly this shape:

{{
  "critical_gaps": [{{"skill": "...", "why_it_matters": "..."}}],
  "partial_gaps": [{{"skill": "...", "why_it_matters": "...", "note": "why this only counts as partial"}}],
  "preferred_gaps": [{{"skill": "...", "why_it_matters": "..."}}],
  "experience_gaps": [{{"gap": "...", "why_it_matters": "..."}}],
  "qualification_gaps": [{{"gap": "...", "why_it_matters": "..."}}],
  "recommendations": [{{"action": "...", "addresses": "which gap this helps close"}}]
}}

Rules:
- "critical_gaps": required skills the candidate does not have at all.
- "partial_gaps": required skills the candidate has some evidence of (e.g. used in a project but
  not listed as a core skill) but hasn't clearly demonstrated.
- "preferred_gaps": preferred/bonus skills the candidate is missing.
- "experience_gaps"/"qualification_gaps": real mismatches only -- do not invent one that isn't true.
- "recommendations": give a practical priority order, a learning sequence, and concrete practice or project ideas that close the gaps.
- Every entry needs a specific "why_it_matters" tied to this exact role or supplied job description, not a generic sentence.

Candidate:
{candidate_text}

Analysis context: {context_label}
- Company context: {job_company}
- Required skills: {job_required_skills}
- Preferred skills: {job_preferred_skills}
- Qualifications: {job_qualifications}
- Experience required: {job_experience_required}
- Education required: {job_education_required}
- Responsibilities: {job_responsibilities}
- Source description: {job_description}

Rules for this context:
- If this is role-level advisory context, compare against the role's important skill areas and do not present them as exact requirements from a specific job.
- If this is a provided job description, use the supplied description as the primary requirement source.
- If this is an explicitly selected job, use that exact job's stored requirements.
"""


def _build_prompt(candidate: dict, job: dict) -> str:
    title = str(job.get("title") or "the selected role")
    company = str(job.get("company") or "").strip()
    default_label = f"{title} at {company}" if company else title
    return PROMPT_TEMPLATE.format(
        candidate_text=flatten_candidate_text(candidate),
        context_label=job.get("_analysis_label") or default_label,
        job_title=title,
        job_company=company,
        job_required_skills=job.get("required_skills") or "None listed",
        job_preferred_skills=job.get("preferred_skills") or "None listed",
        job_qualifications=job.get("qualifications") or "None listed",
        job_experience_required=job.get("experience_required") or "None listed",
        job_education_required=job.get("education_required") or "None listed",
        job_responsibilities=job.get("responsibilities") or "None listed",
        job_description=job.get("description") or "None supplied",
    )


def _normalize_shape(data: dict) -> dict:
    for key in GAP_KEYS:
        if not isinstance(data.get(key), list):
            data[key] = []
    if not isinstance(data.get("recommendations"), list):
        data["recommendations"] = []
    return data


def _split_skills(csv_text: str) -> list[str]:
    return [s.strip() for s in (csv_text or "").split(",") if s.strip()]


def _reconcile_gap_entries(
    entries: list,
    allowed_skills: list[str],
    key: str,
    reason_key: str,
    default_reason: str,
) -> list[dict]:
    """Keep only LLM gap entries that are verified missing job skills."""
    allowed_by_key = {skill_comparison_key(skill): skill for skill in allowed_skills}
    reconciled = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        value = entry.get(key)
        canonical = allowed_by_key.get(skill_comparison_key(value))
        if not canonical:
            continue
        result = dict(entry)
        result[key] = canonical
        result[reason_key] = entry.get(reason_key) or default_reason
        reconciled.append(result)
    return reconciled


def _filter_partial_entries(entries: list, candidate: dict, job: dict) -> list[dict]:
    """Keep partial claims grounded in a profile/job skill vocabulary."""
    vocabulary = set()
    for skill in candidate.get("skills", []):
        vocabulary.add(skill_comparison_key(skill))
    for field in ("required_skills", "preferred_skills"):
        for skill in _split_skills(job.get(field)):
            vocabulary.add(skill_comparison_key(skill))

    filtered = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        if skill_comparison_key(entry.get("skill")) in vocabulary:
            filtered.append(dict(entry))
    return filtered


def add_verified_skill_sections(report: dict, candidate: dict, job: dict) -> dict:
    """Add deterministic M2 skill sections and reconcile LLM skill gaps."""
    match_info = compute_match(candidate.get("skills", []), job)
    role_title = job.get("title", "this role")

    report["matched_skills"] = match_info["matched_skills"]
    report["matched_preferred"] = match_info["matched_preferred"]
    report["missing_required_skills"] = match_info["missing_skills"]
    report["missing_preferred_skills"] = match_info["missing_preferred"]
    report["critical_gaps"] = _reconcile_gap_entries(
        report.get("critical_gaps", []),
        match_info["missing_skills"],
        "skill",
        "why_it_matters",
        f"Listed as a required skill for {role_title}.",
    )
    report["preferred_gaps"] = _reconcile_gap_entries(
        report.get("preferred_gaps", []),
        match_info["missing_preferred"],
        "skill",
        "why_it_matters",
        f"Listed as a preferred skill for {role_title}.",
    )
    report["partial_gaps"] = _filter_partial_entries(report.get("partial_gaps", []), candidate, job)
    report["partial_matches"] = report["partial_gaps"]
    report["matched_skill_count"] = len(match_info["matched_skills"])
    report["required_skill_count"] = match_info["required_total"]
    report["preferred_skill_count"] = match_info["preferred_total"]
    return report


def _fallback_report(candidate: dict, job: dict) -> dict:
    match_info = compute_match(candidate.get("skills", []), job)
    role_title = job.get("title", "this role")
    critical = [
        {
            "skill": skill,
            "why_it_matters": f"Listed as a required skill for {role_title}.",
        }
        for skill in match_info["missing_skills"]
    ]
    preferred_gaps = [
        {
            "skill": skill,
            "why_it_matters": f"Listed as a preferred skill for {role_title}.",
        }
        for skill in match_info["missing_preferred"]
    ]
    report = {
        "critical_gaps": critical,
        "partial_gaps": [],
        "preferred_gaps": preferred_gaps,
        "experience_gaps": [],
        "qualification_gaps": [],
        "recommendations": [
            {
                "action": f"Consider learning or gaining experience with {gap['skill']} before adding it to your profile.",
                "addresses": gap["skill"],
            }
            for gap in critical[:5]
        ],
        "used_fallback": True,
        "fallback_note": (
            "Groq wasn't reachable, so only a plain skills comparison ran. "
            "Experience and qualification gaps need the AI model -- try again shortly for a fuller report."
        ),
    }
    report = add_verified_skill_sections(report, candidate, job)
    report["analysis_mode"] = job.get("_analysis_mode", "job")
    return report


def generate_skill_gap_report(candidate: dict, job: dict) -> dict:
    try:
        raw = generate(_build_prompt(candidate, job))
        report = _normalize_shape(extract_json_object(raw))
        report["used_fallback"] = False
        report = add_verified_skill_sections(report, candidate, job)
        report["analysis_mode"] = job.get("_analysis_mode", "job")
        return report
    except Exception as e:
        print(f"[skill_gap_service] Groq unavailable, using fallback. Reason: {e}")
        return _fallback_report(candidate, job)


def save_skill_gap_report(db, user_id: int, job_id: int, report: dict) -> None:
    with db.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO skill_gap_reports
                (user_id, job_id, critical_gaps, partial_gaps, preferred_gaps,
                 experience_gaps, qualification_gaps, recommendations)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                critical_gaps = VALUES(critical_gaps), partial_gaps = VALUES(partial_gaps),
                preferred_gaps = VALUES(preferred_gaps), experience_gaps = VALUES(experience_gaps),
                qualification_gaps = VALUES(qualification_gaps), recommendations = VALUES(recommendations)
            """,
            (
                user_id, job_id,
                _json.dumps(report.get("critical_gaps", [])), _json.dumps(report.get("partial_gaps", [])),
                _json.dumps(report.get("preferred_gaps", [])), _json.dumps(report.get("experience_gaps", [])),
                _json.dumps(report.get("qualification_gaps", [])), _json.dumps(report.get("recommendations", [])),
            ),
        )
        db.commit()


def load_cached_report(db, user_id: int, job_id: int) -> dict | None:
    with db.cursor() as cursor:
        cursor.execute("SELECT * FROM skill_gap_reports WHERE user_id = %s AND job_id = %s", (user_id, job_id))
        row = cursor.fetchone()
    if not row:
        return None
    for key in GAP_KEYS + ("recommendations",):
        if isinstance(row.get(key), str):
            row[key] = _json.loads(row[key])
    return row