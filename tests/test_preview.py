"""Static HTML previews.

Two invariants: the preview stage never writes into the raw harvest directory,
and remote strings are escaped before reaching the page.
"""

from collections import Counter
from html.parser import HTMLParser

import pytest

from src.consumers import preview
from tests import fixtures


def test_locates_orcid_by_id_and_openalex_by_faculty_id(raw_base, faculty_with_orcid):
    fixtures.write_json(
        raw_base / "orcid" / f"{faculty_with_orcid['orcid']}.json", fixtures.orcid_works([])
    )
    fixtures.write_json(raw_base / "openalex" / "fac-001.json", fixtures.openalex_works([]))

    located = preview._locate_raw_files(faculty_with_orcid, raw_base)

    assert located["orcid"].name == f"{faculty_with_orcid['orcid']}.json"
    assert located["openalex"].name == "fac-001.json"


def test_absent_sources_are_omitted(raw_base, faculty_with_orcid):
    assert preview._locate_raw_files(faculty_with_orcid, raw_base) == {}


def test_faculty_without_orcid_has_no_orcid_file(raw_base, faculty_without_orcid):
    located = preview._locate_raw_files(faculty_without_orcid, raw_base)

    assert "orcid" not in located


def test_publications_are_deduplicated_by_doi(raw_base, faculty_with_orcid):
    shared = {"title": "Shared work", "doi": "10.1/shared", "year": "2020"}
    fixtures.write_json(
        raw_base / "orcid" / f"{faculty_with_orcid['orcid']}.json",
        fixtures.orcid_works([shared]),
    )
    fixtures.write_json(
        raw_base / "openalex" / "fac-001.json",
        fixtures.openalex_works([{"title": "Shared work", "doi": "10.1/shared"}]),
    )

    publications = preview._load_faculty_publications(
        preview._locate_raw_files(faculty_with_orcid, raw_base)
    )

    assert len(publications) == 1


def test_publications_without_dois_are_all_kept(raw_base, faculty_with_orcid):
    fixtures.write_json(
        raw_base / "orcid" / f"{faculty_with_orcid['orcid']}.json",
        fixtures.orcid_works([{"title": "One"}, {"title": "Two"}]),
    )

    publications = preview._load_faculty_publications(
        preview._locate_raw_files(faculty_with_orcid, raw_base)
    )

    assert len(publications) == 2


def test_publications_are_sorted_newest_first(raw_base, faculty_with_orcid):
    fixtures.write_json(
        raw_base / "openalex" / "fac-001.json",
        fixtures.openalex_works([
            {"title": "Old", "doi": "10.1/a", "date": "2001-01-01"},
            {"title": "New", "doi": "10.1/b", "date": "2021-01-01"},
            {"title": "Undated", "doi": "10.1/c"},
        ]),
    )

    publications = preview._load_faculty_publications(
        preview._locate_raw_files(faculty_with_orcid, raw_base)
    )

    assert [p["title"] for p in publications] == ["New", "Old", "Undated"]


def test_malformed_raw_file_is_skipped_not_fatal(raw_base, faculty_with_orcid, caplog):
    fixtures.write_text(raw_base / "openalex" / "fac-001.json", "{ truncated")
    fixtures.write_json(
        raw_base / "orcid" / f"{faculty_with_orcid['orcid']}.json",
        fixtures.orcid_works([{"title": "Still here", "doi": "10.1/a"}]),
    )

    publications = preview._load_faculty_publications(
        preview._locate_raw_files(faculty_with_orcid, raw_base)
    )

    assert [p["title"] for p in publications] == ["Still here"]
    assert "Malformed raw" in caplog.text


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("<", "&lt;"),
        (">", "&gt;"),
        ("&", "&amp;"),
        ('"', "&quot;"),
        ("<script>", "&lt;script&gt;"),
        ("A & B", "A &amp; B"),
        ("&lt;", "&amp;lt;"),
        ("", ""),
    ],
)
def test_escape_html_encodes_every_markup_character(raw, expected):
    """Ampersand must be escaped first or the other escapes get double-encoded."""
    assert preview._escape_html(raw) == expected


def _count_tags(html):
    """Count the element start tags a browser would see in the document."""
    class _Counter(HTMLParser):
        def __init__(self):
            super().__init__()
            self.tags = []

        def handle_starttag(self, tag, attrs):
            self.tags.append(tag)

    counter = _Counter()
    counter.feed(html)
    return Counter(counter.tags)


@pytest.mark.parametrize(
    "hostile",
    [
        "<script>alert(1)</script>",
        'Title" onmouseover="alert(1)',
        "A & B",
        "<img src=x onerror=alert(1)>",
        "<<nested>>",
        "</td></tr><tr><td>injected",
    ],
)
def test_hostile_titles_cannot_introduce_elements(faculty_with_orcid, hostile):
    """Compare the parsed element census against a benign render."""
    benign = preview.generate_faculty_html(faculty_with_orcid, [{"title": "safe"}])
    attacked = preview.generate_faculty_html(faculty_with_orcid, [{"title": hostile}])

    assert _count_tags(attacked) == _count_tags(benign)
    assert "script" not in _count_tags(attacked)


