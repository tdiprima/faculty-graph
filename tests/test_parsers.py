"""Tests for what the source parsers keep.

These are written against the requirement that no field a source supplied is
dropped at the parser boundary: structured names stay split, affiliations stay
attached to the author who claimed them, and bibliographic detail survives.
"""

from src.harvest_openalex.parser import parse_works as parse_openalex_works
from src.harvest_pubmed.parser import parse_pubmed_xml
from src.names import DISPLAY, STRUCTURED
from tests import fixtures


def _one_pubmed(entry):
    """Parse a single-entry PubMed document and return the publication."""
    publications = parse_pubmed_xml(fixtures.pubmed_xml([entry]))
    assert len(publications) == 1
    return publications[0]


def _one_openalex(entry):
    """Parse a single-entry OpenAlex response and return the publication."""
    publications = parse_openalex_works(fixtures.openalex_works([entry]))
    assert len(publications) == 1
    return publications[0]


class TestPubMedNames:
    def test_keeps_family_and_given_names_apart(self):
        publication = _one_pubmed({
            "title": "A study",
            "authors": [{"fore": "Ada", "last": "Lovelace"}],
        })
        author = publication["coauthors"][0]
        assert author["family_name"] == "Lovelace"
        assert author["given_name"] == "Ada"
        assert author["name_source"] == STRUCTURED

    def test_still_exposes_joined_names_for_display(self):
        publication = _one_pubmed({
            "title": "A study",
            "authors": [{"fore": "Ada", "last": "Lovelace"}],
        })
        assert publication["authors"] == ["Ada Lovelace"]

    def test_keeps_an_author_who_has_no_given_name(self):
        publication = _one_pubmed({
            "title": "A study",
            "authors": [{"fore": "", "last": "Lovelace"}],
        })
        author = publication["coauthors"][0]
        assert author["family_name"] == "Lovelace"
        assert author["given_name"] is None
        assert author["name"] == "Lovelace"

    def test_skips_an_author_with_no_family_name(self):
        publication = _one_pubmed({
            "title": "A study",
            "authors": [{"fore": "Ada", "last": ""}],
        })
        assert publication["coauthors"] == []

    def test_records_author_order(self):
        publication = _one_pubmed({
            "title": "A study",
            "authors": [
                {"fore": "Ada", "last": "Lovelace"},
                {"fore": "Alan", "last": "Turing"},
            ],
        })
        assert [a["position"] for a in publication["coauthors"]] == [1, 2]


class TestPubMedAffiliations:
    def test_keeps_each_affiliation_string_verbatim(self):
        publication = _one_pubmed({
            "title": "A study",
            "authors": [{
                "fore": "Ada",
                "last": "Lovelace",
                "affiliations": [
                    "Department of Computing, Example University, NY, USA",
                    "Massachusetts Institute of Technology, Cambridge, MA, USA",
                ],
            }],
        })
        assert publication["coauthors"][0]["affiliations"] == [
            "Department of Computing, Example University, NY, USA",
            "Massachusetts Institute of Technology, Cambridge, MA, USA",
        ]

    def test_author_with_no_affiliation_gets_an_empty_list(self):
        publication = _one_pubmed({
            "title": "A study",
            "authors": [{"fore": "Ada", "last": "Lovelace"}],
        })
        assert publication["coauthors"][0]["affiliations"] == []

    def test_deduplicates_a_repeated_affiliation(self):
        publication = _one_pubmed({
            "title": "A study",
            "authors": [{
                "fore": "Ada",
                "last": "Lovelace",
                "affiliations": ["Example University", "Example University"],
            }],
        })
        assert publication["coauthors"][0]["affiliations"] == ["Example University"]

    def test_reads_an_author_orcid(self):
        publication = _one_pubmed({
            "title": "A study",
            "authors": [{
                "fore": "Ada",
                "last": "Lovelace",
                "orcid": "https://orcid.org/0000-0002-1825-0097",
            }],
        })
        assert publication["coauthors"][0]["orcid"] == "0000-0002-1825-0097"


