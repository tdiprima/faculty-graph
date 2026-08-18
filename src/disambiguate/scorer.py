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

from src.config import institution_name

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("OLLAMA_MODEL", "gemma4")

VALID_RECOMMENDATIONS = ("likely_match", "uncertain", "likely_not_match")
HUMAN_REVIEW_CONFIDENCE = 0.7
REQUEST_TIMEOUT_SECONDS = 120
# Thinking-capable models spend their whole budget reasoning and return an empty
# response, so thinking is disabled and the budget leaves room for a full verdict.
MAX_RESPONSE_TOKENS = 500


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
  Institution: {institution_name()}
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
        "think": False,
        "format": "json",
        "options": {
            "temperature": 0.1,
            "num_predict": MAX_RESPONSE_TOKENS,
        },
    }).encode("utf-8")

    request = Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        logger.error("Ollama HTTP %d (model %s): %s", error.code, model, error.reason)
        return None
    except URLError as error:
        logger.error("Cannot reach Ollama at %s: %s", OLLAMA_BASE_URL, error.reason)
        return None
    except TimeoutError:
        logger.error("Ollama timed out after %d seconds (model %s)", REQUEST_TIMEOUT_SECONDS, model)
        return None
    except json.JSONDecodeError as error:
        logger.error("Ollama returned malformed JSON envelope: %s", error)
        return None

    if data.get("done_reason") == "length":
        logger.error(
            "Ollama (model %s) hit the %d-token limit before finishing its verdict; "
            "raise MAX_RESPONSE_TOKENS or pick a model that answers without reasoning first",
            model,
            MAX_RESPONSE_TOKENS,
        )
        return None

    return _parse_recommendation(data.get("response", ""))


def _strip_code_fence(text):
    """Remove a Markdown code fence that small models often wrap JSON in."""
    text = text.strip()
    if not text.startswith("```"):
        return text
    text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    return text.rsplit("```", 1)[0]


def _parse_recommendation(raw_text):
    """Parse and validate the model's JSON verdict.

    Local models emit malformed or unexpectedly shaped output often enough that
    the caller must not assume a dict came back.
    """
    if not raw_text.strip():
        logger.error("LLM returned an empty response")
        return None

    try:
        parsed = json.loads(_strip_code_fence(raw_text))
    except json.JSONDecodeError as error:
        logger.error("LLM response was not JSON: %s (got %r)", error, raw_text[:200])
        return None

    if not isinstance(parsed, dict):
        logger.error("LLM response was %s, expected an object", type(parsed).__name__)
        return None

    recommendation = parsed.get("recommendation")
    if recommendation not in VALID_RECOMMENDATIONS:
        logger.error("LLM returned unknown recommendation %r", recommendation)
        return None

    confidence = parsed.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        logger.error("LLM returned non-numeric confidence %r", confidence)
        return None
    if not 0.0 <= confidence <= 1.0:
        logger.error("LLM returned out-of-range confidence %r", confidence)
        return None

    return {
        "recommendation": recommendation,
        "confidence": float(confidence),
        "explanation": str(parsed.get("explanation", "")),
    }


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
            result["recommendation"],
            result["confidence"],
        )
    return result


def score_batch(faculty, candidates, known_publications=None):
    """Score multiple candidate publications for one faculty member.

    Returns list of score dicts. Results below HUMAN_REVIEW_CONFIDENCE are
    flagged for human review.
    """
    scores = []
    for candidate in candidates:
        result = score_candidate(faculty, candidate, known_publications)
        if result:
            if result["confidence"] < HUMAN_REVIEW_CONFIDENCE:
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
