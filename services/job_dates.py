"""Date normalisation for job records.

Two sources, one output shape:

* Live Adzuna listings carry a real posting timestamp in ``created``.
* The local dataset has no posting date at all; MySQL's ``jobs.created_at`` is
  the row-import timestamp, which is the only existing field available.

Neither source exposes an application deadline in the fields we receive
(Adzuna's search response has no expiry/deadline key), so that field is filled
only when a source actually provides one. Nothing here invents, defaults, or
derives a date that the source did not state -- an absent date renders as
``Not specified`` rather than being filled in with today.
"""

from datetime import datetime, timedelta, timezone


DISPLAY_FORMAT = "%d %b %Y"

# The Adzuna key that carries the posting timestamp.
PUBLISHED_KEYS = ("created", "published", "published_at", "date_posted")

# Candidate keys for an application deadline. Adzuna's search response currently
# includes none of these; the list exists so that if a source does publish one
# it is picked up without a code change, and so a missing key is a normal case
# rather than a guess.
DEADLINE_KEYS = (
    "application_deadline",
    "expires",
    "expiration",
    "closing_date",
    "closingDate",
    "valid_until",
    "end_date",
)

_FALLBACK_FORMATS = (
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%b %d, %Y",
    "%d %b %Y",
)


def _to_naive_utc(value: datetime) -> datetime:
    """Job dates are date-only, so drop the tz after converting to UTC.

    Keeping everything naive avoids comparing aware and naive values, which
    would raise, and guarantees the displayed date matches the source's UTC day.
    """
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def parse_datetime(value) -> datetime | None:
    """Parse the timestamp shapes job sources actually send, or return None.

    Returns a naive UTC datetime. Never guesses: an unrecognised value yields
    None so the caller can render ``Not specified`` instead of showing
    something wrong.
    """
    if value is None or isinstance(value, bool):
        return None

    if isinstance(value, datetime):
        return _to_naive_utc(value)

    text = str(value).strip()
    if not text:
        return None

    # ISO 8601, tolerating the trailing Z and a trailing offset.
    iso_candidate = text.replace("Z", "+00:00") if text.endswith("Z") else text
    try:
        return _to_naive_utc(datetime.fromisoformat(iso_candidate))
    except ValueError:
        pass

    # Adzuna sometimes appends fractional seconds the ISO parser rejects.
    trimmed = iso_candidate.split(".")[0] if "." in iso_candidate else iso_candidate
    if trimmed != iso_candidate:
        try:
            return _to_naive_utc(datetime.fromisoformat(trimmed))
        except ValueError:
            pass

    for fmt in _FALLBACK_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue

    return None


def format_date(value) -> str:
    """Human-readable date, or "" when the value is missing or unparseable."""
    parsed = parse_datetime(value)
    if parsed is None:
        return ""
    return parsed.strftime(DISPLAY_FORMAT)


def _first_value(raw: dict, keys: tuple[str, ...]):
    for key in keys:
        if key in raw and raw[key] not in (None, ""):
            return raw[key]
    return None


def published_date(raw: dict) -> str:
    """Posting date for a live listing, or "" when the source omits it."""
    if not isinstance(raw, dict):
        return ""
    return format_date(_first_value(raw, PUBLISHED_KEYS))


def application_deadline(raw: dict) -> str:
    """Last date to apply, or "" when the source does not publish one."""
    if not isinstance(raw, dict):
        return ""
    return format_date(_first_value(raw, DEADLINE_KEYS))


def is_expired(deadline_text: str, today: datetime | None = None) -> bool | None:
    """True/False when a deadline exists, None when there is no deadline.

    A source that publishes no deadline must never be treated as expired.
    """
    parsed = parse_datetime(deadline_text)
    if parsed is None:
        return None
    reference = today or datetime.now(timezone.utc).replace(tzinfo=None)
    return parsed.date() < reference.date()


