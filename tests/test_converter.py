"""RDF generation.

Every test that produces Turtle parses it. Output that looks right but does not
parse is the failure mode this suite exists to prevent: the pipeline shipped
`fgdata:faculty/fac-004`, which is not a legal Turtle prefixed name, and no
triple store would load it.
"""

import pathlib

import pytest

from src.rdf_model import converter

rdflib = pytest.importorskip("rdflib", reason="rdflib parses the generated Turtle")


FACULTY = {
    "faculty_id": "fac-001",
    "full_name": "Ada Lovelace",
    "department": "Psychoceramics",
    "orcid": "0000-0002-1825-0097",
    "email": "ada@example.edu",
}


def parse(turtle):
    """Parse Turtle into a graph, failing the test if it is not well-formed."""
    graph = rdflib.Graph()
    graph.parse(data=turtle, format="turtle")
    return graph


def render(publications, faculty=FACULTY):
    """Render a faculty member's publications as a complete Turtle document."""
    body = converter.convert_faculty_to_rdf(faculty, publications, "2026-01-01T00:00:00")
    return converter.PREFIXES + "\n" + body


def publication(**overrides):
    """A minimally complete publication record."""
    record = {
        "title": "A study of things",
        "source": "OpenAlex",
        "assertion_status": "candidate",
    }
    record.update(overrides)
    return record


# ── URI construction ──────────────────────────────────────────────────────────

def test_faculty_uri_is_an_absolute_iri():
    """Regression: a prefixed name cannot contain an unescaped slash."""
    uri = converter.build_faculty_uri("fac-001")

    assert uri == "<http://example.org/faculty-graph/data/faculty/fac-001>"


@pytest.mark.parametrize(
    "record",
    [
        {"doi": "10.1234/abc.def", "title": "T"},
        {"pmid": "12345678", "title": "T"},
        {"title": "Title only, no identifiers"},
    ],
    ids=["by_doi", "by_pmid", "by_title"],
)
def test_work_uris_are_absolute_iris(record):
    uri = converter.build_work_uri(record)

    assert uri.startswith("<http://example.org/faculty-graph/data/work/")
    assert uri.endswith(">")


def test_doi_is_preferred_over_pmid_for_work_identity():
    both = converter.build_work_uri({"doi": "10.1/a", "pmid": "9", "title": "T"})
    doi_only = converter.build_work_uri({"doi": "10.1/a", "title": "Different title"})

    assert both == doi_only


def test_assertions_from_different_sources_stay_distinct():
    """One work asserted by two sources must yield two assertion URIs."""
    record = publication(doi="10.1/a")

    orcid_uri = converter.build_assertion_uri("fac-001", "ORCID", record)
    openalex_uri = converter.build_assertion_uri("fac-001", "OpenAlex", record)

    assert orcid_uri != openalex_uri


def test_assertions_for_different_faculty_stay_distinct():
    record = publication(doi="10.1/a")

    assert converter.build_assertion_uri("fac-001", "ORCID", record) != \
           converter.build_assertion_uri("fac-002", "ORCID", record)


@pytest.mark.parametrize(
    "unsafe",
    ["10.1234/a b", "10.1234/a#b", "10.1234/a?b=c", "10.1234/<>", "10.1234/a\\b", "10.1234/ä"],
)
def test_unsafe_identifier_characters_are_sanitized(unsafe):
    turtle = render([publication(doi=unsafe)])

    parse(turtle)


# ── document validity ─────────────────────────────────────────────────────────

def test_minimal_document_parses():
    graph = parse(render([publication()]))

    assert len(graph) > 0


def test_faculty_block_parses_and_carries_expected_triples():
    graph = parse(render([]))
    subject = rdflib.URIRef("http://example.org/faculty-graph/data/faculty/fac-001")
    foaf_name = rdflib.URIRef("http://xmlns.com/foaf/0.1/name")

    assert (subject, foaf_name, rdflib.Literal("Ada Lovelace")) in graph