def test_hostile_doi_cannot_break_out_of_the_link(faculty_with_orcid):
    hostile = '"><script>alert(1)</script>'
    benign = preview.generate_faculty_html(
        faculty_with_orcid, [{"title": "T", "doi": "10.1/a"}]
    )

    attacked = preview.generate_faculty_html(
        faculty_with_orcid, [{"title": "T", "doi": hostile}]
    )

    assert _count_tags(attacked) == _count_tags(benign)


def test_hostile_title_survives_as_readable_text(faculty_with_orcid):
    """Escaping must not silently drop the content it is protecting."""
    html = preview.generate_faculty_html(
        faculty_with_orcid, [{"title": "<script>alert(1)</script>"}]
    )

    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_empty_publication_list_renders_a_placeholder(faculty_with_orcid):
    html = preview.generate_faculty_html(faculty_with_orcid, [])

    assert "No publications found" in html
    assert "(0 total)" in html


def test_generate_all_previews_writes_one_page_per_faculty(
    tmp_path, raw_base, seed_file
):
    rows = [
        ("fac-001", "Ada Lovelace", "Psychoceramics", "0000-0002-1825-0097", "ada@example.edu"),
        ("fac-002", "Grace Hopper", "Psychoceramics", "", "grace@example.edu"),
    ]
    fixtures.write_json(
        raw_base / "orcid" / "0000-0002-1825-0097.json",
        fixtures.orcid_works([{"title": "A work", "doi": "10.1/a", "year": "2020"}]),
    )
    output_dir = tmp_path / "previews"

    preview.generate_all_previews(seed_file(rows), raw_base, output_dir)

    assert (output_dir / "fac-001.html").exists()
    assert (output_dir / "fac-002.html").exists()
    assert "A work" in (output_dir / "fac-001.html").read_text(encoding="utf-8")


def test_generate_all_previews_never_writes_into_raw(tmp_path, raw_base, seed_file):
    """Regression: the preview stage used to copy files into data/raw/orcid."""
    fixtures.write_json(
        raw_base / "orcid" / "0000-0002-1825-0097.json",
        fixtures.orcid_works([{"title": "A work", "doi": "10.1/a", "year": "2020"}]),
    )
    rows = [("fac-001", "Ada Lovelace", "Psychoceramics", "0000-0002-1825-0097", "ada@example.edu")]
    before = {p: p.stat().st_mtime_ns for p in raw_base.rglob("*") if p.is_file()}

    preview.generate_all_previews(seed_file(rows), raw_base, tmp_path / "previews")

    after = {p: p.stat().st_mtime_ns for p in raw_base.rglob("*") if p.is_file()}
    assert after == before, "preview must not write into the raw harvest directory"


def test_locates_both_pubmed_search_method_files(raw_base, faculty_with_orcid):
    fixtures.write_text(
        raw_base / "pubmed" / "fac-001-orcid.xml", fixtures.pubmed_xml([])
    )
    fixtures.write_text(
        raw_base / "pubmed" / "fac-001-name.xml", fixtures.pubmed_xml([])
    )

    located = preview._locate_raw_files(faculty_with_orcid, raw_base)

    assert located["pubmed:orcid"].name == "fac-001-orcid.xml"
    assert located["pubmed:name"].name == "fac-001-name.xml"


def test_pubmed_publications_reach_the_page_labelled_pubmed(
    raw_base, faculty_with_orcid
):
    """Regression: PubMed harvests were never read, so Source never said pubmed."""
    fixtures.write_text(
        raw_base / "pubmed" / "fac-001-orcid.xml",
        fixtures.pubmed_xml([
            {"title": "A PubMed work", "pmid": "111", "year": "2020"},
        ]),
    )

    publications = preview._load_faculty_publications(
        preview._locate_raw_files(faculty_with_orcid, raw_base)
    )

    assert [p["title"] for p in publications] == ["A PubMed work"]
    assert publications[0]["_sources"] == ["pubmed"]
    html = preview.generate_faculty_html(faculty_with_orcid, publications)
    assert "<td>pubmed</td>" in html


def test_same_record_from_both_pubmed_files_appears_once(
    raw_base, faculty_with_orcid
):
    """The ORCID and name searches overlap; PMID must dedupe them."""
    entry = {"title": "Overlapping work", "pmid": "222", "year": "2020"}
    fixtures.write_text(
        raw_base / "pubmed" / "fac-001-orcid.xml", fixtures.pubmed_xml([entry])
    )
    fixtures.write_text(
        raw_base / "pubmed" / "fac-001-name.xml", fixtures.pubmed_xml([entry])
    )

    publications = preview._load_faculty_publications(
        preview._locate_raw_files(faculty_with_orcid, raw_base)
    )

    assert len(publications) == 1