# ==========================================================================
# Dashboard card rules
# --------------------------------------------------------------------------
# Three separate questions, kept separate because conflating them is how a
# dashboard ends up showing a fake deadline as though an employer had set it.
#
# 1. Is there a real publication date?
#    `validated_publication_date` only returns a date that parses *and* is
#    plausible. A local seeded row's `created_at` is a row-import timestamp, not
#    a posting date, so it is never treated as one -- those listings are badged
#    as demo data instead of being given a date they never had. An implausible
#    year (2019, 2021, the future) is rejected rather than replaced with
#    today's date.
#
# 2. Is there an employer deadline?
#    Nothing in either job source publishes one, so `application_deadline` is ""
#    for every listing and that is the honest state.
#
# 3. Then what date does the card show?
#    `suggested_apply_by` returns a self-imposed planning window under an
#    explicitly non-employer label.
#
# The rule behind (3) is one constant, so it is auditable: a 14-day application
# window counted from the day the dashboard is rendered. It is deliberately not
# varied by job type, because we know nothing about these employers' real
# processes, and a per-employer-looking rule would imply knowledge we lack.
# ==========================================================================

# Label for the derived date. The wording is the guard rail: "Suggested" and
# "Apply By" together say plainly that this is not the employer's deadline.
SUGGESTED_DEADLINE_LABEL = "Suggested Apply By"

# The documented rule behind SUGGESTED_DEADLINE_LABEL.
SUGGESTED_WINDOW_DAYS = 14

# A publication date further back than this is treated as stale rather than
# real. Chosen to cover a plausible posting age without silently accepting a
# 2019 row and quietly re-dating it.
MAX_PUBLICATION_AGE_DAYS = 730

# Listing sources that are generated rather than supplied by an employer.
#
# Two labels refer to the same seeded dataset and both must be recognised:
#   "synthetic" -- the jobs.source column value, written by the CSV loader;
#   "local"     -- assigned by services.opportunity_service.py to every row it
#                  reads back from that table, and what the template actually
#                  receives.
# Recognising only the column value silently left the majority of listings
# unbadged, which is the opposite of the intent.
DEMO_SOURCES = frozenset({"synthetic", "local", "demo", "sample", "seed"})

# The label shown next to a generated listing.
DEMO_BADGE = "Demo listing"


def is_demo_listing(job: dict | None) -> bool:
    """True when the listing is generated rather than employer-supplied.

    Decided by the source label the ranking layer attaches, never inferred from
    the shape of the text. A live Adzuna listing arrives with "adzuna" and is
    therefore never badged.
    """
    if not isinstance(job, dict):
        return False
    return str(job.get("source") or "").strip().lower() in DEMO_SOURCES


def demo_badge(job: dict | None) -> str:
    """Badge text for a generated listing, or "" when it is a real one."""
    return DEMO_BADGE if is_demo_listing(job) else ""


def validated_publication_date(value, today: datetime | None = None) -> str:
    """A publication date only when the source value is real and plausible.

    Rejects, rather than repairs:
      * anything unparseable;
      * dates more than MAX_PUBLICATION_AGE_DAYS old;
      * dates in the future.

    A rejected value returns "", so the card omits the field entirely. It is
    never substituted with the current date.
    """
    parsed = parse_datetime(value)
    if parsed is None:
        return ""

    reference = today or datetime.now(timezone.utc).replace(tzinfo=None)
    reference_date = reference.date()
    parsed_date = parsed.date()

    if parsed_date > reference_date:
        return ""
    if (reference_date - parsed_date).days > MAX_PUBLICATION_AGE_DAYS:
        return ""
    return parsed.strftime(DISPLAY_FORMAT)


def suggested_apply_by(today: datetime | None = None) -> str:
    """A planning window for a listing with no published deadline.

    Rule: today + SUGGESTED_WINDOW_DAYS days, identical for every listing. Must
    be rendered together with SUGGESTED_DEADLINE_LABEL so it is never mistaken
    for the employer's deadline.
    """
    reference = today or datetime.now(timezone.utc).replace(tzinfo=None)
    return (reference + timedelta(days=SUGGESTED_WINDOW_DAYS)).strftime(DISPLAY_FORMAT)


def apply_by_for(job: dict | None, today: datetime | None = None) -> dict:
    """The single source of truth for a card's apply-by row.

    Returns the label and the value together, so the two cannot drift apart:

        {"label": "Application deadline", "value": "...", "suggested": False}
        {"label": "Suggested Apply By",    "value": "...", "suggested": True}

    A listing with a real deadline keeps it, even when it has passed, because
    hiding it would remove the one fact the reader needs.
    """
    job = job if isinstance(job, dict) else {}
    real = str(job.get("application_deadline") or "").strip()
    if real:
        return {"label": "Application deadline", "value": real, "suggested": False}
    return {
        "label": SUGGESTED_DEADLINE_LABEL,
        "value": suggested_apply_by(today),
        "suggested": True,
    }
