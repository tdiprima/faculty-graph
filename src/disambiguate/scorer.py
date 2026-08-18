"""LLM-based disambiguation for candidate publication matches.

Uses the Anthropic Messages API to evaluate whether a candidate publication
belongs to a specific faculty member. Stores recommendations as evidence,
not as final truth.

Requires ANTHROPIC_API_KEY environment variable.
"""

import json
import logging
import os
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

logger = logging.getLogger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-sonnet-4-20250514"


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


def _call_api(prompt, api_key, model=None):
    """Call Anthropic Messages API and return parsed response."""
    model = model or DEFAULT_MODEL
    payload = json.dumps({
        "model": model,
        "max_tokens": 300,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")

    request = Request(
        ANTHROPIC_API_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
            text = data["content"][0]["text"]
            return json.loads(text)
    except (HTTPError, URLError) as error:
        logger.error("Anthropic API error: %s", error)
        return None
    except (json.JSONDecodeError, KeyError, IndexError) as error:
        logger.error("Failed to parse LLM response: %s", error)
        return None


def score_candidate(faculty, candidate, known_publications=None, api_key=None):
    """Score a single candidate publication match.

    Returns dict with recommendation, confidence, explanation, or None on failure.
    """
    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.error("ANTHROPIC_API_KEY not set. Cannot run LLM disambiguation.")
        return None

    prompt = _build_prompt(faculty, candidate, known_publications)
    result = _call_api(prompt, api_key)

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


def score_batch(faculty, candidates, known_publications=None, api_key=None):
    """Score multiple candidate publications for one faculty member.

    Returns list of score dicts. Low-confidence results (< 0.7) are flagged
    for human review.
    """
    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.error("ANTHROPIC_API_KEY not set. Cannot run LLM disambiguation.")
        return []

    scores = []
    for candidate in candidates:
        result = score_candidate(faculty, candidate, known_publications, api_key)
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