def test_malformed_pubmed_xml_is_skipped_not_fatal(
    raw_base, faculty_with_orcid, caplog
):
    fixtures.write_text(raw_base / "pubmed" / "fac-001-name.xml", "<PubmedArticleSet")
    fixtures.write_json(
        raw_base / "orcid" / f"{faculty_with_orcid['orcid']}.json",
        fixtures.orcid_works([{"title": "Still here", "doi": "10.1/a"}]),
    )

    publications = preview._load_faculty_publications(
        preview._locate_raw_files(faculty_with_orcid, raw_base)
    )

    assert [p["title"] for p in publications] == ["Still here"]
    assert "Failed to parse PubMed XML" in caplog.text


def test_same_doi_in_different_case_is_deduplicated(raw_base, faculty_with_orcid):
    """Regression: ORCID lowercases DOIs, PubMed and OpenAlex do not."""
    fixtures.write_json(
        raw_base / "orcid" / f"{faculty_with_orcid['orcid']}.json",
        fixtures.orcid_works([{"title": "Work", "doi": "10.1158/0008-5472.can-17-0316"}]),
    )
    fixtures.write_json(
        raw_base / "openalex" / "fac-001.json",
        fixtures.openalex_works([
            {"title": "Work", "doi": "10.1158/0008-5472.CAN-17-0316"},
        ]),
    )

    publications = preview._load_faculty_publications(
        preview._locate_raw_files(faculty_with_orcid, raw_base)
    )

    assert len(publications) == 1


def test_distinct_dois_are_not_collapsed(raw_base, faculty_with_orcid):
    """Normalization must not merge works that only look similar."""
    fixtures.write_json(
        raw_base / "orcid" / f"{faculty_with_orcid['orcid']}.json",
        fixtures.orcid_works([
            {"title": "One", "doi": "10.1/abc"},
            {"title": "Two", "doi": "10.1/abcd"},
        ]),
    )

    publications = preview._load_faculty_publications(
        preview._locate_raw_files(faculty_with_orcid, raw_base)
    )

    assert len(publications) == 2


def test_work_found_in_several_sources_lists_all_of_them(
    raw_base, faculty_with_orcid
):
    fixtures.write_json(
        raw_base / "orcid" / f"{faculty_with_orcid['orcid']}.json",
        fixtures.orcid_works([{"title": "Shared", "doi": "10.1/shared", "pmid": "555"}]),
    )
    fixtures.write_json(
        raw_base / "openalex" / "fac-001.json",
        fixtures.openalex_works([{"title": "Shared", "doi": "10.1/shared"}]),
    )
    fixtures.write_text(
        raw_base / "pubmed" / "fac-001-orcid.xml",
        fixtures.pubmed_xml([{"title": "Shared", "pmid": "555"}]),
    )

    publications = preview._load_faculty_publications(
        preview._locate_raw_files(faculty_with_orcid, raw_base)
    )

    assert len(publications) == 1
    assert publications[0]["_sources"] == ["orcid", "openalex", "pubmed"]
    html = preview.generate_faculty_html(faculty_with_orcid, publications)
    assert "<td>orcid, openalex, pubmed</td>" in html


def test_pmid_only_record_merges_into_the_work_matched_by_doi(
    raw_base, faculty_with_orcid
):
    """PubMed records often lack a DOI; the PMID must still link them."""
    fixtures.write_json(
        raw_base / "orcid" / f"{faculty_with_orcid['orcid']}.json",
        fixtures.orcid_works([{"title": "Shared", "doi": "10.1/shared", "pmid": "777"}]),
    )
    fixtures.write_text(
        raw_base / "pubmed" / "fac-001-name.xml",
        fixtures.pubmed_xml([{"title": "Shared", "pmid": "777"}]),
    )

    publications = preview._load_faculty_publications(
        preview._locate_raw_files(faculty_with_orcid, raw_base)
    )

    assert [p["_sources"] for p in publications] == [["orcid", "pubmed"]]


def test_a_source_reporting_a_work_twice_lists_it_once(raw_base, faculty_with_orcid):
    fixtures.write_json(
        raw_base / "orcid" / f"{faculty_with_orcid['orcid']}.json",
        fixtures.orcid_works([
            {"title": "Dup", "doi": "10.1/dup"},
            {"title": "Dup", "doi": "10.1/DUP"},
        ]),
    )

    publications = preview._load_faculty_publications(
        preview._locate_raw_files(faculty_with_orcid, raw_base)
    )

    assert [p["_sources"] for p in publications] == [["orcid"]]


def test_unidentified_publications_are_labelled_by_their_own_source(
    raw_base, faculty_with_orcid
):
    """Works with neither DOI nor PMID cannot merge, but must still be labelled."""
    fixtures.write_json(
        raw_base / "orcid" / f"{faculty_with_orcid['orcid']}.json",
        fixtures.orcid_works([{"title": "One"}, {"title": "Two"}]),
    )

    publications = preview._load_faculty_publications(
        preview._locate_raw_files(faculty_with_orcid, raw_base)
    )

    assert [p["_sources"] for p in publications] == [["orcid"], ["orcid"]]
