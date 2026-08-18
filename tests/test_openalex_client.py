"""OpenAlex pagination.

A cursor walk that stops early must fail loudly. Returning the pages it managed
to fetch would write a truncated result set into the graph as authoritative.
"""

import json
from urllib.error import HTTPError, URLError
from urllib.parse import unquote_plus

import pytest

from src.errors import HarvestError
from src.harvest_openalex import client
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


def _page(entries, next_cursor=None):
    return json.dumps(fixtures.openalex_works(entries, next_cursor)).encode("utf-8")


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """Pagination sleeps between pages; tests should not."""
    monkeypatch.setattr(client.time, "sleep", lambda seconds: None)


def _serve(monkeypatch, pages):
    """Serve queued pages, then raise if the walk asks for more than expected."""
    queue = list(pages)
    requested = []

    def _fake_urlopen(request, timeout=None):
        requested.append(request.full_url)
        if not queue:
            raise AssertionError("cursor walk requested more pages than expected")
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return _FakeResponse(item)

    monkeypatch.setattr(client, "urlopen", _fake_urlopen)
    return requested


def test_single_page_walk_returns_all_results(monkeypatch):
    _serve(monkeypatch, [_page([{"title": "A", "doi": "10.1/a"}])])

    data = client.fetch_works_by_orcid("0000-0002-1825-0097")

    assert [work["title"] for work in data["results"]] == ["A"]


def test_multi_page_walk_concatenates_pages(monkeypatch):
    _serve(monkeypatch, [
        _page([{"title": "A", "doi": "10.1/a"}], next_cursor="cursor-2"),
        _page([{"title": "B", "doi": "10.1/b"}], next_cursor="cursor-3"),
        _page([{"title": "C", "doi": "10.1/c"}]),
    ])

    data = client.fetch_works_by_orcid("0000-0002-1825-0097")

    assert [work["title"] for work in data["results"]] == ["A", "B", "C"]


def test_walk_stops_when_a_page_comes_back_empty(monkeypatch):
    _serve(monkeypatch, [
        _page([{"title": "A", "doi": "10.1/a"}], next_cursor="cursor-2"),
        _page([], next_cursor="cursor-3"),
    ])

    data = client.fetch_works_by_orcid("0000-0002-1825-0097")

    assert len(data["results"]) == 1


@pytest.mark.parametrize(
    "error",
    [
        HTTPError("http://api.openalex.org", 429, "Too Many Requests", {}, None),
        URLError("connection reset"),
        TimeoutError("timed out"),
    ],
    ids=["http_error", "url_error", "timeout"],
)
def test_failure_midwalk_raises_instead_of_returning_partial_data(monkeypatch, error):
    """Regression: this used to `break` and return page one as a complete harvest."""
    _serve(monkeypatch, [
        _page([{"title": "A", "doi": "10.1/a"}], next_cursor="cursor-2"),
        error,
    ])

    with pytest.raises(HarvestError):
        client.fetch_works_by_orcid("0000-0002-1825-0097")


def test_malformed_json_raises(monkeypatch):
    _serve(monkeypatch, [b"{ truncated"])

    with pytest.raises(HarvestError, match="malformed JSON"):
        client.fetch_works_by_orcid("0000-0002-1825-0097")


def test_runaway_cursor_is_bounded(monkeypatch):
    """A next_cursor that never clears must not spin forever."""
    def _always_more(request, timeout=None):
        return _FakeResponse(_page([{"title": "A", "doi": "10.1/a"}], next_cursor="again"))

    monkeypatch.setattr(client, "urlopen", _always_more)

    with pytest.raises(HarvestError, match="exceeded"):
        client.fetch_works_by_orcid("0000-0002-1825-0097")


def test_polite_email_is_sent_when_configured(monkeypatch):
    monkeypatch.setenv("OPENALEX_EMAIL", "ada@example.edu")
    requested = _serve(monkeypatch, [_page([])])

    client.fetch_works_by_orcid("0000-0002-1825-0097")

    assert "mailto=ada%40example.edu" in requested[0]


def test_polite_email_is_omitted_when_unset(monkeypatch):
    monkeypatch.delenv("OPENALEX_EMAIL", raising=False)
    requested = _serve(monkeypatch, [_page([])])

    client.fetch_works_by_orcid("0000-0002-1825-0097")

    assert "mailto" not in requested[0]


