"""ORCID harvest guards.

The seed CSV allows a blank orcid column, so harvest_all must skip those rows
before they reach the API. A blank iD would otherwise build the request URL
`/v3.0//works`, which is a wasted call at best and a mislabelled harvest at
worst.
"""

import json

import pytest

from src.harvest_orcid import client
from tests import fixtures


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """harvest_all sleeps between faculty; tests should not."""
    monkeypatch.setattr(client.time, "sleep", lambda seconds: None)


def _record_requests(monkeypatch, payload=None):
    """Capture every URL harvest_all requests, serving one canned works payload."""
    requested = []
    body = json.dumps(payload or fixtures.orcid_works([])).encode("utf-8")

    def _fake_urlopen(request, timeout=None):
        requested.append(request.full_url)
        return _FakeResponse(body)

    monkeypatch.setattr(client, "urlopen", _fake_urlopen)
    return requested


def test_blank_orcid_is_never_requested(monkeypatch, tmp_path, faculty_without_orcid):
    requested = _record_requests(monkeypatch)

    client.harvest_all([faculty_without_orcid], tmp_path)

    assert requested == []


def test_blank_orcid_writes_no_raw_file(monkeypatch, tmp_path, faculty_without_orcid):
    """A skipped person must not leave a raw file later runs would treat as data."""
    _record_requests(monkeypatch)

    client.harvest_all([faculty_without_orcid], tmp_path)

    assert list(tmp_path.glob("*.json")) == []


def test_blank_orcid_is_logged(monkeypatch, tmp_path, faculty_without_orcid, caplog):
    """Skipping silently would hide a seed row that needs an iD filled in."""
    _record_requests(monkeypatch)

    client.harvest_all([faculty_without_orcid], tmp_path)

    assert "Grace Hopper" in caplog.text
    assert "no ORCID ID" in caplog.text


@pytest.mark.parametrize("blank", ["", "   ", "\t"], ids=["empty", "spaces", "tab"])
def test_whitespace_only_orcid_is_treated_as_blank(monkeypatch, tmp_path, blank):
    faculty = {
        "faculty_id": "fac-002",
        "full_name": "Grace Hopper",
        "department": "Psychoceramics",
        "orcid": blank,
        "email": "grace@example.edu",
    }
    requested = _record_requests(monkeypatch)

    client.harvest_all([faculty], tmp_path)

    assert requested == []


def test_missing_orcid_key_is_treated_as_blank(monkeypatch, tmp_path):
    """A row dict built without the column must not raise a KeyError."""
    faculty = {"faculty_id": "fac-002", "full_name": "Grace Hopper"}
    requested = _record_requests(monkeypatch)

    results = client.harvest_all([faculty], tmp_path)

    assert requested == []
    assert results == [(faculty, [])]


def test_skipped_faculty_still_appears_in_results(monkeypatch, tmp_path, faculty_without_orcid):
    """Downstream stages zip results against the seed list; the row must survive."""
    _record_requests(monkeypatch)

    results = client.harvest_all([faculty_without_orcid], tmp_path)

    assert results == [(faculty_without_orcid, [])]


def test_populated_orcid_is_requested(monkeypatch, tmp_path, faculty_with_orcid):
    requested = _record_requests(
        monkeypatch, fixtures.orcid_works([{"title": "A", "doi": "10.1/a", "year": "2020"}])
    )

    results = client.harvest_all([faculty_with_orcid], tmp_path)

    assert requested == ["https://pub.orcid.org/v3.0/0000-0002-1825-0097/works"]
    assert results[0][1][0]["source"] == "ORCID"
    assert (tmp_path / "0000-0002-1825-0097.json").exists()


def test_blank_orcid_does_not_stop_the_run(monkeypatch, tmp_path, faculty_with_orcid,
                                           faculty_without_orcid):
    """One unharvestable row must not cost the rows after it."""
    requested = _record_requests(
        monkeypatch, fixtures.orcid_works([{"title": "A", "doi": "10.1/a", "year": "2020"}])
    )
    faculty_list = [faculty_without_orcid, faculty_with_orcid]

    results = client.harvest_all(faculty_list, tmp_path)

    assert len(requested) == 1
    assert results[0][1] == []
    assert len(results[1][1]) == 1
