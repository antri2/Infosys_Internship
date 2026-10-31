"""Adzuna live job source -- transport and normalization only.

This module is deliberately the *only* place that talks to Adzuna. It contains
no CareerAI business logic: it performs one HTTPS GET, normalizes the response
into the same job shape the rest of the app already consumes, and hands the
result back.

Two rules govern everything here:

1. **Never raise.** Every failure mode -- missing credentials, disabled flag,
   DNS/TLS error, timeout, HTTP error, non-JSON body, wrong JSON shape, an
   empty result set, or individual malformed entries -- returns an empty list
   so the caller falls back to the canonical local dataset. A flaky third party
   must never surface as an application error.

2. **Never leak the key.** The App ID / App Key go out as query parameters, and
   httpx embeds the full request URL in some exception messages. Nothing here
   logs a URL, a parameter dict, or ``str(exception)``; only exception *type
   names* and HTTP status codes are ever recorded.

Country and location are settings (``config.ADZUNA_COUNTRY_CODE`` and the
``location`` argument), never hardcoded, so another market is a config change.
"""

import logging
import zlib

import config

from services.job_dates import application_deadline, published_date
from services.job_requirements import extract_requirements


logger = logging.getLogger(__name__)

ADZUNA_BASE_URL = "https://api.adzuna.com/v1/api/jobs"

# Live jobs are not rows in the local `jobs` table, so they need synthetic,
# stable integer ids that can never collide with the canonical dataset (whose
# ids are small) and never overflow MySQL's signed INT.
_ADZUNA_JOB_ID_OFFSET = 1_000_000_000
_ADZUNA_JOB_ID_SPAN = 1_000_000_000


def is_configured() -> bool:
    """True only when the live source is enabled and both credentials exist."""
    return bool(
        config.ADZUNA_ENABLED
        and (config.ADZUNA_APP_ID or "").strip()
        and (config.ADZUNA_APP_KEY or "").strip()
    )


def is_adzuna_job_id(job_id) -> bool:
    """True when an id falls inside the reserved live range.

    This is the single definition of "is this a live id", shared with the
    application-tracking path so the reserved range stays enforced in one place.
    """
    try:
        value = int(job_id)
    except (TypeError, ValueError):
        return False
    return _ADZUNA_JOB_ID_OFFSET <= value < _ADZUNA_JOB_ID_OFFSET + _ADZUNA_JOB_ID_SPAN


def _safe_job_id(raw_id) -> int:
    """Map an Adzuna id onto a stable, collision-free integer job_id.

    Adzuna ids are usually numeric strings, and the Opportunities route calls
    ``int(job["job_id"])`` on every row it renders, so a non-numeric id would
    break the page. Non-numeric ids fall back to a deterministic crc32-derived
    value so the same job keeps the same id across requests.
    """
    if raw_id is None:
        raw = ""
    else:
        raw = str(raw_id).strip()

    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        digest = zlib.crc32(raw.encode("utf-8", "ignore")) if raw else 0
        parsed = _ADZUNA_JOB_ID_OFFSET + (digest % _ADZUNA_JOB_ID_SPAN)
    else:
        # Force every live id into the reserved range so it can never collide
        # with a local dataset id.
        parsed = _ADZUNA_JOB_ID_OFFSET + (parsed % _ADZUNA_JOB_ID_SPAN)

    return parsed


def _first(value, default=""):
    """Adzuna occasionally returns a dict instead of a string for these fields."""
    if isinstance(value, dict):
        return value.get("display_name") or value.get("label") or default
    if value is None:
        return default
    return str(value)


def _salary_text(raw: dict) -> str:
    minimum = raw.get("salary_min")
    maximum = raw.get("salary_max")
    if minimum is None and maximum is None:
        return ""
    low = int(minimum) if isinstance(minimum, (int, float)) else None
    high = int(maximum) if isinstance(maximum, (int, float)) else None
    if low is not None and high is not None and low != high:
        return f"{low:,} - {high:,} per year"
    value = low if low is not None else high
    return f"{value:,} per year" if value is not None else ""