def test_harvest_failure_is_contained_to_one_faculty_member(
    monkeypatch, tmp_path, faculty_with_orcid, caplog
):
    """One person's failed harvest must not abort the run for everyone else."""
    _serve(monkeypatch, [URLError("connection reset")])

    publications = client.harvest_faculty(faculty_with_orcid, tmp_path)

    assert publications == []
    assert "OpenAlex harvest failed" in caplog.text


def test_failed_harvest_writes_no_raw_file(monkeypatch, tmp_path, faculty_with_orcid):
    """A truncated harvest must not leave a raw file later runs would trust."""
    _serve(monkeypatch, [URLError("connection reset")])

    client.harvest_faculty(faculty_with_orcid, tmp_path)

    assert list(tmp_path.glob("*.json")) == []


def test_successful_harvest_tags_and_saves(monkeypatch, tmp_path, faculty_with_orcid):
    _serve(monkeypatch, [_page([{"title": "A", "doi": "10.1/a", "date": "2020-01-01"}])])

    publications = client.harvest_faculty(faculty_with_orcid, tmp_path)

    assert publications[0]["source"] == "OpenAlex"
    assert publications[0]["assertion_status"] == "authoritative"
    assert (tmp_path / "fac-001.json").exists()


def test_faculty_without_orcid_is_harvested_by_name(monkeypatch, tmp_path, faculty_without_orcid):
    requested = _serve(monkeypatch, [_page([{"title": "A", "doi": "10.1/a"}])])

    publications = client.harvest_faculty(faculty_without_orcid, tmp_path)

    assert "display_name.search" in requested[0]
    assert publications[0]["assertion_status"] == "candidate"


def test_name_search_is_constrained_to_the_institution(monkeypatch, tmp_path,
                                                       faculty_without_orcid):
    """Without the institution filter, 'Grace Hopper' pulls in every namesake."""
    monkeypatch.setenv("INSTITUTION_NAME", "Example University")
    requested = _serve(monkeypatch, [_page([{"title": "A", "doi": "10.1/a"}])])

    client.harvest_faculty(faculty_without_orcid, tmp_path)

    query = unquote_plus(requested[0])
    assert "authorships.author.display_name.search:Grace Hopper" in query
    assert "authorships.institutions.display_name.search:Example University" in query


def test_name_search_skips_the_institution_filter_when_unset(monkeypatch):
    """An empty INSTITUTION_NAME means search every institution, not literal ''."""
    monkeypatch.setenv("INSTITUTION_NAME", "")
    requested = _serve(monkeypatch, [_page([])])

    client.fetch_works_by_name("Grace Hopper")

    query = unquote_plus(requested[0])
    assert "authorships.institutions" not in query


def test_name_and_institution_are_anded_in_one_filter(monkeypatch):
    """OpenAlex ANDs comma-separated terms only within a single filter param."""
    monkeypatch.setenv("INSTITUTION_NAME", "Example University")
    requested = _serve(monkeypatch, [_page([])])

    client.fetch_works_by_name("Grace Hopper")

    query = unquote_plus(requested[0])
    filter_value = query.split("filter=", 1)[1].split("&", 1)[0]
    assert filter_value.count("authorships.") == 2
    assert query.count("filter=") == 1


def test_name_search_institution_is_overridable(monkeypatch):
    monkeypatch.setenv("INSTITUTION_NAME", "Example University")
    requested = _serve(monkeypatch, [_page([])])

    client.fetch_works_by_name("Grace Hopper", institution="Other University")

    assert "Other University" in unquote_plus(requested[0])
    assert "Example University" not in unquote_plus(requested[0])


def test_orcid_search_is_not_institution_constrained(monkeypatch, tmp_path,
                                                     faculty_with_orcid):
    """An iD is authoritative; filtering it by affiliation would drop prior work."""
    requested = _serve(monkeypatch, [_page([{"title": "A", "doi": "10.1/a"}])])

    client.harvest_faculty(faculty_with_orcid, tmp_path)

    query = unquote_plus(requested[0])
    assert "author.orcid:https://orcid.org/0000-0002-1825-0097" in query
    assert "institutions.display_name" not in query
