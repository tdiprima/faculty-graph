"""LLM-based disambiguation for candidate publication matches.

Uses a local Ollama instance to evaluate whether a candidate
publication belongs to a specific faculty member. Stores recommendations as
evidence, not as final truth.

Requires Ollama running locally. Configure with the OLLAMA_URL and OLLAMA_MODEL
environment variables (defaults: http://localhost:11434, gemma4).
"""

import json
import logging
import os
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("OLLAMA_MODEL", "gemma4")


def _build_prompt(faculty, candidate, known_publications=None):
    """Build a disambiguation prompt for the LLM."""
    known_titles = ""
    if known_publications:
        titles = [p.get("title", "") for p in known_publications[:10]]
        known_titles = "\n".join(f"  - {t}" for t in titles if t)

    return f"""Evaluate whether this candidate publication belongs to this faculty member.

FACULTY:
  Name: {faculty["full_name"]}
  Department: {faculty.get("department", "unknown")}
  Institution: Example University
  ORCID: {faculty.get("orcid", "none")}

CANDIDATE PUBLICATION:
  Title: {candidate.get("title", "unknown")}
  Authors: {", ".join(candidate.get("authors", [])) or "unknown"}
  Journal: {candidate.get("journal", "unknown")}
  Date: {candidate.get("date", "unknown")}
  DOI: {candidate.get("doi", "none")}
  Affiliations mentioned: {candidate.get("affiliation", "unknown")}
  Source: {candidate.get("source", "unknown")}

KNOWN VERIFIED PUBLICATIONS (from ORCID):
{known_titles or "  (none available)"}

Respond with ONLY a JSON object (no other text):
{{
  "recommendation": "likely_match" | "uncertain" | "likely_not_match",
  "confidence": 0.0 to 1.0,
  "explanation": "brief reasoning"
}}"""


def _call_api(prompt, model=None):
    """Call Ollama generate API and return parsed response."""
    model = model or DEFAULT_MODEL
    url = f"{OLLAMA_BASE_URL}/api/generate"
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_predict": 300,
        },
    }).encode("utf-8")

    request = Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=120) as response:
            data = json.loads(response.read().decode("utf-8"))
            text = data.get("response", "")
            text = text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                text = text.rsplit("```", 1)[0]
            return json.loads(text)
    except (HTTPError, URLError) as error:
        logger.error("Ollama API error: %s", error)
        return None
    except (json.JSONDecodeError, KeyError, IndexError) as error:
        logger.error("Failed to parse LLM response: %s", error)
        return None


def score_candidate(faculty, candidate, known_publications=None):
    """Score a single candidate publication match.

    Returns dict with recommendation, confidence, explanation, or None on failure.
    """
    prompt = _build_prompt(faculty, candidate, known_publications)
    result = _call_api(prompt)

    if result:
        result["faculty_id"] = faculty.get("faculty_id")
        result["work_doi"] = candidate.get("doi")
        result["work_pmid"] = candidate.get("pmid")
        result["work_title"] = candidate.get("title")
        logger.info(
            "LLM scored %s for %s: %s (%.2f)",
            candidate.get("title", "?")[:60],
            faculty["full_name"],
            result.get("recommendation"),
            result.get("confidence", 0),
        )
    return result


def score_batch(faculty, candidates, known_publications=None):
    """Score multiple candidate publications for one faculty member.

    Returns list of score dicts. Low-confidence results (< 0.7) are flagged
    for human review.
    """
    scores = []
    for candidate in candidates:
        result = score_candidate(faculty, candidate, known_publications)
        if result:
            if result.get("confidence", 0) < 0.7:
                result["needs_human_review"] = True
            scores.append(result)

    logger.info(
        "Scored %d candidates for %s: %d need review",
        len(scores),
        faculty["full_name"],
        sum(1 for s in scores if s.get("needs_human_review")),
    )
    return scores


def save_scores(scores, output_path):
    """Save disambiguation scores to JSON for review."""
    with open(output_path, "w", encoding="utf-8") as outfile:
        json.dump(scores, outfile, indent=2, ensure_ascii=False)
    logger.info("Saved %d disambiguation scores to %s", len(scores), output_path)
