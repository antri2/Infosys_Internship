"""
M2.1 -- Dataset cleaning.

Reads data/jobs_raw.csv and produces data/jobs_clean.csv by:
  1. Dropping exact duplicate postings (same title + company + location)
  2. Dropping incomplete postings (missing any required field)
  3. Dropping irrelevant/junk rows (heuristic: too short a description)
  4. Normalizing whitespace across all text fields

Run:
    python data/clean_dataset.py
Produces:
    data/jobs_clean.csv
Prints a before/after summary so the cleaning step is visible and
verifiable, not a silent no-op.
"""
import csv
from pathlib import Path

RAW_PATH = Path(__file__).resolve().parent / "jobs_raw.csv"
CLEAN_PATH = Path(__file__).resolve().parent / "jobs_clean.csv"

REQUIRED_FIELDS = [
    "title", "company", "location", "description",
    "required_skills", "qualifications",
]

MIN_DESCRIPTION_WORDS = 5  # below this, treat as junk/irrelevant


def normalize(value: str) -> str:
    return " ".join(value.strip().split())


def is_incomplete(row: dict) -> bool:
    return any(not normalize(row.get(field, "")) for field in REQUIRED_FIELDS)


def is_irrelevant(row: dict) -> bool:
    desc = normalize(row.get("description", ""))
    return len(desc.split()) < MIN_DESCRIPTION_WORDS


def dedup_key(row: dict) -> tuple:
    return (
        normalize(row.get("title", "")).lower(),
        normalize(row.get("company", "")).lower(),
        normalize(row.get("location", "")).lower(),
    )


def main():
    with open(RAW_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    total_raw = len(rows)

    # Normalize whitespace across every field first
    for row in rows:
        for key in row:
            row[key] = normalize(row[key] or "")

    incomplete = [r for r in rows if is_incomplete(r)]
    rows = [r for r in rows if not is_incomplete(r)]

    irrelevant = [r for r in rows if is_irrelevant(r)]
    rows = [r for r in rows if not is_irrelevant(r)]

    seen = set()
    deduped = []
    duplicates = []
    for row in rows:
        key = dedup_key(row)
        if key in seen:
            duplicates.append(row)
            continue
        seen.add(key)
        deduped.append(row)

    with open(CLEAN_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(deduped)

    print("Cleaning summary")
    print("-" * 40)
    print(f"Raw rows:              {total_raw}")
    print(f"Removed (incomplete):  {len(incomplete)}")
    print(f"Removed (irrelevant):  {len(irrelevant)}")
    print(f"Removed (duplicates):  {len(duplicates)}")
    print(f"Final clean rows:      {len(deduped)}")
    print(f"Saved to: {CLEAN_PATH}")


if __name__ == "__main__":
    main()