class TestPubMedBibliography:
    def test_keeps_volume_issue_pages_and_issn(self):
        publication = _one_pubmed({
            "title": "A study",
            "journal": "Journal of Testing",
            "issn": "1234-5678",
            "volume": "12",
            "issue": "3",
            "pages": "100-115",
        })
        assert publication["volume"] == "12"
        assert publication["issue"] == "3"
        assert publication["pages"] == "100-115"
        assert publication["issn"] == "1234-5678"

    def test_missing_bibliographic_fields_are_none_not_absent(self):
        publication = _one_pubmed({"title": "A study"})
        assert publication["volume"] is None
        assert publication["issue"] is None
        assert publication["pages"] is None
        assert publication["issn"] is None


class TestOpenAlexAuthors:
    def test_marks_a_split_display_name_as_inferred(self):
        publication = _one_openalex({
            "title": "A study",
            "authors": [{"name": "Ada Lovelace"}],
        })
        author = publication["coauthors"][0]
        assert author["given_name"] == "Ada"
        assert author["family_name"] == "Lovelace"
        assert author["name_source"] == DISPLAY

    def test_records_position_and_corresponding_flag(self):
        publication = _one_openalex({
            "title": "A study",
            "authors": [
                {"name": "Ada Lovelace"},
                {"name": "Alan Turing", "is_corresponding": True},
            ],
        })
        first, second = publication["coauthors"]
        assert first["position"] == 1
        assert first["is_corresponding"] is False
        assert second["position"] == 2
        assert second["is_corresponding"] is True


class TestOpenAlexInstitutions:
    def test_keeps_the_ror_identifier(self):
        publication = _one_openalex({
            "title": "A study",
            "authors": [{
                "name": "Ada Lovelace",
                "institutions": [{
                    "display_name": "Example University",
                    "ror": "https://ror.org/abc123456",
                    "country_code": "US",
                    "type": "education",
                }],
            }],
        })
        institution = publication["coauthors"][0]["institutions"][0]
        assert institution["display_name"] == "Example University"
        assert institution["ror"] == "https://ror.org/abc123456"
        assert institution["country_code"] == "US"

    def test_keeps_an_institution_that_has_no_ror(self):
        publication = _one_openalex({
            "title": "A study",
            "authors": [{"name": "Ada Lovelace", "institutions": ["Some Institute"]}],
        })
        institution = publication["coauthors"][0]["institutions"][0]
        assert institution["display_name"] == "Some Institute"
        assert institution["ror"] is None

    def test_keeps_every_institution_on_a_multi_affiliated_author(self):
        publication = _one_openalex({
            "title": "A study",
            "authors": [{
                "name": "Ada Lovelace",
                "institutions": ["Example University", "MIT"],
            }],
        })
        names = [i["display_name"] for i in publication["coauthors"][0]["institutions"]]
        assert names == ["Example University", "MIT"]

    def test_drops_an_institution_with_no_display_name(self):
        publication = _one_openalex({
            "title": "A study",
            "authors": [{"name": "Ada Lovelace", "institutions": [{"ror": "x"}]}],
        })
        assert publication["coauthors"][0]["institutions"] == []


class TestOpenAlexBibliography:
    def test_builds_a_page_range_from_first_and_last_page(self):
        publication = _one_openalex({
            "title": "A study",
            "volume": "12",
            "issue": "3",
            "first_page": "100",
            "last_page": "115",
        })
        assert publication["volume"] == "12"
        assert publication["issue"] == "3"
        assert publication["pages"] == "100-115"

    def test_collapses_a_single_page_range(self):
        publication = _one_openalex({
            "title": "A study",
            "first_page": "100",
            "last_page": "100",
        })
        assert publication["pages"] == "100"

    def test_keeps_a_first_page_with_no_last_page(self):
        publication = _one_openalex({"title": "A study", "first_page": "100"})
        assert publication["pages"] == "100"

    def test_keeps_the_linking_issn(self):
        publication = _one_openalex({
            "title": "A study",
            "journal": "Journal of Testing",
            "issn": "1234-5678",
        })
        assert publication["issn"] == "1234-5678"

    def test_absent_biblio_block_yields_none(self):
        publication = _one_openalex({"title": "A study"})
        assert publication["volume"] is None
        assert publication["pages"] is None
