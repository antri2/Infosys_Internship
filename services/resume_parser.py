"""
Sends resume text to an LLM via Groq's hosted API (free tier, no credit
card) and gets back structured JSON: skills, education, experience,
projects. Nothing is downloaded or run locally -- no torch, no
transformers, no multi-GB model weights on disk. Needs GROQ_API_KEY in
.env (get one free at console.groq.com) and config.GROQ_MODEL_NAME set
to whatever model ID is currently listed at console.groq.com/docs/models.

Parsing/validation logic is kept separate from the API call so it can be
tested without a network connection or an API key.
"""
import json
from functools import lru_cache

import config

EXTRACTION_PROMPT = """You are a resume-parsing assistant. Read the resume text \
below and extract structured information from it.

Return ONLY valid JSON (no other text, no markdown fences, no explanation) \
matching exactly this shape:

{{
  "summary": "one or two sentence summary of the candidate, or null",
  "skills": [{{"name": "Python", "category": "programming_language"}}],
  "education": [{{"institution": "...", "degree": "...", "field": "...", "start_date": "...", "end_date": "..."}}],
  "experience": [{{"title": "...", "organization": "...", "start_date": "...", "end_date": "...", "description": "..."}}],
  "projects": [{{"title": "...", "description": "...", "tech_stack": "..."}}]
}}

Rules:
- If a field isn't present in the resume, use null (not a made-up value).
- Do not invent skills, dates, or experience that aren't in the text.
- "category" for a skill should be one of: programming_language, framework, tool, soft_skill, other.

Resume text:
---
{resume_text}
---
"""

REQUIRED_KEYS = {"summary", "skills", "education", "experience", "projects"}


class ResumeParsingError(Exception):
    pass


@lru_cache(maxsize=1)
def _get_client():
    from groq import Groq
    return Groq(api_key=config.GROQ_API_KEY)


def _generate(prompt: str) -> str:
    client = _get_client()
    response = client.chat.completions.create(
        model=config.GROQ_MODEL_NAME,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=3000,
        temperature=0,
        
        reasoning_effort="low",   # only used by gpt-oss models; ignored
                                   # (safely) by non-reasoning models.
        reasoning_format="hidden",
    )
    return response.choices[0].message.content


def _parse_llm_output(raw_text: str) -> dict:
    """Strips markdown fences if present, then validates the JSON shape."""
    raw_text = raw_text.strip()
    if raw_text.startswith("```"):
        raw_text = raw_text.strip("`")
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]
        raw_text = raw_text.strip()

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise ResumeParsingError(f"LLM did not return valid JSON: {e}")

    if not REQUIRED_KEYS.issubset(data.keys()):
        raise ResumeParsingError(f"LLM output is missing required fields: {REQUIRED_KEYS - data.keys()}")

    data.setdefault("skills", [])
    data.setdefault("education", [])
    data.setdefault("experience", [])
    data.setdefault("projects", [])
    return data


def parse_resume_text(resume_text: str) -> dict:
    prompt = EXTRACTION_PROMPT.format(resume_text=resume_text)
    try:
        raw_text = _generate(prompt)
    except Exception as e:
        raise ResumeParsingError(
            f"Could not reach Groq's API with model '{config.GROQ_MODEL_NAME}'. "
            f"Check GROQ_API_KEY in .env and that you have an internet connection. "
            f"Details: {e}"
        )
    return _parse_llm_output(raw_text)