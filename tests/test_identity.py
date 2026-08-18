"""Deciding when two harvested records describe the same work.

The rules must collapse the variants real sources produce without merging works
that merely look alike, and they must be reproducible: identical input always
yields identical grouping, whatever order the harvesters ran in.
"""

import pytest

from src import identity

CONTAINERIZED = (
    "A Containerized Software System for Generation, Management, "
    "and Exploration of Features from Whole Slide Tissue Images"
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("10.1158/0008-5472.CAN-17-0316", "10.1158/0008-5472.can-17-0316"),
        ("https://doi.org/10.1/A", "10.1/a"),
        ("http://doi.org/10.1/A", "10.1/a"),
        ("doi:10.1/A", "10.1/a"),
        ("  10.1/a  ", "10.1/a"),
        ("10.1/a/", "10.1/a"),
        ("10.1158/0008-5472.22418981.v1", "10.1158/0008-5472.22418981"),
        ("10.1158/0008-5472.c.6510269.v12", "10.1158/0008-5472.c.6510269"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalize_doi_reduces_sources_to_one_comparable_form(raw, expected):
    assert identity.normalize_doi(raw) == expected


def test_version_suffix_is_only_stripped_from_the_end():
    """A DOI whose body contains .v1 must keep it."""
    assert identity.normalize_doi("10.1/a.v1.b") == "10.1/a.v1.b"


@pytest.mark.parametrize(
    "variant",
    [
        CONTAINERIZED,
        f"Data from {CONTAINERIZED}",
        CONTAINERIZED.replace("Management, and", "Management and"),
        f"{CONTAINERIZED}.",
        CONTAINERIZED.upper(),
        f"  {CONTAINERIZED}  ",
    ],
)
def test_real_title_variants_share_one_key(variant):
    assert identity.title_key(variant) == identity.title_key(CONTAINERIZED)


def test_distinct_titles_do_not_share_a_key():
    assert identity.title_key(CONTAINERIZED) != identity.title_key(
        "Hierarchical nucleus segmentation in digital pathology images"
    )


@pytest.mark.parametrize(
    "short_title",
    ["Erratum", "Introduction", "Correction to earlier work", "", None],
)
def test_short_titles_are_too_generic_to_merge_on(short_title):
    assert identity.title_key(short_title) == ""


def test_short_titles_never_merge_unrelated_works():
    groups = identity.group_publications([
        {"title": "Erratum", "source": "orcid"},
        {"title": "Erratum", "source": "openalex"},
    ])

    assert len(groups) == 2


def test_records_without_any_identifier_stay_separate():
    groups = identity.group_publications([
        {"title": "", "source": "orcid"},
        {"title": "", "source": "openalex"},
    ])

    assert len(groups) == 2


def test_figshare_deposits_merge_into_the_article():
    """The exact duplicate set OpenAlex returns for the Containerized paper."""
    harvested = [
        {
            "title": CONTAINERIZED,
            "doi": "10.1158/0008-5472.can-17-0316",
            "type": "article",
            "source": "ORCID",
        },
        {
            "title": f"Data from {CONTAINERIZED}",
            "doi": "10.1158/0008-5472.c.6510269.v1",
            "type": "other",
            "source": "OpenAlex",
        },
        {
            "title": CONTAINERIZED.replace("Management, and", "Management and"),
            "doi": "10.1158/0008-5472.22418981.v1",
            "type": "other",
            "source": "OpenAlex",
        },
        {
            "title": CONTAINERIZED.replace("Management, and", "Management and"),
            "doi": "10.1158/0008-5472.22418981",
            "type": "other",
            "source": "OpenAlex",
        },
        {
            "title": f"Data from {CONTAINERIZED}",
            "doi": "10.1158/0008-5472.c.6510269",
            "type": "other",
            "source": "OpenAlex",
        },
    ]

    merged = identity.merge_publications(harvested)

    assert len(merged) == 1
    assert merged[0]["doi"] == "10.1158/0008-5472.can-17-0316"
    assert merged[0]["type"] == "article"
    assert merged[0]["_sources"] == ["ORCID", "OpenAlex"]


def test_deposit_dois_are_kept_as_alternates():
    """Deposit DOIs are citable, so merging must not throw them away."""
    merged = identity.merge_publications([
        {"title": CONTAINERIZED, "doi": "10.1/article", "type": "article"},
        {
            "title": f"Data from {CONTAINERIZED}",
            "doi": "10.1158/0008-5472.c.6510269.v1",
            "type": "other",
        },
    ])

    assert merged[0]["alternate_dois"] == ["10.1158/0008-5472.c.6510269.v1"]


def test_alternate_pmids_are_kept():
    merged = identity.merge_publications([
        {"title": CONTAINERIZED, "doi": "10.1/a", "pmid": "111"},
        {"title": CONTAINERIZED, "doi": "10.1/a", "pmid": "222"},
    ])

    assert merged[0]["pmid"] == "111"
    assert merged[0]["alternate_pmids"] == ["222"]


def test_the_article_wins_over_the_deposit_whatever_the_harvest_order():
    """Grouping must not depend on which harvester ran first."""
    article = {"title": CONTAINERIZED, "doi": "10.1/article", "type": "article"}
    deposit = {
        "title": f"Data from {CONTAINERIZED}",
        "doi": "10.1/deposit",
        "type": "other",
    }

    forward = identity.merge_publications([article, deposit])
    reverse = identity.merge_publications([deposit, article])

    assert forward[0]["doi"] == reverse[0]["doi"] == "10.1/article"


def test_two_deposits_break_their_tie_deterministically():
    first = {"title": CONTAINERIZED, "doi": "10.1/zzz", "type": "other"}
    second = {"title": CONTAINERIZED, "doi": "10.1/aaa", "type": "other"}

    forward = identity.merge_publications([first, second])
    reverse = identity.merge_publications([second, first])

    assert forward[0]["doi"] == reverse[0]["doi"] == "10.1/aaa"


def test_a_pmid_only_record_joins_the_work_a_doi_established():
    merged = identity.merge_publications([
        {"title": "Some work", "doi": "10.1/a", "pmid": "999", "source": "ORCID"},
        {"title": "Some work", "pmid": "999", "source": "PubMed"},
    ])

    assert len(merged) == 1
    assert merged[0]["_sources"] == ["ORCID", "PubMed"]


def test_different_works_are_not_merged():
    merged = identity.merge_publications([
        {"title": CONTAINERIZED, "doi": "10.1/a"},
        {"title": "Hierarchical nucleus segmentation in digital pathology images",
         "doi": "10.1/b"},
    ])

    assert len(merged) == 2


def test_merging_does_not_mutate_the_harvested_records():
    """Raw parsed records are reused by other stages, so merge must copy."""
    original = {"title": CONTAINERIZED, "doi": "10.1/a", "type": "article"}
    deposit = {"title": f"Data from {CONTAINERIZED}", "doi": "10.1/b", "type": "other"}

    identity.merge_publications([original, deposit])

    assert "alternate_dois" not in original
    assert "_sources" not in original


def test_empty_input_yields_no_works():
    assert identity.merge_publications([]) == []


DOUBLED = (
    CONTAINERIZED.replace("Management, and", "Management and")
    + " from "
    + CONTAINERIZED
)


def test_a_title_concatenated_onto_itself_matches_the_single_copy():
    """OpenAlex titles one AACR deposit as "<title> from <title>"."""
    assert identity.title_key(DOUBLED) == identity.title_key(CONTAINERIZED)


def test_a_plainly_doubled_title_matches_the_single_copy():
    assert identity.title_key(f"{CONTAINERIZED} {CONTAINERIZED}") == identity.title_key(
        CONTAINERIZED
    )


def test_a_title_that_merely_contains_from_is_left_alone():
    """"from" is an ordinary word; only a true repeat may collapse."""
    title = "Mapping Sub-cellular Morphology from Whole Slide Tissue Images"

    assert identity.title_key(title) == identity.normalize_title(title)
    assert "whole slide tissue images" in identity.title_key(title)


def test_distinct_halves_around_from_are_not_collapsed():
    title = "Generation and Management of Radiomics Datasets from Whole Slide Tissue Images"

    assert identity.title_key(title) == identity.normalize_title(title)


def test_the_full_openalex_duplicate_set_collapses_to_one_work():
    """Every Containerized variant OpenAlex actually returns, verbatim."""
    harvested = [
        {"title": CONTAINERIZED, "doi": "10.1158/0008-5472.can-17-0316",
         "type": "article", "source": "ORCID"},
        {"title": f"Data from {CONTAINERIZED}",
         "doi": "10.1158/0008-5472.c.6510269.v1", "type": "other", "source": "OpenAlex"},
        {"title": DOUBLED, "doi": "10.1158/0008-5472.22418981.v1",
         "type": "other", "source": "OpenAlex"},
        {"title": DOUBLED, "doi": "10.1158/0008-5472.22418981",
         "type": "other", "source": "OpenAlex"},
        {"title": f"Data from {CONTAINERIZED}",
         "doi": "10.1158/0008-5472.c.6510269", "type": "other", "source": "OpenAlex"},
    ]

    merged = identity.merge_publications(harvested)

    assert len(merged) == 1
    assert merged[0]["title"] == CONTAINERIZED
    assert len(merged[0]["alternate_dois"]) == 4


def test_merged_work_takes_a_journal_the_primary_record_lacks():
    """ORCID reported no journal for years; the merge must not lose PubMed's."""
    merged = identity.merge_publications([
        {"title": CONTAINERIZED, "doi": "10.1/a", "source": "ORCID", "journal": None},
        {"title": CONTAINERIZED, "doi": "10.1/a", "source": "PubMed",
         "journal": "Journal of pathology informatics"},
    ])

    assert merged[0]["journal"] == "Journal of pathology informatics"


def test_openalex_supplies_the_rendered_journal_name():
    """Sources disagree on case; OpenAlex carries the journal's display name."""
    merged = identity.merge_publications([
        {"title": CONTAINERIZED, "doi": "10.1/a", "source": "ORCID",
         "journal": "Journal of pathology informatics"},
        {"title": CONTAINERIZED, "doi": "10.1/a", "source": "OpenAlex",
         "journal": "Journal of Pathology Informatics"},
    ])

    assert merged[0]["journal"] == "Journal of Pathology Informatics"


def test_journal_preference_does_not_depend_on_harvest_order():
    orcid = {"title": CONTAINERIZED, "doi": "10.1/a", "source": "ORCID",
             "journal": "Journal of pathology informatics"}
    openalex = {"title": CONTAINERIZED, "doi": "10.1/a", "source": "OpenAlex",
                "journal": "Journal of Pathology Informatics"}

    forward = identity.merge_publications([orcid, openalex])
    reverse = identity.merge_publications([openalex, orcid])

    assert forward[0]["journal"] == reverse[0]["journal"]


@pytest.mark.parametrize("aggregator", ["PubMed", "pubmed", "OpenAlex", "Crossref", ""])
def test_an_aggregator_name_is_not_accepted_as_a_journal(aggregator):
    """OpenAlex names the index it harvested from as the container title."""
    assert not identity.is_usable_journal(aggregator)


def test_a_real_journal_beats_an_aggregator_name():
    merged = identity.merge_publications([
        {"title": CONTAINERIZED, "doi": "10.1/a", "source": "OpenAlex",
         "journal": "PubMed"},
        {"title": CONTAINERIZED, "doi": "10.1/a", "source": "PubMed",
         "journal": "AMIA Joint Summits on Translational Science proceedings"},
    ])

    assert merged[0]["journal"] == "AMIA Joint Summits on Translational Science proceedings"


def test_a_work_no_source_gave_a_journal_keeps_none():
    merged = identity.merge_publications([
        {"title": CONTAINERIZED, "doi": "10.1/a", "source": "ORCID"},
        {"title": CONTAINERIZED, "doi": "10.1/a", "source": "OpenAlex", "journal": ""},
    ])

    assert not merged[0].get("journal")


def test_gap_filling_never_overwrites_a_value_the_primary_supplied():
    merged = identity.merge_publications([
        {"title": CONTAINERIZED, "doi": "10.1/a", "type": "article",
         "date": "2017-10-31", "source": "ORCID"},
        {"title": f"Data from {CONTAINERIZED}", "doi": "10.1/b", "type": "other",
         "date": "2023-03-31", "source": "OpenAlex"},
    ])

    assert merged[0]["date"] == "2017-10-31"
    assert merged[0]["type"] == "article"


def test_gap_filling_does_not_borrow_identifiers():
    """Only descriptive fields fill; a deposit's DOI must stay an alternate."""
    merged = identity.merge_publications([
        {"title": CONTAINERIZED, "pmid": "123", "type": "article", "source": "PubMed"},
        {"title": f"Data from {CONTAINERIZED}", "pmid": "123", "doi": "10.1/b",
         "type": "other", "source": "OpenAlex"},
    ])

    assert merged[0].get("doi") is None
    assert merged[0]["alternate_dois"] == ["10.1/b"]


def test_a_record_with_a_doi_is_preferred_over_one_without():
    merged = identity.merge_publications([
        {"title": CONTAINERIZED, "pmid": "123", "source": "PubMed"},
        {"title": CONTAINERIZED, "pmid": "123", "doi": "10.1/b", "source": "OpenAlex"},
    ])

    assert merged[0]["doi"] == "10.1/b"
