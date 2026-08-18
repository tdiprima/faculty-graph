"""The vocabulary definition matches what the pipeline actually emits.

A vocabulary file drifts the moment someone adds a term to the converter and
forgets this file, and nothing else would catch it: the generated Turtle still
parses, and the undefined term simply means nothing to a consumer. These tests
compare the two directions — every emitted term is defined, and every defined
term is emitted — so the claim "this model maps cleanly onto yours" stays true.
"""

import pathlib
import re

import pytest

from src.rdf_model import converter

rdflib = pytest.importorskip("rdflib", reason="rdflib parses the vocabulary")

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
ONTOLOGY_PATH = PROJECT_ROOT / "ontology" / "fg.ttl"

# Files that emit or consume fg: terms. Prose in docstrings is excluded by
# reading only the source files that generate Turtle, plus the shipped queries
# and the hand-written reference model.
EMITTING_SOURCES = (
    PROJECT_ROOT / "src" / "rdf_model" / "converter.py",
    PROJECT_ROOT / "src" / "reconcile" / "writer.py",
)

CONSUMING_FILES = tuple(sorted((PROJECT_ROOT / "queries").glob("*.rq"))) + (
    PROJECT_ROOT / "data" / "output" / "rdf" / "example.ttl",
)

FG = rdflib.Namespace(converter.FG_NAMESPACE)

TERM_PATTERN = re.compile(r"fg:([A-Za-z][A-Za-z0-9_]*)")

# Terms named only in prose, never emitted as triples. Empty today; kept as the
# declared place to record such an exemption, so a future one is visible here
# rather than quietly widening a pattern.
PROSE_ONLY_TERMS = frozenset()


def terms_in(path):
    """Return every fg: local name appearing in a file."""
    if not path.exists():
        return set()
    return set(TERM_PATTERN.findall(path.read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def ontology():
    """The parsed vocabulary."""
    graph = rdflib.Graph()
    graph.parse(ONTOLOGY_PATH, format="turtle")
    return graph


@pytest.fixture(scope="module")
def defined_terms(ontology):
    """Every fg: term the vocabulary defines."""
    return {
        str(subject)[len(converter.FG_NAMESPACE):]
        for subject in ontology.subjects()
        if isinstance(subject, rdflib.URIRef)
        and str(subject).startswith(converter.FG_NAMESPACE)
        and str(subject) != converter.FG_NAMESPACE
    }


@pytest.fixture(scope="module")
def emitted_terms():
    """Every fg: term the code emits or the shipped queries rely on."""
    terms = set()
    for path in EMITTING_SOURCES + CONSUMING_FILES:
        terms |= terms_in(path)
    return terms - PROSE_ONLY_TERMS


def test_the_vocabulary_parses(ontology):
    assert len(ontology) > 0


def test_every_emitted_term_is_defined(defined_terms, emitted_terms):
    undefined = sorted(emitted_terms - defined_terms)
    assert undefined == [], (
        f"fg: terms emitted or queried but not defined in {ONTOLOGY_PATH.name}: "
        f"{undefined}"
    )


def test_every_defined_term_is_used(defined_terms, emitted_terms):
    unused = sorted(defined_terms - emitted_terms)
    assert unused == [], (
        f"fg: terms defined in {ONTOLOGY_PATH.name} but never emitted or "
        f"queried: {unused}"
    )


def test_every_term_has_a_label(ontology, defined_terms):
    missing = sorted(
        term for term in defined_terms
        if ontology.value(FG[term], rdflib.RDFS.label) is None
    )
    assert missing == []


def test_every_term_has_a_comment(ontology, defined_terms):
    """Individuals inherit meaning from their class; classes and properties do not."""
    typed_as_individual = {"authoritative", "candidate", "verified", "rejected",
                           "ORCID", "PubMed", "OpenAlex"}
    missing = sorted(
        term for term in defined_terms - typed_as_individual
        if ontology.value(FG[term], rdflib.RDFS.comment) is None
    )
    assert missing == []


def properties_in(ontology, property_type):
    """Return the fg: terms declared as this kind of property."""
    return {
        str(subject)[len(converter.FG_NAMESPACE):]
        for subject in ontology.subjects(rdflib.RDF.type, property_type)
    }


def test_every_property_declares_a_range(ontology):
    owl = rdflib.OWL
    declared = properties_in(ontology, owl.ObjectProperty) | properties_in(
        ontology, owl.DatatypeProperty
    )
    missing = sorted(
        term for term in declared
        if ontology.value(FG[term], rdflib.RDFS.range) is None
    )
    assert missing == []


def test_every_property_declares_a_domain_or_says_why_not(ontology):
    """idType and idValue live on an anonymous identifier node with no class."""
    owl = rdflib.OWL
    exempt = {"idType", "idValue"}
    declared = properties_in(ontology, owl.ObjectProperty) | properties_in(
        ontology, owl.DatatypeProperty
    )
    missing = sorted(
        term for term in declared - exempt
        if ontology.value(FG[term], rdflib.RDFS.domain) is None
    )
    assert missing == []


def test_no_property_declares_two_plain_domains(ontology):
    """Two rdfs:domain statements mean intersection, not union.

    Declaring fg:work with domain PublicationAssertion and domain Authorship
    would infer that every subject is both. Shared properties must use an
    explicit owl:unionOf instead, and this catches a regression to the naive
    form.
    """
    offenders = []
    for subject in set(ontology.subjects(rdflib.RDFS.domain, None)):
        domains = list(ontology.objects(subject, rdflib.RDFS.domain))
        if len(domains) > 1:
            offenders.append(str(subject))
    assert offenders == []


def test_shared_properties_use_a_union_domain(ontology):
    """fg:work and fg:source are used on more than one class."""
    for term in ("work", "source"):
        domain = ontology.value(FG[term], rdflib.RDFS.domain)
        union = ontology.value(domain, rdflib.OWL.unionOf)
        assert union is not None, f"fg:{term} must declare a union domain"


def test_alignment_targets_are_absolute_iris(ontology):
    """An alignment to a relative or malformed IRI maps onto nothing."""
    alignment_properties = (
        rdflib.RDFS.subClassOf,
        rdflib.RDFS.subPropertyOf,
        rdflib.OWL.equivalentProperty,
    )
    for alignment in alignment_properties:
        for target in ontology.objects(None, alignment):
            if isinstance(target, rdflib.URIRef):
                assert str(target).startswith(("http://", "https://")), target


def test_the_vocabulary_declares_its_own_version(ontology):
    version = ontology.value(
        rdflib.URIRef(converter.FG_NAMESPACE), rdflib.OWL.versionInfo
    )
    assert version is not None
