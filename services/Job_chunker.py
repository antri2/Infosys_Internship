"""
M2.2 -- Field-based chunking for job postings.

Splits each job posting into two meaningful chunks instead of one giant
blob of text (and instead of blind 500-character splitting, which would
cut sentences/skills lists in half for no reason):

  - "overview" chunk -> title, company, location, job type, description,
                         qualifications, experience/education requirements
  - "skills" chunk   -> required skills, preferred skills, responsibilities

Why split at all: a query like "internship needing Python and Pandas"
should match strongly on the skills chunk. A query like "remote
marketing internship in Bangalore" should match on the overview chunk.
One combined vector per job would blur both signals together.
"""


def build_chunks(job: dict) -> list[dict]:
    """
    job: one row from the cleaned jobs dataset (dict with the CSV's
    column names: title, company, location, job_type, description,
    qualifications, experience_required, education_required,
    required_skills, preferred_skills, responsibilities, ...).

    Returns a list of chunk dicts: {job_id, chunk_type, text}
    """
    overview_text = (
        f"Job Title: {job['title']}\n"
        f"Company: {job['company']}\n"
        f"Location: {job['location']}\n"
        f"Job Type: {job['job_type']}\n"
        f"Description: {job['description']}\n"
        f"Qualifications: {job['qualifications']}\n"
        f"Experience Required: {job['experience_required']}\n"
        f"Education Required: {job['education_required']}"
    )
    skills_text = (
        f"Job Title: {job['title']}\n"
        f"Required Skills: {job['required_skills']}\n"
        f"Preferred Skills: {job['preferred_skills']}\n"
        f"Responsibilities: {job['responsibilities']}"
    )
    return [
        {"job_id": job["job_id"], "chunk_type": "overview", "text": overview_text},
        {"job_id": job["job_id"], "chunk_type": "skills", "text": skills_text},
    ]