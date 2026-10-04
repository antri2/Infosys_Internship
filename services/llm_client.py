"""
Shared Groq LLM call, used by skill_gap_service, resume_agent, and
cover_letter_agent (resume_parser.py has its own copy of this same logic
predating this file -- fine to leave as-is, or point it here later).

Does NOT catch errors -- callers call generate(), catch whatever it
raises, and decide their own fallback behavior, same pattern already
established in resume_parser.py.
"""
import json
from functools import lru_cache

import config


@lru_cache(maxsize=1)
def _get_client():
    from groq import Groq
    return Groq(api_key=config.GROQ_API_KEY)


def generate(prompt: str, max_tokens: int = 3000, temperature: float = 0.3) -> str:
    client = _get_client()
    # Keep the request compatible with the installed Groq SDK as well as
    # hosted Groq.  Older SDK releases reject optional reasoning kwargs before
    # the request is sent, which previously made every assistant turn appear
    # to be a model failure.  The configured model/provider remain unchanged;
    # unsupported optional parameters are simply omitted.
    response = client.chat.completions.create(
        model=config.GROQ_MODEL_NAME,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        temperature=temperature,
    )
    content = response.choices[0].message.content
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("The LLM returned an empty completion.")
    return content


def extract_json_object(raw_text: str) -> dict:
    """Pulls the {...} JSON object out of a model reply even if it added
    stray text or markdown fences around it."""
    raw_text = raw_text.strip()
    if raw_text.startswith("```"):
        raw_text = raw_text.strip("`")
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]
        raw_text = raw_text.strip()

    start, end = raw_text.find("{"), raw_text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("No JSON object found in the model's output.")
    data = json.loads(raw_text[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError("Model output was not a JSON object.")
    return data