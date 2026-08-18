"""The shipped SPARQL queries run, and answer what they claim to answer.

A query that parses but returns nothing against real generated output is worse
than a broken one, because nobody notices. Each query here runs against Turtle
this pipeline actually produces.
"""

import pathlib

import pytest

from src.rdf_model import converter

rdflib = pytest.importorskip("rdflib", reason="rdflib runs the shipped queries")

QUERIES_DIR = pathlib.Path(__file__).resolve().parent.parent / "queries"

EX_ROR = "https://ror.org/abc123456"
MIT_ROR = "https://ror.org/042nb2s44"

FACULTY = {
    "faculty_id": "fac-001",
    "full_name": "Ada Lovelace",
    "department": "Psychoceramics",
    "orcid": "0000-0002-1825-0097",
    "email": "ada@example.edu",
}


def load_query(name):
    """Read one shipped query file."""
    return (QUERIES_DIR / name).read_text(encoding="utf-8")


def collaboration_graph(status="candidate"):
    """Build a graph with one EX/MIT co-authored work."""
    publication = {
        "title": "A jointly authored study of things",
        "doi": "10.1234/joint",
        "source": "OpenAlex",
        "assertion_status": status,
        "coauthors": [
            {
                "name": "Ada Lovelace",
                "position": 1,
                "institutions": [
                    {"display_name": "Example University", "ror": EX_ROR}
                ],
            },
            {
                "name": "Alan Turing",
                "position": 2,
                "institutions": [
                    {
                        "display_name": "Massachusetts Institute of Technology",
                        "ror": MIT_ROR,
                    }
                ],
            },
        ],
    }
    body = converter.convert_faculty_to_rdf(
        FACULTY, [publication], "2026-01-01T00:00:00"
    )
    graph = rdflib.Graph()
    graph.parse(data=converter.PREFIXES + "\n" + body, format="turtle")
    return graph


@pytest.mark.parametrize(
    "query_file", sorted(path.name for path in QUERIES_DIR.glob("*.rq"))
)
def test_every_shipped_query_is_valid_sparql(query_file):
    rdflib.Graph().query(load_query(query_file))


class TestCollaboratingInstitutions:
    def test_finds_the_outside_institution(self):
        results = list(collaboration_graph().query(
            load_query("collaborating-institutions.rq")
        ))
        partners = {str(row.partner_name): int(row.shared_works) for row in results}
        assert partners == {"Massachusetts Institute of Technology": 1}

    def test_does_not_report_our_own_institution_as_a_partner(self):
        results = list(collaboration_graph().query(
            load_query("collaborating-institutions.rq")
        ))
        assert "Example University" not in {str(row.partner_name) for row in results}

    def test_a_rejected_work_is_not_counted(self):
        results = list(collaboration_graph(status="rejected").query(
            load_query("collaborating-institutions.rq")
        ))
        assert results == []

    def test_a_work_with_no_outside_institution_yields_no_collaboration(self):
        publication = {
            "title": "A single institution study of things",
            "doi": "10.1234/solo",
            "source": "OpenAlex",
            "assertion_status": "candidate",
            "coauthors": [{
                "name": "Ada Lovelace",
                "position": 1,
                "institutions": [
                    {"display_name": "Example University", "ror": EX_ROR}
                ],
            }],
        }
        body = converter.convert_faculty_to_rdf(
            FACULTY, [publication], "2026-01-01T00:00:00"
        )
        graph = rdflib.Graph()
        graph.parse(data=converter.PREFIXES + "\n" + body, format="turtle")
        assert list(graph.query(load_query("collaborating-institutions.rq"))) == []


class TestCollaboratorsByInstitution:
    def test_names_the_people_behind_a_collaboration(self):
        results = list(collaboration_graph().query(
            load_query("collaborators-by-institution.rq")
        ))
        assert len(results) == 1
        row = results[0]
        assert str(row.our_author_name) == "Ada Lovelace"
        assert str(row.partner_author_name) == "Alan Turing"


class TestOrganizationHierarchy:
    def test_reports_the_department_under_its_institution(self, monkeypatch):
        monkeypatch.setenv("INSTITUTION_NAME", "Example University")
        monkeypatch.setenv("INSTITUTION_ROR", EX_ROR)
        results = list(collaboration_graph().query(
            load_query("organization-hierarchy.rq")
        ))
        parented = {
            str(row.unit_name): str(row.parent_name)
            for row in results
            if row.parent_name
        }
        assert parented.get("Psychoceramics") == "Example University"

    def test_reports_where_each_identity_came_from(self):
        results = list(collaboration_graph().query(
            load_query("organization-hierarchy.rq")
        ))
        kinds = {str(row.unit_name): str(row.identifier_kind) for row in results}
        assert kinds["Massachusetts Institute of Technology"] == "ror"
        assert kinds["Psychoceramics"] == "local"
