"""LLM disambiguation scoring.

Local models return malformed or unexpectedly shaped output often enough that
the parser is treated as a trust boundary.
"""

import json
from urllib.error import HTTPError, URLError

import pytest

from src.disambiguate import scorer

VALID_VERDICT = {
    "recommendation": "likely_match",
    "confidence": 0.9,
    "explanation": "co-authors overlap",
}


def _envelope(response_text):
    """Wrap model output in the Ollama /api/generate response envelope."""
    return json.dumps({"response": response_text}).encode("utf-8")


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


# ── response parsing ──────────────────────────────────────────────────────────

def test_valid_verdict_is_normalized():
    result = scorer._parse_recommendation(json.dumps(VALID_VERDICT))

    assert result == {
        "recommendation": "likely_match",
        "confidence": 0.9,
        "explanation": "co-authors overlap",
    }


@pytest.mark.parametrize(
    "fence",
    [
        "```json\n{body}\n```",
        "```\n{body}\n```",
        "  ```json\n{body}\n```  ",
    ],
)
def test_code_fences_are_stripped(fence):
    raw = fence.format(body=json.dumps(VALID_VERDICT))

    assert scorer._parse_recommendation(raw)["recommendation"] == "likely_match"


@pytest.mark.parametrize("confidence", [0, 1, 0.5, 0.0, 1.0])
def test_boundary_confidence_values_are_accepted(confidence):
    verdict = dict(VALID_VERDICT, confidence=confidence)

    result = scorer._parse_recommendation(json.dumps(verdict))

    assert result["confidence"] == float(confidence)
    assert isinstance(result["confidence"], float)


@pytest.mark.parametrize("recommendation", ["likely_match", "uncertain", "likely_not_match"])
def test_every_documented_recommendation_is_accepted(recommendation):
    verdict = dict(VALID_VERDICT, recommendation=recommendation)

    assert scorer._parse_recommendation(json.dumps(verdict)) is not None


def test_missing_explanation_defaults_to_empty_string():
    verdict = {"recommendation": "uncertain", "confidence": 0.5}

    assert scorer._parse_recommendation(json.dumps(verdict))["explanation"] == ""


@pytest.mark.parametrize(
    "raw,reason",
    [
        ("", "empty response"),
        ("   ", "whitespace only"),
        ("Sure! Here is my answer.", "conversational prose"),
        ("{not json", "truncated JSON"),
        ("[{\"recommendation\": \"likely_match\"}]", "array instead of object"),
        ('"likely_match"', "bare string"),
        ("null", "JSON null"),
        ("42", "JSON number"),
        ("true", "JSON boolean"),
        ('{"recommendation": "maybe", "confidence": 0.5}', "unknown recommendation"),
        ('{"confidence": 0.5}', "missing recommendation"),
        ('{"recommendation": null, "confidence": 0.5}', "null recommendation"),
        ('{"recommendation": "uncertain"}', "missing confidence"),
        ('{"recommendation": "uncertain", "confidence": "0.5"}', "confidence as string"),
        ('{"recommendation": "uncertain", "confidence": true}', "confidence as bool"),
        ('{"recommendation": "uncertain", "confidence": null}', "null confidence"),
        ('{"recommendation": "uncertain", "confidence": -0.1}', "confidence below range"),
        ('{"recommendation": "uncertain", "confidence": 1.1}', "confidence above range"),
    ],
)
def test_malformed_responses_are_rejected(raw, reason):
    assert scorer._parse_recommendation(raw) is None, reason


def test_oversized_explanation_is_accepted_without_truncating_the_verdict():
    verdict = dict(VALID_VERDICT, explanation="A" * 100_000)

    result = scorer._parse_recommendation(json.dumps(verdict))

    assert result["recommendation"] == "likely_match"
    assert len(result["explanation"]) == 100_000


def test_quote_heavy_explanation_survives_round_trip():
    verdict = dict(VALID_VERDICT, explanation='he said "yes" ; DROP TABLE works --')

    result = scorer._parse_recommendation(json.dumps(verdict))

    assert result["explanation"] == 'he said "yes" ; DROP TABLE works --'


def test_extra_model_fields_are_discarded():
    verdict = dict(VALID_VERDICT, faculty_id="injected", needs_human_review=False)

    result = scorer._parse_recommendation(json.dumps(verdict))

    assert set(result) == {"recommendation", "confidence", "explanation"}


