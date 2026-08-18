"""Offline reload of raw harvest files for disambiguation.

Raw files do not record assertion status, so the loader re-derives it. A drift
between these rules and the harvest clients' would silently send zero
candidates to the LLM, which is exactly what the shipped pipeline did.
"""

from src.disambiguate import loader
from src.provenance import STATUS_AUTHORITATIVE, STATUS_CANDIDATE
from tests import fixtures


def test_known_works_load_from_the_orcid_id_filename(raw_base, faculty_with_orcid):
    fixtures.write_json(
        raw_base / "orcid" / f"{faculty_with_orcid['orcid']}.json",
        fixtures.orcid_works([{"title": "Prior work", "doi": "10.1/a", "year": "2020"}]),
    )

    known = loader.load_known_works(faculty_with_orcid, raw_base / "orcid")

    assert [work["title"] for work in known] == ["Prior work"]
    assert known[0]["assertion_status"] == STATUS_AUTHORITATIVE


def test_faculty_without_orcid_has_no_known_works(raw_base, faculty_without_orcid):
    assert loader.load_known_works(faculty_without_orcid, raw_base / "orcid") == []


def test_missing_orcid_file_yields_no_known_works(raw_base, faculty_with_orcid):
    assert loader.load_known_works(faculty_with_orcid, raw_base / "orcid") == []


def test_malformed_orcid_json_is_reported_not_raised(raw_base, faculty_with_orcid, caplog):
    fixtures.write_text(
        raw_base / "orcid" / f"{faculty_with_orcid['orcid']}.json", "{ truncated"
    )

    assert loader.load_known_works(faculty_with_orcid, raw_base / "orcid") == []
    assert "Malformed JSON" in caplog.text


def test_pubmed_name_search_files_are_candidates(raw_base, faculty_with_orcid):
    """Regression: these are .xml, and the old glob only matched .json."""
    fixtures.write_text(
        raw_base / "pubmed" / "bmi-001-name.xml",
        fixtures.pubmed_xml([{"title": "Maybe theirs", "pmid": "1", "year": "2021"}]),
    )

    publications = loader.load_pubmed_publications(faculty_with_orcid, raw_base / "pubmed")

    assert [p["assertion_status"] for p in publications] == [STATUS_CANDIDATE]


def test_pubmed_orcid_search_files_are_authoritative(raw_base, faculty_with_orcid):
    fixtures.write_text(
        raw_base / "pubmed" / "bmi-001-orcid.xml",
        fixtures.pubmed_xml([{"title": "Definitely theirs", "pmid": "2", "year": "2021"}]),
    )

    publications = loader.load_pubmed_publications(faculty_with_orcid, raw_base / "pubmed")

    assert [p["assertion_status"] for p in publications] == [STATUS_AUTHORITATIVE]


def test_both_pubmed_search_methods_load_together(raw_base, faculty_with_orcid):
    fixtures.write_text(
        raw_base / "pubmed" / "bmi-001-orcid.xml",
        fixtures.pubmed_xml([{"title": "Sure", "pmid": "1", "year": "2021"}]),
    )
    fixtures.write_text(
        raw_base / "pubmed" / "bmi-001-name.xml",
        fixtures.pubmed_xml([{"title": "Maybe", "pmid": "2", "year": "2021"}]),
    )

    publications = loader.load_pubmed_publications(faculty_with_orcid, raw_base / "pubmed")

    statuses = sorted(p["assertion_status"] for p in publications)
    assert statuses == [STATUS_AUTHORITATIVE, STATUS_CANDIDATE]


def test_openalex_is_authoritative_when_the_faculty_has_an_orcid(raw_base, faculty_with_orcid):
    fixtures.write_json(
        raw_base / "openalex" / "bmi-001.json",
        fixtures.openalex_works([{"title": "Work", "doi": "10.1/a", "date": "2020-01-01"}]),
    )

    publications = loader.load_openalex_publications(faculty_with_orcid, raw_base / "openalex")

    assert [p["assertion_status"] for p in publications] == [STATUS_AUTHORITATIVE]


def test_openalex_is_candidate_without_an_orcid(raw_base, faculty_without_orcid):
    fixtures.write_json(
        raw_base / "openalex" / "bmi-002.json",
        fixtures.openalex_works([{"title": "Work", "doi": "10.1/a", "date": "2020-01-01"}]),
    )

    publications = loader.load_openalex_publications(faculty_without_orcid, raw_base / "openalex")

    assert [p["assertion_status"] for p in publications] == [STATUS_CANDIDATE]


def test_load_candidates_returns_only_candidates(raw_base, faculty_with_orcid):
    fixtures.write_text(
        raw_base / "pubmed" / "bmi-001-orcid.xml",
        fixtures.pubmed_xml([{"title": "Authoritative", "pmid": "1", "year": "2021"}]),
    )
    fixtures.write_text(
        raw_base / "pubmed" / "bmi-001-name.xml",
        fixtures.pubmed_xml([{"title": "Candidate", "pmid": "2", "year": "2021"}]),
    )
    fixtures.write_json(
        raw_base / "openalex" / "bmi-001.json",
        fixtures.openalex_works([{"title": "Also authoritative", "doi": "10.1/a"}]),
    )

    candidates = loader.load_candidates(
        faculty_with_orcid, raw_base / "pubmed", raw_base / "openalex"
    )

    assert [c["title"] for c in candidates] == ["Candidate"]


def test_load_candidates_finds_candidates_from_both_sources(raw_base, faculty_without_orcid):
    fixtures.write_text(
        raw_base / "pubmed" / "bmi-002-name.xml",
        fixtures.pubmed_xml([{"title": "From PubMed", "pmid": "1", "year": "2021"}]),
    )
    fixtures.write_json(
        raw_base / "openalex" / "bmi-002.json",
        fixtures.openalex_works([{"title": "From OpenAlex", "doi": "10.1/a"}]),
    )

    candidates = loader.load_candidates(
        faculty_without_orcid, raw_base / "pubmed", raw_base / "openalex"
    )

    assert sorted(c["title"] for c in candidates) == ["From OpenAlex", "From PubMed"]


def test_no_raw_files_yields_no_candidates(raw_base, faculty_with_orcid):
    assert loader.load_candidates(
        faculty_with_orcid, raw_base / "pubmed", raw_base / "openalex"
    ) == []


def test_empty_result_sets_yield_no_candidates(raw_base, faculty_without_orcid):
    fixtures.write_json(raw_base / "openalex" / "bmi-002.json", fixtures.openalex_works([]))
    fixtures.write_text(raw_base / "pubmed" / "bmi-002-name.xml", fixtures.pubmed_xml([]))

    assert loader.load_candidates(
        faculty_without_orcid, raw_base / "pubmed", raw_base / "openalex"
    ) == []


def test_loading_does_not_write_into_the_raw_directory(raw_base, faculty_with_orcid):
    """Raw harvest data is the source of truth and must stay read-only."""
    fixtures.write_json(
        raw_base / "openalex" / "bmi-001.json",
        fixtures.openalex_works([{"title": "Work", "doi": "10.1/a"}]),
    )
    before = {p: p.stat().st_mtime_ns for p in raw_base.rglob("*") if p.is_file()}

    loader.load_candidates(faculty_with_orcid, raw_base / "pubmed", raw_base / "openalex")

    after = {p: p.stat().st_mtime_ns for p in raw_base.rglob("*") if p.is_file()}
    assert after == before