def test_fully_populated_publication_parses():
    record = publication(
        doi="10.1234/abc.def",
        pmid="12345678",
        type="journal-article",
        date="2020-03-04",
        journal="Journal of Tests",
        openalex_id="W123",
        cited_by_count=7,
        external_ids={"doi": "10.1234/abc.def", "pmcid": "PMC999", "mag": "42"},
        coauthors=[
            {"name": "Grace Hopper", "orcid": "0000-0001-0000-0000"},
            {"name": "Alan Turing", "orcid": None},
        ],
        search_method="orcid",
    )

    graph = parse(render([record]))

    assert len(graph) > 10


@pytest.mark.parametrize(
    "title",
    [
        'Title with "quotes"',
        "Title with \\ backslash",
        "Title with\nnewline",
        "Title with\r\ncarriage return",
        "Title ending in a semicolon;",
        "Title with a . period",
        "Title with émojis 🧬 and ünicode",
        "Title with <angle> brackets",
        'Nasty" ;\n fg:injected "value',
    ],
)
def test_hostile_titles_are_escaped(title):
    """A title is remote data; it must never break out of its literal."""
    graph = parse(render([publication(title=title, doi="10.1/a")]))
    dcterms_title = rdflib.URIRef("http://purl.org/dc/terms/title")

    assert rdflib.Literal(title) in set(graph.objects(None, dcterms_title))


def test_injected_predicate_does_not_become_a_triple():
    hostile = 'x" ; <http://example.org/evil> "pwned'

    graph = parse(render([publication(title=hostile, doi="10.1/a")]))

    assert (None, rdflib.URIRef("http://example.org/evil"), None) not in graph


@pytest.mark.parametrize(
    "date,expected_suffix",
    [
        ("2020", "gYear"),
        ("2020-03", "gYearMonth"),
        ("2020-03-04", "date"),
    ],
)
def test_dates_are_typed_by_precision(date, expected_suffix):
    graph = parse(render([publication(date=date, doi="10.1/a")]))
    dcterms_date = rdflib.URIRef("http://purl.org/dc/terms/date")
    literal = next(iter(graph.objects(None, dcterms_date)))

    assert str(literal.datatype).endswith(expected_suffix)


def test_missing_date_emits_no_date_triple():
    graph = parse(render([publication(doi="10.1/a")]))
    dcterms_date = rdflib.URIRef("http://purl.org/dc/terms/date")

    assert list(graph.objects(None, dcterms_date)) == []


def test_repeated_work_is_described_once_but_asserted_twice():
    """Two sources reporting one work share a work node and add two assertions."""
    record = publication(doi="10.1/shared")
    turtle = render([
        dict(record, source="ORCID", assertion_status="authoritative"),
        dict(record, source="OpenAlex"),
    ])

    graph = parse(turtle)
    assertion_type = rdflib.URIRef("http://example.org/faculty-graph/PublicationAssertion")
    article_type = rdflib.URIRef("http://purl.org/ontology/bibo/AcademicArticle")

    assert len(list(graph.subjects(None, assertion_type))) == 2
    assert len(list(graph.subjects(None, article_type))) == 1


def test_coauthors_are_linked_to_the_work():
    record = publication(doi="10.1/a", coauthors=[{"name": "Grace Hopper"}])

    graph = parse(render([record]))
    dcterms_creator = rdflib.URIRef("http://purl.org/dc/terms/creator")

    assert len(list(graph.objects(None, dcterms_creator))) == 1


def test_empty_publication_list_still_produces_a_valid_document():
    graph = parse(render([]))

    assert len(graph) > 0


def test_large_batch_parses():
    records = [publication(doi=f"10.1/{n}", title=f"Study {n}") for n in range(500)]

    graph = parse(render(records))

    assert len(graph) > 500


# ── file output ───────────────────────────────────────────────────────────────

