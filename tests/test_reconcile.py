"""Reconciliation: linking records across sources.

Written from the property the phase exists to guarantee: a link is an explicit,
attributed, reversible assertion. Nothing here may silently fuse two records,
and every link must say what it was based on and how sure the pipeline is.
"""

import pytest

from src.rdf_model import converter
from src.rdf_model.organizations import build_organization
from src.reconcile.orgs import (
    CONFIDENCE_EXACT_NAME,
    build_organization_matches,
    index_by_name,
    is_ambiguous,
)
from src.reconcile.works import (
    MATCH_METHOD_DOI,
    MATCH_METHOD_PMID,
    MATCH_METHOD_TITLE,
    build_work_matches,
    group_match_method,
)
from src.reconcile.writer import build_reconciliation_turtle, write_reconciliation

rdflib = pytest.importorskip("rdflib", reason="rdflib parses the reconciliation graph")

FG = rdflib.Namespace(converter.FG_NAMESPACE)
OWL = rdflib.Namespace("http://www.w3.org/2002/07/owl#")

EX_ROR = "https://ror.org/abc123456"

LONG_TITLE = "A study of many different and quite distinctive things"


def publication(**overrides):
    """A minimally complete harvested record."""
    record = {"title": LONG_TITLE, "source": "PubMed", "assertion_status": "candidate"}
    record.update(overrides)
    return record


def parse(turtle):
    """Parse Turtle, failing the test if it is not well-formed."""
    graph = rdflib.Graph()
    graph.parse(data=turtle, format="turtle")
    return graph


def reconciliation_graph(publications, organizations=()):
    """Build and parse a reconciliation graph."""
    turtle, _, _ = build_reconciliation_turtle(publications, list(organizations))
    return parse(turtle)


class TestWorkMatching:
    def test_two_sources_sharing_a_doi_produce_a_link(self):
        matches = build_work_matches([
            publication(doi="10.1/x", source="PubMed"),
            publication(doi="10.1/x", source="OpenAlex"),
        ])
        assert len(matches) == 1
        assert matches[0]["sources"] == ["PubMed", "OpenAlex"]

    def test_a_doi_cased_differently_still_links(self):
        matches = build_work_matches([
            publication(doi="10.1/ABC", source="PubMed"),
            publication(doi="10.1/abc", source="OpenAlex"),
        ])
        assert len(matches) == 1

    def test_a_record_only_one_source_reported_produces_no_link(self):
        assert build_work_matches([publication(doi="10.1/x")]) == []

    def test_unrelated_records_produce_no_link(self):
        matches = build_work_matches([
            publication(doi="10.1/x", title="One distinctive title about things"),
            publication(doi="10.2/y", title="Another entirely separate title here"),
        ])
        assert matches == []

    def test_an_empty_harvest_produces_no_links(self):
        assert build_work_matches([]) == []

    def test_a_doi_link_is_fully_confident(self):
        matches = build_work_matches([
            publication(doi="10.1/x", source="PubMed"),
            publication(doi="10.1/x", source="OpenAlex"),
        ])
        assert matches[0]["method"] == MATCH_METHOD_DOI
        assert matches[0]["confidence"] == 1.0
        assert matches[0]["needs_review"] is False

    def test_a_title_only_link_is_flagged_for_review(self):
        matches = build_work_matches([
            publication(source="PubMed"),
            publication(source="OpenAlex"),
        ])
        assert matches[0]["method"] == MATCH_METHOD_TITLE
        assert matches[0]["confidence"] < 1.0
        assert matches[0]["needs_review"] is True

    def test_a_group_is_only_as_strong_as_the_key_that_joined_it(self):
        group = [
            publication(doi="10.1/x", source="PubMed"),
            publication(source="OpenAlex"),
        ]
        assert group_match_method(group) == MATCH_METHOD_TITLE

    def test_records_carrying_different_dois_are_not_a_doi_match(self):
        group = [
            publication(doi="10.1/x", source="PubMed"),
            publication(doi="10.2/y", source="OpenAlex"),
        ]
        assert group_match_method(group) == MATCH_METHOD_TITLE

    def test_a_shared_doi_outranks_a_shared_title(self):
        group = [
            publication(doi="10.1/x", source="PubMed"),
            publication(doi="10.1/x", source="OpenAlex"),
        ]
        assert group_match_method(group) == MATCH_METHOD_DOI

    def test_a_pmid_only_group_is_matched_on_pmid(self):
        group = [
            publication(pmid="123", source="PubMed"),
            publication(pmid="123", source="OpenAlex"),
        ]
        assert group_match_method(group) == MATCH_METHOD_PMID

    def test_three_sources_reporting_one_work_produce_one_link(self):
        matches = build_work_matches([
            publication(doi="10.1/x", source="PubMed"),
            publication(doi="10.1/x", source="OpenAlex"),
            publication(doi="10.1/x", source="ORCID"),
        ])
        assert len(matches) == 1
        assert len(matches[0]["members"]) == 3

    def test_scales_to_a_large_harvest(self):
        publications = []
        for index in range(2000):
            title = f"A distinctive study number {index} of assorted things"
            publications.append(
                publication(doi=f"10.1/{index}", title=title, source="PubMed")
            )
            publications.append(
                publication(doi=f"10.1/{index}", title=title, source="OpenAlex")
            )
        assert len(build_work_matches(publications)) == 2000

    def test_distinct_dois_sharing_one_title_are_treated_as_one_work(self):
        """Documents existing src/identity.py behaviour, which this phase inherits.

        A title long enough to be distinctive is a merge key, so two records with
        different DOIs but the same title join one group. That is right for two
        deposits of one article and wrong for two genuinely different works that
        happen to share a title; the link is flagged for review either way.
        """
        matches = build_work_matches([
            publication(doi="10.1/x", source="PubMed"),
            publication(doi="10.2/y", source="OpenAlex"),
        ])
        assert len(matches) == 1
        assert matches[0]["needs_review"] is True


