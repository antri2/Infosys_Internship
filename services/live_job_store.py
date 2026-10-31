"""Short-lived cache of live Adzuna jobs, keyed by their synthetic job_id.

Skill Gap, AI Summary, Interview Prep and Resume Builder all receive only a
``job_id`` through the Opportunities page links. A live Adzuna job has no row in
MySQL, so those routes need a way to get the job back from its id.

Rather than duplicating the listing into the canonical ``jobs`` table (which
stays the local dataset) or inventing a new persistence layer, the live jobs
are remembered here for a few minutes after they are fetched. A user clicks
through within seconds, so this closes the gap without any schema change.

If the entry has expired -- or this process never saw it -- the resolver returns
None and the caller falls back to its existing "job not found" handling. Nothing
here raises.
"""

import logging
import threading
import time
from collections import OrderedDict

import config
import services.adzuna_service as adzuna_service


logger = logging.getLogger(__name__)

# Keep this short: it only has to survive the click-through from the listing.
DEFAULT_TTL_SECONDS = 900
DEFAULT_MAX_ENTRIES = 500

_lock = threading.Lock()
_cache: "OrderedDict[int, tuple[float, dict]]" = OrderedDict()


def _ttl() -> float:
    try:
        return float(getattr(config, "ADZUNA_JOB_CACHE_TTL_SECONDS", DEFAULT_TTL_SECONDS))
    except (TypeError, ValueError):
        return DEFAULT_TTL_SECONDS


def _max_entries() -> int:
    try:
        return max(1, int(getattr(config, "ADZUNA_JOB_CACHE_MAX_ENTRIES", DEFAULT_MAX_ENTRIES)))
    except (TypeError, ValueError):
        return DEFAULT_MAX_ENTRIES


def remember(jobs: list[dict]) -> None:
    """Store freshly fetched live jobs so their ids can be resolved later."""
    if not jobs:
        return
    now = time.time()
    limit = _max_entries()
    with _lock:
        for job in jobs:
            try:
                job_id = int(job["job_id"])
            except (KeyError, TypeError, ValueError):
                continue
            if not adzuna_service.is_adzuna_job_id(job_id):
                continue
            _cache[job_id] = (now, dict(job))
            _cache.move_to_end(job_id)
        while len(_cache) > limit:
            _cache.popitem(last=False)


def get(job_id) -> dict | None:
    """Return a remembered live job, or None when it is unknown/expired."""
    try:
        job_id = int(job_id)
    except (TypeError, ValueError):
        return None

    with _lock:
        entry = _cache.get(job_id)
        if entry is None:
            return None
        stored_at, job = entry
        # ">=" rather than ">": a TTL of 0 means "never serve from cache", and
        # with ">" an entry written in the same clock tick read back as live.
        if time.time() - stored_at >= _ttl():
            _cache.pop(job_id, None)
            return None
        _cache.move_to_end(job_id)
        return dict(job)


def clear() -> None:
    with _lock:
        _cache.clear()


def size() -> int:
    with _lock:
        return len(_cache)