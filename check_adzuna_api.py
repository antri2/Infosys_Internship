"""
Standalone Adzuna connectivity check -- backend only.

Verifies that the Adzuna job-listings API is reachable and that the India
search endpoint returns real results, then prints the response structure.

    python check_adzuna_api.py
    python check_adzuna_api.py --what "machine learning" --results 3

This script is deliberately read-only and completely side-effect free:
it never touches MySQL, the FAISS vector store, Data/jobs_clean.csv, or any
Flask route/template. It only performs an outbound HTTPS GET.

Credentials are read from config, i.e. from the ADZUNA_APP_ID and
ADZUNA_APP_KEY entries in .env (or from the process environment).
If they are absent the script exits 0 with a clear explanation rather than
making a request that could only ever fail with 401.

Exit codes:
    0  reachable, results returned (or skipped because no credentials)
    1  credentials present but the call failed / returned nothing usable
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config

ADZUNA_BASE = "https://api.adzuna.com/v1/api/jobs"
# Adzuna country code for India.
INDIA_COUNTRY_CODE = "in"
TIMEOUT_SECONDS = 20.0


def _mask(value: str, keep: int = 3) -> str:
    value = (value or "").strip()
    if not value:
        return "(empty)"
    return value if len(value) <= keep else f"{value[:keep]}***({len(value)} chars)"


def describe(results: list, sample_fields: int = 12) -> None:
    """Print the shape of the payload: top-level keys, per-result keys, sample."""
    print("\n--- Response structure ---")
    print(f"  results returned : {len(results)}")

    if not results:
        print("  (no results to describe)")
        return

    first = results[0]
    print(f"  keys per result  : {len(first)}")
    for key in list(first)[:sample_fields]:
        value = first[key]
        if isinstance(value, str):
            shown = value if len(value) <= 70 else value[:70] + "..."
        elif isinstance(value, (list, dict)):
            shown = f"<{type(value).__name__} len={len(value)}>"
        else:
            shown = repr(value)
        print(f"    {key:22} = {shown}")
    if len(first) > sample_fields:
        print(f"    ... and {len(first) - sample_fields} more field(s)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check the Adzuna India jobs endpoint.")
    parser.add_argument("--what", default="data analyst", help="Search keywords.")
    parser.add_argument("--where", default="India", help="Location filter.")
    parser.add_argument("--results", type=int, default=3, help="results_per_page (1-50).")
    args = parser.parse_args()

    app_id = (config.ADZUNA_APP_ID or "").strip()
    app_key = (config.ADZUNA_APP_KEY or "").strip()

    print("Adzuna connectivity check")
    print("=" * 60)
    print(f"  config.ADZUNA_APP_ID : {_mask(app_id)}")
    print(f"  config.ADZUNA_APP_KEY: {_mask(app_key)}")
    print(f"  .env present        : {Path('.env').exists()}")
    print(f"  endpoint            : {ADZUNA_BASE}/{INDIA_COUNTRY_CODE}/search/1")
    print(f"  what={args.what!r} where={args.where!r} results_per_page={args.results}")

    if not app_id or not app_key:
        print("\nRESULT: SKIPPED - no Adzuna credentials configured.")
        print(
            "  ADZUNA_APP_ID / ADZUNA_APP_KEY are declared in config.py but are not\n"
            "  present in .env, .env.example, or the process environment.\n"
            "  Add them to .env (get a free key at developer.adzuna.com) and re-run:\n"
            "\n      ADZUNA_APP_ID=your_id\n      ADZUNA_APP_KEY=your_key\n"
        )
        print("  Nothing was requested and nothing was changed.")
        return 0

    try:
        import httpx
    except ImportError:
        print("\nRESULT: FAILED - httpx is not installed (pip install httpx).")
        return 1

    params = {
        "app_id": app_id,
        "app_key": app_key,
        "results_per_page": max(1, min(int(args.results), 50)),
        "what": args.what,
        "where": args.where,
        "content-type": "application/json",
    }

    url = f"{ADZUNA_BASE}/{INDIA_COUNTRY_CODE}/search/1"
    print("\n--- Request ---")
    print(f"  GET {url}")
    print(f"  params: {json.dumps({k: (v if k not in ('app_id', 'app_key') else '***') for k, v in params.items()})}")

    try:
        response = httpx.get(url, params=params, timeout=TIMEOUT_SECONDS, follow_redirects=True)
    except httpx.HTTPError as exc:
        print(f"\nRESULT: FAILED - network/transport error: {type(exc).__name__}: {exc}")
        return 1

    print("\n--- HTTP response ---")
    print(f"  status      : {response.status_code} {response.reason_phrase}")
    print(f"  content-type: {response.headers.get('content-type')}")
    print(f"  bytes       : {len(response.content)}")

    if response.status_code != 200:
        print(f"  body        : {response.text[:400]}")
        print("\nRESULT: FAILED - endpoint did not return 200.")
        return 1

    try:
        payload = response.json()
    except ValueError:
        print(f"  body        : {response.text[:400]}")
        print("\nRESULT: FAILED - response was not valid JSON.")
        return 1

    if not isinstance(payload, dict):
        print(f"  type        : {type(payload).__name__}")
        print("\nRESULT: FAILED - top-level JSON was not an object.")
        return 1

    print(f"  top-level keys: {sorted(payload.keys())}")
    print(f"  count field   : {payload.get('count')!r}")
    print(f"  next field    : {'present' if payload.get('next') else 'absent'}")

    results = payload.get("results") or []
    describe(results)

    if not results:
        print("\nRESULT: FAILED - authenticated call returned zero results.")
        return 1

    missing = [k for k in ("id", "title", "company", "location") if k not in results[0]]
    if missing:
        print(f"\nRESULT: FAILED - expected fields missing from result: {missing}")
        return 1

    print("\nRESULT: OK - live Adzuna India results returned.")
    print(f"  reported total matches : {payload.get('count')}")
    print(f"  sample titles          : {[r.get('title') for r in results]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())