class TestOrganizationMatching:
    def test_a_local_name_matches_the_registered_organization(self):
        matches = build_organization_matches([
            build_organization("Example University", ror=EX_ROR),
            build_organization("The Example University"),
        ])
        assert len(matches) == 1
        assert matches[0]["target"]["ror"] == EX_ROR
        assert matches[0]["confidence"] == CONFIDENCE_EXACT_NAME

    def test_an_organization_link_is_always_flagged_for_review(self):
        matches = build_organization_matches([
            build_organization("Example University", ror=EX_ROR),
            build_organization("example university"),
        ])
        assert matches[0]["needs_review"] is True

    def test_an_unmatched_local_organization_stays_local(self):
        matches = build_organization_matches([
            build_organization("Example University", ror=EX_ROR),
            build_organization("Nowhere Institute"),
        ])
        assert matches == []

    @pytest.mark.parametrize("generic", [
        "School of Medicine",
        "school of medicine",
        "Cancer Center",
        "Research Institute",
    ])
    def test_a_generic_name_is_never_matched(self, generic):
        assert is_ambiguous(generic)
        matches = build_organization_matches([
            build_organization(generic, ror=EX_ROR),
            build_organization(generic),
        ])
        assert matches == []

    def test_a_name_two_registered_organizations_claim_is_left_alone(self):
        matches = build_organization_matches([
            build_organization("Ambiguous University", ror=EX_ROR),
            build_organization("Ambiguous University", ror="https://ror.org/042nb2s44"),
            build_organization("ambiguous university"),
        ])
        assert matches == []

    def test_registered_organizations_are_not_matched_to_each_other(self):
        matches = build_organization_matches([
            build_organization("Example University", ror=EX_ROR),
            build_organization("Massachusetts Institute of Technology",
                               ror="https://ror.org/042nb2s44"),
        ])
        assert matches == []

    def test_index_ignores_organizations_with_no_registry_identity(self):
        index = index_by_name([build_organization("Local Only")])
        assert index == {}

    def test_no_organizations_is_harmless(self):
        assert build_organization_matches([]) == []


class TestReconciliationGraph:
    def test_a_confident_link_asserts_same_as(self):
        graph = reconciliation_graph([
            publication(doi="10.1/x", source="PubMed"),
            publication(doi="10.1/x", source="OpenAlex"),
        ])
        assert len(list(graph.triples((None, OWL.sameAs, None)))) == 2

    def test_an_uncertain_link_does_not_assert_same_as(self):
        graph = reconciliation_graph([
            publication(source="PubMed"),
            publication(source="OpenAlex"),
        ])
        assert list(graph.triples((None, OWL.sameAs, None))) == []

    def test_an_uncertain_link_is_still_recorded_for_review(self):
        graph = reconciliation_graph([
            publication(source="PubMed"),
            publication(source="OpenAlex"),
        ])
        flagged = list(graph.subjects(FG.needsHumanReview, rdflib.Literal(True)))
        assert len(flagged) == 2

    def test_every_link_records_its_method_and_confidence(self):
        graph = reconciliation_graph([
            publication(doi="10.1/x", source="PubMed"),
            publication(doi="10.1/x", source="OpenAlex"),
        ])
        for match in graph.subjects(rdflib.RDF.type, FG.MatchAssertion):
            assert graph.value(match, FG.matchMethod) is not None
            assert graph.value(match, FG.matchConfidence) is not None
            assert graph.value(match, FG.reconciledAt) is not None

    def test_a_link_names_the_source_it_came_from(self):
        graph = reconciliation_graph([
            publication(doi="10.1/x", source="PubMed"),
            publication(doi="10.1/x", source="OpenAlex"),
        ])
        sources = {str(o) for o in graph.objects(None, FG.source)}
        assert sources == {f"{converter.FG_NAMESPACE}PubMed",
                           f"{converter.FG_NAMESPACE}OpenAlex"}

    def test_the_graph_contains_only_links_not_restated_source_data(self):
        graph = reconciliation_graph([
            publication(doi="10.1/x", source="PubMed", journal="Journal of Testing"),
            publication(doi="10.1/x", source="OpenAlex"),
        ])
        assert list(graph.objects(None, FG.journal)) == []
        assert list(graph.objects(None, rdflib.URIRef(
            "http://purl.org/dc/terms/title"))) == []

    def test_an_organization_link_reaches_the_graph(self):
        graph = reconciliation_graph(
            [],
            [
                build_organization("Example University", ror=EX_ROR),
                build_organization("The Example University"),
            ],
        )
        matched_to = list(graph.objects(None, FG.matchedTo))
        assert rdflib.URIRef(EX_ROR) in matched_to

    def test_an_empty_harvest_still_produces_a_valid_graph(self):
        graph = reconciliation_graph([], [])
        assert list(graph.triples((None, rdflib.RDF.type, FG.MatchAssertion))) == []

    def test_a_hostile_source_name_cannot_inject_triples(self):
        graph = reconciliation_graph([
            publication(doi="10.1/x", source='PubMed> . <http://evil> <http://evil> <a'),
            publication(doi="10.1/x", source="OpenAlex"),
        ])
        assert rdflib.URIRef("http://evil") not in set(graph.predicates(None, None))

    def test_a_hostile_title_cannot_inject_triples(self):
        hostile = 'Study" ; fg:injected "yes'
        graph = reconciliation_graph([
            publication(title=hostile, source="PubMed"),
            publication(title=hostile, source="OpenAlex"),
        ])
        assert list(graph.objects(None, FG.injected)) == []