def test_convert_all_writes_per_faculty_and_combined_files(tmp_path):
    results = [(FACULTY, [publication(doi="10.1/a")])]

    combined = converter.convert_all_to_rdf(results, tmp_path)

    assert (tmp_path / "fac-001.ttl").exists()
    assert combined.name == "faculty-all.ttl"
    parse((tmp_path / "fac-001.ttl").read_text(encoding="utf-8"))
    parse(combined.read_text(encoding="utf-8"))


def test_combined_file_matches_the_name_the_loader_scripts_expect(tmp_path):
    """scripts/load_graph_*.sh read faculty-all.ttl; the name is a contract."""
    combined = converter.convert_all_to_rdf([(FACULTY, [])], tmp_path)

    assert combined.name == "faculty-all.ttl"


def test_publications_from_repeated_faculty_entries_are_merged(tmp_path):
    """Each harvester returns its own (faculty, publications) tuple."""
    results = [
        (FACULTY, [publication(doi="10.1/a", source="ORCID")]),
        (FACULTY, [publication(doi="10.1/b", source="OpenAlex")]),
    ]

    converter.convert_all_to_rdf(results, tmp_path)

    graph = parse((tmp_path / "fac-001.ttl").read_text(encoding="utf-8"))
    article_type = rdflib.URIRef("http://purl.org/ontology/bibo/AcademicArticle")
    assert len(list(graph.subjects(None, article_type))) == 2


# ── checked-in reference model ────────────────────────────────────────────────

def test_reference_model_parses():
    """data/output/rdf/example.ttl is the documented data model.

    It is hand-written, so nothing else would catch it drifting out of valid
    Turtle -- which is exactly what happened to it once already.
    """
    example = pathlib.Path(__file__).resolve().parent.parent / "data/output/rdf/example.ttl"
    if not example.exists():
        pytest.skip("reference model not present in this checkout")

    graph = parse(example.read_text(encoding="utf-8"))

    assert len(graph) > 0


def test_reference_model_uses_the_same_faculty_iri_as_the_generator():
    """The reference and the generator must describe the same node."""
    example = pathlib.Path(__file__).resolve().parent.parent / "data/output/rdf/example.ttl"
    if not example.exists():
        pytest.skip("reference model not present in this checkout")

    graph = parse(example.read_text(encoding="utf-8"))
    generated = converter.build_faculty_uri("fac-001").strip("<>")

    assert (rdflib.URIRef(generated), None, None) in graph


CONTAINERIZED = (
    "A Containerized Software System for Generation, Management, "
    "and Exploration of Features from Whole Slide Tissue Images"
)

FG = rdflib.Namespace(converter.FG_NAMESPACE)
BIBO = rdflib.Namespace("http://purl.org/ontology/bibo/")


def works_in(graph):
    """Return every subject that carries a title, i.e. every fg:Work node."""
    return set(graph.subjects(rdflib.DCTERMS.title, None))


def test_duplicate_records_produce_one_work_node():
    """Regression: figshare deposits minted a separate fg:Work per DOI."""
    turtle = render([
        publication(title=CONTAINERIZED, doi="10.1158/0008-5472.can-17-0316",
                    type="article", source="ORCID"),
        publication(title=f"Data from {CONTAINERIZED}",
                    doi="10.1158/0008-5472.c.6510269.v1", type="other"),
        publication(title=CONTAINERIZED.replace("Management, and", "Management and"),
                    doi="10.1158/0008-5472.22418981.v1", type="other"),
        publication(title=CONTAINERIZED.replace("Management, and", "Management and"),
                    doi="10.1158/0008-5472.22418981", type="other"),
        publication(title=f"Data from {CONTAINERIZED}",
                    doi="10.1158/0008-5472.c.6510269", type="other"),
    ])

    graph = parse(turtle)

    assert len(works_in(graph)) == 1
    titles = list(graph.objects(None, rdflib.DCTERMS.title))
    assert str(titles[0]) == CONTAINERIZED


