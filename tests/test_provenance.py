"""Provenance tagging: the rules that decide authoritative vs candidate."""

import pytest

from src.provenance import (
    SEARCH_METHOD_NAME,
    SEARCH_METHOD_ORCID,
    STATUS_AUTHORITATIVE,
    STATUS_CANDIDATE,
    search_method_for_faculty,
    status_for_search_method,
    tag_publications,
)


def test_orcid_search_is_authoritative():
    assert status_for_search_method(SEARCH_METHOD_ORCID) == STATUS_AUTHORITATIVE


def test_name_search_is_candidate():
    assert status_for_search_method(SEARCH_METHOD_NAME) == STATUS_CANDIDATE


@pytest.mark.parametrize("bad_method", ["", None, "ORCID", "fulltext", 0])
def test_unknown_search_method_is_rejected(bad_method):
    with pytest.raises(ValueError):
        status_for_search_method(bad_method)


@pytest.mark.parametrize("orcid_value", ["0000-0002-1825-0097", "  0000-0002-1825-0097  "])
def test_faculty_with_orcid_uses_orcid_search(orcid_value):
    faculty = {"orcid": orcid_value}
    assert search_method_for_faculty(faculty) == SEARCH_METHOD_ORCID


@pytest.mark.parametrize("orcid_value", ["", "   ", None])
def test_faculty_without_orcid_falls_back_to_name_search(orcid_value):
    faculty = {"orcid": orcid_value} if orcid_value is not None else {}
    assert search_method_for_faculty(faculty) == SEARCH_METHOD_NAME


def test_tag_publications_stamps_every_record():
    publications = [{"title": "A"}, {"title": "B"}]

    tagged = tag_publications(publications, "OpenAlex", SEARCH_METHOD_NAME)

    assert tagged is publications, "tagging is documented as in-place"
    for publication in tagged:
        assert publication["source"] == "OpenAlex"
        assert publication["assertion_status"] == STATUS_CANDIDATE
        assert publication["search_method"] == SEARCH_METHOD_NAME


def test_tag_publications_accepts_empty_list():
    assert tag_publications([], "ORCID", SEARCH_METHOD_ORCID) == []


def test_tag_publications_rejects_unknown_method_before_mutating():
    publications = [{"title": "A"}]

    with pytest.raises(ValueError):
        tag_publications(publications, "ORCID", "guess")

    assert "assertion_status" not in publications[0]
