"""
M2.2 -- RAG pipeline: build the vector index, and search it.

    Job Dataset -> Chunking -> Embeddings -> FAISS -> Semantic Search -> Top-K Jobs

build_index()      reads data/jobs_clean.csv, chunks + embeds every
                    posting, saves the FAISS index + metadata to
                    data/vector_store/. Run this once after the dataset
                    changes.
semantic_search()  embeds a query, searches the index, returns the
                    top-k unique job postings (collapsing the 2 chunks
                    per job back into one result per job).
"""
import csv
import json
from functools import lru_cache
from pathlib import Path

import faiss

from services.Embedding_service import embed_texts, embed_query
from services.Job_chunker import build_chunks

DATA_PATH = Path(__file__).resolve().parent.parent / "Data" / "jobs_clean.csv"
STORE_DIR = Path(__file__).resolve().parent.parent / "Data" / "vector_store"
INDEX_PATH = STORE_DIR / "jobs.index"
METADATA_PATH = STORE_DIR / "metadata.json"
JOBS_LOOKUP_PATH = STORE_DIR / "jobs_lookup.json"

MIN_SEMANTIC_SCORE = 0.65
MAX_TOP_K = 100


def build_index():
    with open(DATA_PATH, newline="", encoding="utf-8") as f:
        jobs = list(csv.DictReader(f))
    print(f"Loaded {len(jobs)} clean job postings from {DATA_PATH.name}")

    all_chunks = []
    for job in jobs:
        all_chunks.extend(build_chunks(job))
    print(f"Split into {len(all_chunks)} chunks ({len(all_chunks) // len(jobs)} per posting)")

    texts = [c["text"] for c in all_chunks]
    print("Generating embeddings (first run downloads the model, ~100MB)...")
    vectors = embed_texts(texts)
    dim = vectors.shape[1]

    index = faiss.IndexFlatIP(dim)  # inner product on normalized vectors = cosine similarity
    index.add(vectors)

    STORE_DIR.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(INDEX_PATH))

    # metadata.json: vector position -> {job_id, job_title, company, chunk_type}
    jobs_by_id = {job["job_id"]: job for job in jobs}
    metadata = {}
    for i, c in enumerate(all_chunks):
        job = jobs_by_id[c["job_id"]]
        metadata[str(i)] = {
            "job_id": c["job_id"],
            "job_title": job["title"],
            "company": job["company"],
            "chunk_type": c["chunk_type"],
        }
    with open(METADATA_PATH, "w", encoding="utf-8") as f:
        json.dump(metadata, f)

    with open(JOBS_LOOKUP_PATH, "w", encoding="utf-8") as f:
        json.dump(jobs_by_id, f)

    print(f"Saved FAISS index ({index.ntotal} vectors, dim={dim}) to {INDEX_PATH}")
    print(f"Saved metadata to {METADATA_PATH}")
    print(f"Saved job lookup table to {JOBS_LOOKUP_PATH}")


def validate_store_against_csv() -> dict:
    """Validate that the checked-in FAISS artifacts match the canonical CSV."""
    with open(DATA_PATH, newline="", encoding="utf-8-sig") as f:
        jobs = list(csv.DictReader(f))

    with open(METADATA_PATH, encoding="utf-8") as f:
        metadata = json.load(f)
    with open(JOBS_LOOKUP_PATH, encoding="utf-8") as f:
        jobs_lookup = json.load(f)

    expected_lookup = {job["job_id"]: job for job in jobs}
    if jobs_lookup != expected_lookup:
        raise RuntimeError("FAISS lookup data does not match Data/jobs_clean.csv")

    expected_metadata_ids = set(range(len(jobs) * 2))
    actual_metadata_ids = {int(index) for index in metadata}
    if actual_metadata_ids != expected_metadata_ids:
        raise RuntimeError("FAISS metadata indexes are missing, duplicated, or non-contiguous")

    metadata_job_ids = {str(item["job_id"]) for item in metadata.values()}
    if metadata_job_ids != set(expected_lookup):
        raise RuntimeError("FAISS metadata job IDs do not match the canonical CSV")

    index = faiss.read_index(str(INDEX_PATH))
    if index.ntotal != len(metadata):
        raise RuntimeError(
            f"FAISS vector count {index.ntotal} does not match metadata count {len(metadata)}"
        )

    return {
        "job_count": len(jobs),
        "vector_count": int(index.ntotal),
        "dimension": int(index.d),
    }


@lru_cache(maxsize=1)
def _load_store():
    if not INDEX_PATH.exists():
        raise FileNotFoundError(
            "Vector index not found. Run rag_service.build_index() "
            "(or `python -c \"from services.rag_service import build_index; build_index()\"`) first."
        )
    index = faiss.read_index(str(INDEX_PATH))
    with open(METADATA_PATH, encoding="utf-8") as f:
        metadata = json.load(f)
    with open(JOBS_LOOKUP_PATH, encoding="utf-8") as f:
        jobs_lookup = json.load(f)
    return index, metadata, jobs_lookup


def _semantic_label(score: float) -> str:
    if score >= 0.80:
        return "strong"
    if score >= 0.72:
        return "good"
    if score >= MIN_SEMANTIC_SCORE:
        return "moderate"
    return "limited"


def semantic_search(
    query: str,
    top_k: int = 5,
    min_score: float = MIN_SEMANTIC_SCORE,
) -> list[dict]:
    """
    Return up to top_k unique jobs whose best chunk meets min_score.

    FastEmbed/BAAI embeddings, FAISS IndexFlatIP, chunking, and the checked-in
    index remain unchanged. Low-relevance results are omitted rather than
    replaced with unrelated fallback rows.
    """
    if not isinstance(top_k, int) or isinstance(top_k, bool) or not 1 <= top_k <= MAX_TOP_K:
        raise ValueError(f"top_k must be an integer between 1 and {MAX_TOP_K}")
    if not 0.0 <= float(min_score) <= 1.0:
        raise ValueError("min_score must be between 0 and 1")
    if not query or not query.strip():
        return []

    index, metadata, jobs_lookup = _load_store()
    query_vector = embed_query(query.strip()).reshape(1, -1)
    fetch_k = min(top_k, index.ntotal)
    scores, indices = index.search(query_vector, fetch_k)

    best_per_job = {}
    for score, idx in zip(scores[0], indices[0]):
        if idx == -1 or float(score) < min_score:
            continue
        chunk_info = metadata[str(idx)]
        job_id = chunk_info["job_id"]
        if job_id not in best_per_job or score > best_per_job[job_id][0]:
            best_per_job[job_id] = (float(score), chunk_info["chunk_type"])

    ranked = sorted(best_per_job.items(), key=lambda item: item[1][0], reverse=True)[:top_k]

    results = []
    for job_id, (score, chunk_type) in ranked:
        job = dict(jobs_lookup[job_id])
        job["score"] = round(score, 4)
        job["matched_chunk"] = chunk_type
        job["semantic_label"] = _semantic_label(score)
        results.append(job)
    return results