def test_the_surviving_work_carries_the_published_doi():
    turtle = render([
        publication(title=f"Data from {CONTAINERIZED}", doi="10.1/deposit", type="other"),
        publication(title=CONTAINERIZED, doi="10.1/article", type="article"),
    ])

    graph = parse(turtle)

    dois = {str(o) for o in graph.objects(None, BIBO.doi)}
    assert dois == {"10.1/article"}


def test_deposit_dois_survive_as_external_identifiers():
    """Merging must not silently delete citable identifiers from the graph."""
    turtle = render([
        publication(title=CONTAINERIZED, doi="10.1/article", type="article"),
        publication(title=f"Data from {CONTAINERIZED}", doi="10.1/deposit", type="other"),
    ])

    graph = parse(turtle)

    id_values = {str(o) for o in graph.objects(None, FG.idValue)}
    assert "10.1/deposit" in id_values


def test_every_source_keeps_its_own_assertion_after_merging():
    """The merge removes duplicate works, never provenance."""
    turtle = render([
        publication(title=CONTAINERIZED, doi="10.1/a", pmid="123", source="ORCID"),
        publication(title=CONTAINERIZED, pmid="123", source="PubMed"),
        publication(title=CONTAINERIZED, doi="10.1/A", source="OpenAlex"),
    ])

    graph = parse(turtle)
    assertions = set(graph.subjects(rdflib.RDF.type, FG.PublicationAssertion))

    assert len(works_in(graph)) == 1
    assert len(assertions) == 3


def test_merged_assertions_all_point_at_the_surviving_work():
    turtle = render([
        publication(title=CONTAINERIZED, doi="10.1/a", type="article", source="ORCID"),
        publication(title=f"Data from {CONTAINERIZED}", doi="10.1/b",
                    type="other", source="OpenAlex"),
    ])

    graph = parse(turtle)
    referenced_works = set(graph.objects(None, FG.work))

    assert referenced_works == works_in(graph)


def test_doi_case_alone_does_not_split_a_work():
    """DOIs are case-insensitive; ORCID lowercases them and PubMed does not."""
    turtle = render([
        publication(title="A study of things", doi="10.1158/0008-5472.CAN-17-0316",
                    source="PubMed"),
        publication(title="A study of things", doi="10.1158/0008-5472.can-17-0316",
                    source="ORCID"),
    ])

    graph = parse(turtle)

    assert len(works_in(graph)) == 1


def test_unrelated_works_are_still_separate_nodes():
    turtle = render([
        publication(title=CONTAINERIZED, doi="10.1/a"),
        publication(title="Hierarchical nucleus segmentation in digital pathology images",
                    doi="10.1/b"),
    ])

    graph = parse(turtle)

    assert len(works_in(graph)) == 2


# ── Phase 1: bibliographic detail and author name parts ──


BIBO = rdflib.Namespace("http://purl.org/ontology/bibo/")
FOAF = rdflib.Namespace("http://xmlns.com/foaf/0.1/")


def objects_for(graph, predicate):
    """Return every object asserted with this predicate, as strings."""
    return sorted(str(o) for o in graph.objects(None, predicate))


def test_volume_issue_and_issn_reach_the_graph():
    graph = parse(render([publication(
        journal="Journal of Testing",
        issn="1234-5678",
        volume="12",
        issue="3",
    )]))
    assert objects_for(graph, BIBO.volume) == ["12"]
    assert objects_for(graph, BIBO.issue) == ["3"]
    assert objects_for(graph, BIBO.issn) == ["1234-5678"]


def test_page_range_emits_printed_form_and_endpoints():
    graph = parse(render([publication(pages="100-115")]))
    assert objects_for(graph, BIBO.pages) == ["100-115"]
    assert objects_for(graph, BIBO.pageStart) == ["100"]
    assert objects_for(graph, BIBO.pageEnd) == ["115"]