def normalize_result(raw: dict) -> dict | None:
    """Convert one Adzuna result into the CareerAI job shape.

    Requirements are recovered from the listing's own text by
    ``services.job_requirements``. Nothing is invented: a posting with no
    readable requirements yields empty skill fields, which the UI renders as
    "Not specified".
    """
    if not isinstance(raw, dict):
        return None

    title = _first(raw.get("title")).strip()
    company = _first(raw.get("company")).strip()
    if not title or not company:
        return None

    location = _first(raw.get("location")).strip()
    category = raw.get("category") if isinstance(raw.get("category"), dict) else {}
    category_label = _first(category.get("label")).strip() if category else ""

    description = _first(raw.get("description")).strip()
    requirements = extract_requirements(title, description, raw)

    job_type = requirements["job_type"]
    if not job_type:
        # No contract_time/contract_type and nothing inferable from the title.
        # Leave it empty -- the UI hides an empty field rather than showing the
        # job's category ("IT Jobs") as if it were an employment type.
        job_type = ""

    # `domain` is the job family (e.g. "IT Jobs"). Education requirements are a
    # separate, text-derived field -- the category is never used as education.
    return {
        "job_id": _safe_job_id(raw.get("id")),
        "adzuna_id": _first(raw.get("id")).strip(),
        "title": title,
        "company": company,
        "location": location or "Not specified",
        "job_type": job_type,
        "domain": category_label or "Not specified",
        "description": description,
        "responsibilities": "",
        "required_skills": requirements["required_skills"],
        "preferred_skills": requirements["preferred_skills"],
        "qualifications": requirements["education_required"] or "See job description",
        "experience_required": requirements["experience_required"],
        "education_required": requirements["education_required"],
        "stipend_or_salary": _salary_text(raw),
        "apply_link": _first(raw.get("redirect_url")).strip(),
        # Real dates from the listing, or "" when the source omits them.
        # Adzuna's search response publishes `created` but no expiry, so
        # application_deadline is normally "" and renders as "Not specified".
        "published_date": published_date(raw),
        "application_deadline": application_deadline(raw),
        "source": "adzuna",
        # No `score` key: live jobs are not embedded, so the existing matcher
        # correctly reports no semantic component for them.
    }


def search_jobs(
    query: str,
    location: str = "",
    country_code: str = "",
    page: int = 1,
    results_per_page: int = 20,
) -> list[dict]:
    """Return normalized live jobs, or an empty list for any reason at all."""
    if not is_configured():
        logger.debug("Adzuna skipped: not configured or disabled.")
        return []

    country = (country_code or config.ADZUNA_COUNTRY_CODE or "in").strip().lower()

    try:
        page = max(1, int(page))
    except (TypeError, ValueError):
        page = 1

    try:
        per_page = int(results_per_page)
    except (TypeError, ValueError):
        per_page = 20
    per_page = max(1, min(per_page, config.ADZUNA_MAX_RESULTS or 50))

    params = {
        "app_id": (config.ADZUNA_APP_ID or "").strip(),
        "app_key": (config.ADZUNA_APP_KEY or "").strip(),
        "results_per_page": per_page,
        "content-type": "application/json",
    }
    what = (query or "").strip()
    if what:
        params["what"] = what[:200]
    where = (location or "").strip()
    if where:
        params["where"] = where[:120]

    url = f"{ADZUNA_BASE_URL}/{country}/search/{page}"

    try:
        import httpx
    except ImportError:  # pragma: no cover - httpx is a declared dependency
        logger.warning("Adzuna skipped: httpx is not installed.")
        return []

    timeout = config.ADZUNA_TIMEOUT_SECONDS or 8.0

    try:
        response = httpx.get(
            url,
            params=params,
            timeout=timeout,
            follow_redirects=True,
        )
    except Exception as exc:
        # Log the type only: httpx may embed the credential-bearing URL.
        logger.warning("Adzuna request failed (%s); using local dataset.", type(exc).__name__)
        return []

    status = getattr(response, "status_code", 0)
    if status != 200:
        logger.warning("Adzuna returned HTTP %s; using local dataset.", status)
        return []

    try:
        payload = response.json()
    except Exception:
        logger.warning("Adzuna returned a non-JSON body; using local dataset.")
        return []

    if not isinstance(payload, dict):
        logger.warning("Adzuna returned an unexpected JSON shape; using local dataset.")
        return []

    results = payload.get("results")
    if not isinstance(results, list):
        logger.warning("Adzuna payload had no usable 'results' list; using local dataset.")
        return []

    jobs = []
    for raw in results:
        try:
            job = normalize_result(raw)
        except Exception:
            logger.debug("Skipped one malformed Adzuna entry (%s).", type(raw).__name__)
            continue
        if job:
            jobs.append(job)

    if not jobs:
        logger.info("Adzuna returned no usable jobs; using local dataset.")
        return []

    # Remember them so Skill Gap / AI Summary / Interview can resolve the
    # synthetic ids they receive from the Opportunities page links.
    try:
        from services import live_job_store

        live_job_store.remember(jobs)
    except Exception:  # pragma: no cover - cache is best-effort only
        logger.debug("Live job cache unavailable.", exc_info=True)

    logger.info("Adzuna returned %d usable job(s) for country=%s.", len(jobs), country)
    return jobs