# ── transport errors ──────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "error",
    [
        HTTPError("http://localhost:11434", 500, "Server Error", {}, None),
        URLError("connection refused"),
        TimeoutError("timed out"),
    ],
    ids=["http_error", "url_error", "timeout"],
)
def test_transport_failures_return_none_instead_of_raising(monkeypatch, error):
    """One slow or failed call must not abort a whole batch."""
    def _raise(*args, **kwargs):
        raise error

    monkeypatch.setattr(scorer, "urlopen", _raise)

    assert scorer._call_api("prompt") is None


def test_malformed_envelope_returns_none(monkeypatch):
    monkeypatch.setattr(scorer, "urlopen", lambda *a, **k: _FakeResponse(b"not json"))

    assert scorer._call_api("prompt") is None


def test_successful_call_returns_parsed_verdict(monkeypatch):
    payload = _envelope(json.dumps(VALID_VERDICT))
    monkeypatch.setattr(scorer, "urlopen", lambda *a, **k: _FakeResponse(payload))

    assert scorer._call_api("prompt")["recommendation"] == "likely_match"


def test_model_is_configurable_per_call(monkeypatch):
    sent = {}

    def _capture(request, timeout=None):
        sent.update(json.loads(request.data.decode("utf-8")))
        return _FakeResponse(_envelope(json.dumps(VALID_VERDICT)))

    monkeypatch.setattr(scorer, "urlopen", _capture)
    scorer._call_api("prompt", model="gemma3:27b")

    assert sent["model"] == "gemma3:27b"
    assert sent["stream"] is False


# ── scoring ───────────────────────────────────────────────────────────────────

def test_score_candidate_attaches_work_identifiers(monkeypatch, faculty_with_orcid):
    monkeypatch.setattr(scorer, "_call_api", lambda *a, **k: dict(VALID_VERDICT))
    candidate = {"title": "A study", "doi": "10.1/a", "pmid": "123"}

    result = scorer.score_candidate(faculty_with_orcid, candidate)

    assert result["faculty_id"] == "fac-001"
    assert result["work_doi"] == "10.1/a"
    assert result["work_pmid"] == "123"
    assert result["work_title"] == "A study"


def test_score_candidate_returns_none_when_the_model_fails(monkeypatch, faculty_with_orcid):
    monkeypatch.setattr(scorer, "_call_api", lambda *a, **k: None)

    assert scorer.score_candidate(faculty_with_orcid, {"title": "A"}) is None


def test_low_confidence_is_flagged_for_human_review(monkeypatch, faculty_with_orcid):
    verdict = dict(VALID_VERDICT, confidence=scorer.HUMAN_REVIEW_CONFIDENCE - 0.01)
    monkeypatch.setattr(scorer, "_call_api", lambda *a, **k: dict(verdict))

    scores = scorer.score_batch(faculty_with_orcid, [{"title": "A"}])

    assert scores[0]["needs_human_review"] is True


def test_confidence_at_threshold_is_not_flagged(monkeypatch, faculty_with_orcid):
    verdict = dict(VALID_VERDICT, confidence=scorer.HUMAN_REVIEW_CONFIDENCE)
    monkeypatch.setattr(scorer, "_call_api", lambda *a, **k: dict(verdict))

    scores = scorer.score_batch(faculty_with_orcid, [{"title": "A"}])

    assert "needs_human_review" not in scores[0]


def test_failed_candidates_are_skipped_not_recorded(monkeypatch, faculty_with_orcid):
    responses = [dict(VALID_VERDICT), None, dict(VALID_VERDICT)]
    monkeypatch.setattr(scorer, "_call_api", lambda *a, **k: responses.pop(0))

    scores = scorer.score_batch(faculty_with_orcid, [{"title": t} for t in "ABC"])

    assert len(scores) == 2


def test_empty_candidate_list_scores_nothing(faculty_with_orcid):
    assert scorer.score_batch(faculty_with_orcid, []) == []


def test_known_publications_appear_in_the_prompt(faculty_with_orcid):
    known = [{"title": "Prior work on graphs"}]

    prompt = scorer._build_prompt(faculty_with_orcid, {"title": "New work"}, known)

    assert "Prior work on graphs" in prompt
    assert "New work" in prompt


def test_prompt_handles_absent_known_publications(faculty_with_orcid):
    prompt = scorer._build_prompt(faculty_with_orcid, {"title": "New work"}, [])

    assert "(none available)" in prompt


def test_save_scores_round_trips(tmp_path, faculty_with_orcid):
    output = tmp_path / "scores.json"

    scorer.save_scores([dict(VALID_VERDICT)], output)

    assert json.loads(output.read_text(encoding="utf-8"))[0]["confidence"] == 0.9