def test_single_page_emits_no_endpoints():
    graph = parse(render([publication(pages="e1000")]))
    assert objects_for(graph, BIBO.pages) == ["e1000"]
    assert objects_for(graph, BIBO.pageStart) == []


def test_missing_bibliographic_fields_emit_no_triples():
    graph = parse(render([publication()]))
    assert objects_for(graph, BIBO.volume) == []
    assert objects_for(graph, BIBO.pages) == []


@pytest.mark.parametrize("hostile", [
    'v1" ; fg:injected "yes',
    "12\\",
    'x" .\n<http://evil> <http://evil> "',
])
def test_hostile_bibliographic_values_are_escaped(hostile):
    graph = parse(render([publication(volume=hostile, pages=hostile)]))
    assert objects_for(graph, BIBO.volume) == [hostile]


def test_author_name_parts_are_emitted_separately():
    graph = parse(render([publication(coauthors=[{
        "name": "Ada Lovelace",
        "given_name": "Ada",
        "family_name": "Lovelace",
        "name_source": "structured",
    }])]))
    assert objects_for(graph, FOAF.givenName) == ["Ada"]
    assert objects_for(graph, FOAF.familyName) == ["Lovelace"]
    assert "Ada Lovelace" in objects_for(graph, FOAF.name)


def test_an_unsplit_name_emits_no_name_part_triples():
    graph = parse(render([publication(coauthors=[{
        "name": "Prince",
        "given_name": None,
        "family_name": None,
        "name_source": "display",
    }])]))
    assert objects_for(graph, FOAF.givenName) == []
    assert objects_for(graph, FOAF.familyName) == []
    assert "Prince" in objects_for(graph, FOAF.name)


def test_institution_with_a_ror_id_reaches_the_graph():
    turtle = render([publication(coauthors=[{
        "name": "Ada Lovelace",
        "institutions": [{
            "display_name": "Example University",
            "ror": "https://ror.org/abc123456",
            "country_code": "US",
        }],
    }])])
    graph = parse(turtle)
    ror_id = rdflib.URIRef(f"{converter.FG_NAMESPACE}rorId")
    org_name = rdflib.URIRef(f"{converter.FG_NAMESPACE}orgName")
    assert objects_for(graph, ror_id) == ["https://ror.org/abc123456"]
    assert objects_for(graph, org_name) == ["Example University"]


def test_institution_without_a_ror_id_still_records_its_name():
    turtle = render([publication(coauthors=[{
        "name": "Ada Lovelace",
        "institutions": [{"display_name": "Some Institute", "ror": None}],
    }])])
    graph = parse(turtle)
    ror_id = rdflib.URIRef(f"{converter.FG_NAMESPACE}rorId")
    org_name = rdflib.URIRef(f"{converter.FG_NAMESPACE}orgName")
    assert objects_for(graph, org_name) == ["Some Institute"]
    assert objects_for(graph, ror_id) == []


def test_raw_pubmed_affiliation_is_kept_verbatim():
    affiliation = "Department of Computing, Example University, NY, USA"
    turtle = render([publication(coauthors=[{
        "name": "Ada Lovelace",
        "affiliations": [affiliation],
    }])])
    graph = parse(turtle)
    affiliation_raw = rdflib.URIRef(f"{converter.FG_NAMESPACE}affiliationRaw")
    assert objects_for(graph, affiliation_raw) == [affiliation]


def test_a_coauthor_with_no_affiliation_still_parses():
    graph = parse(render([publication(coauthors=[{"name": "Ada Lovelace"}])]))
    assert "Ada Lovelace" in objects_for(graph, FOAF.name)


def test_hostile_affiliation_string_is_escaped():
    hostile = 'MIT" ; fg:injected "yes'
    graph = parse(render([publication(coauthors=[{
        "name": "Ada Lovelace",
        "affiliations": [hostile],
    }])]))
    injected = rdflib.URIRef(f"{converter.FG_NAMESPACE}injected")
    assert list(graph.objects(None, injected)) == []