class TestWriter:
    def test_writes_the_reconciliation_file(self, tmp_path):
        path = write_reconciliation(
            [
                publication(doi="10.1/x", source="PubMed"),
                publication(doi="10.1/x", source="OpenAlex"),
            ],
            [],
            tmp_path,
        )
        assert path.name == "reconciliation.ttl"
        assert path.exists()
        parse(path.read_text(encoding="utf-8"))

    def test_the_links_file_is_separate_from_the_source_graphs(self, tmp_path):
        path = write_reconciliation([], [], tmp_path)
        assert path.parent == tmp_path
        assert not (tmp_path / "faculty-all.ttl").exists()


class TestReconcileStage:
    """The --reconcile stage, end to end over raw files on disk."""

    def _paths(self, tmp_path):
        return {
            "seed_csv": tmp_path / "faculty.csv",
            "raw_orcid": tmp_path / "raw" / "orcid",
            "raw_pubmed": tmp_path / "raw" / "pubmed",
            "raw_openalex": tmp_path / "raw" / "openalex",
            "raw_base": tmp_path / "raw",
            "rdf_output": tmp_path / "rdf",
        }

    def _write_harvest(self, paths):
        """Write one PubMed and one OpenAlex file describing the same DOI."""
        from tests import fixtures

        fixtures.write_text(
            paths["seed_csv"],
            fixtures.seed_csv([
                ("fac-001", "Ada Lovelace", "Psychoceramics", "", "ada@example.edu")
            ]),
        )
        fixtures.write_text(
            paths["raw_pubmed"] / "fac-001-name.xml",
            fixtures.pubmed_xml([{
                "title": LONG_TITLE,
                "pmid": "123",
                "article_ids": {"doi": "10.1234/shared"},
                "authors": [{"fore": "Ada", "last": "Lovelace"}],
            }]),
        )
        fixtures.write_json(
            paths["raw_openalex"] / "fac-001.json",
            fixtures.openalex_works([{
                "title": LONG_TITLE,
                "doi": "10.1234/shared",
                "authors": [{
                    "name": "Ada Lovelace",
                    "institutions": [{
                        "display_name": "Example University",
                        "ror": EX_ROR,
                    }],
                }],
            }]),
        )

    def test_links_the_same_work_across_two_sources(self, tmp_path):
        import main

        paths = self._paths(tmp_path)
        self._write_harvest(paths)

        path = main.run_reconcile(paths)
        assert path is not None

        graph = parse(path.read_text(encoding="utf-8"))
        matches = list(graph.subjects(rdflib.RDF.type, FG.MatchAssertion))
        assert len(matches) == 2

    def test_reports_nothing_when_no_harvest_exists(self, tmp_path):
        import main
        from tests import fixtures

        paths = self._paths(tmp_path)
        fixtures.write_text(
            paths["seed_csv"],
            fixtures.seed_csv([
                ("fac-001", "Ada Lovelace", "Psychoceramics", "", "ada@example.edu")
            ]),
        )
        assert main.run_reconcile(paths) is None

    def test_the_source_graphs_are_untouched_by_reconciliation(self, tmp_path):
        import main

        paths = self._paths(tmp_path)
        self._write_harvest(paths)
        main.run_reconcile(paths)

        written = sorted(p.name for p in paths["rdf_output"].iterdir())
        assert written == ["reconciliation.ttl"]
