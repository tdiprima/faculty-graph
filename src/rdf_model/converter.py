"""Convert harvested ORCID data into RDF Turtle format."""

import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from src.harvest_orcid.parser import parse_works

logger = logging.getLogger(__name__)

PREFIXES = """\
@prefix rdf:    <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs:   <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:    <http://www.w3.org/2001/XMLSchema#> .
@prefix foaf:   <http://xmlns.com/foaf/0.1/> .
@prefix bibo:   <http://purl.org/ontology/bibo/> .
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix prov:   <http://www.w3.org/ns/prov#> .
@prefix fg:     <http://example.org/faculty-graph/> .
@prefix fgdata: <http://example.org/faculty-graph/data/> .
"""


def sanitize_uri_part(value):
    """Make a string safe for use in a URI."""
    return re.sub(r"[^a-zA-Z0-9._-]", "-", value)


def escape_turtle_string(value):
    """Escape special characters for Turtle string literals."""
    return (
        value
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )


def build_work_uri(publication):
    """Generate a URI for a publication based on DOI or title."""
    if publication.get("doi"):
        return f"fgdata:work/doi-{sanitize_uri_part(publication['doi'])}"
    return f"fgdata:work/orcid-{sanitize_uri_part(publication['title'][:80])}"


def build_assertion_uri(faculty_id, publication):
    """Generate a URI for a publication assertion."""
    if publication.get("doi"):
        work_key = f"doi-{sanitize_uri_part(publication['doi'])}"
    else:
        work_key = f"orcid-{sanitize_uri_part(publication['title'][:60])}"
    return f"fgdata:assertion/{faculty_id}-{work_key}"


def format_date_literal(date_str):
    """Format a date string as an xsd:date or xsd:gYear literal."""
    if not date_str:
        return None
    if len(date_str) == 4:
        return f'"{date_str}"^^xsd:gYear'
    if len(date_str) == 7:
        return f'"{date_str}"^^xsd:gYearMonth'
    return f'"{date_str}"^^xsd:date'


def faculty_to_turtle(faculty):
    """Generate Turtle triples for a faculty member."""
    faculty_id = faculty["faculty_id"]
    lines = [
        f"fgdata:faculty/{faculty_id}",
        f"    a                   foaf:Person ;",
        f'    foaf:name           "{escape_turtle_string(faculty["full_name"])}" ;',
        f'    fg:facultyId        "{faculty_id}" ;',
        f'    fg:department       "{escape_turtle_string(faculty["department"])}" ;',
        f'    fg:orcidId          "{faculty["orcid"]}" ;',
        f'    foaf:mbox           <mailto:{faculty["email"]}> .',
    ]
    return "\n".join(lines)


def publication_to_turtle(publication):
    """Generate Turtle triples for a single publication."""
    work_uri = build_work_uri(publication)
    lines = [
        f"{work_uri}",
        f"    a                   bibo:AcademicArticle ;",
        f'    dcterms:title       "{escape_turtle_string(publication["title"])}" ;',
    ]

    if publication.get("doi"):
        lines.append(f'    bibo:doi            "{publication["doi"]}" ;')

    if publication.get("pmid"):
        lines.append(f'    bibo:pmid           "{publication["pmid"]}" ;')

    if publication.get("type"):
        lines.append(f'    fg:workType         "{publication["type"]}" ;')

    date_literal = format_date_literal(publication.get("date"))
    if date_literal:
        lines.append(f"    dcterms:date        {date_literal} ;")

    for id_type, id_value in publication.get("external_ids", {}).items():
        if id_type not in ("doi", "pmid"):
            lines.append(f'    fg:externalId       [ fg:idType "{id_type}" ; fg:idValue "{escape_turtle_string(id_value)}" ] ;')

    lines[-1] = lines[-1].rstrip(" ;") + " ."
    return "\n".join(lines)


def assertion_to_turtle(faculty_id, publication, harvest_timestamp):
    """Generate Turtle triples for a publication assertion."""
    assertion_uri = build_assertion_uri(faculty_id, publication)
    work_uri = build_work_uri(publication)
    lines = [
        f"{assertion_uri}",
        f"    a                   fg:PublicationAssertion ;",
        f"    fg:faculty          fgdata:faculty/{faculty_id} ;",
        f"    fg:work             {work_uri} ;",
        f"    fg:status           fg:authoritative ;",
        f"    fg:source           fg:ORCID ;",
        f'    fg:harvestedAt      "{harvest_timestamp}"^^xsd:dateTime ;',
        f"    prov:wasAttributedTo fg:ORCID .",
    ]
    return "\n".join(lines)


def convert_faculty_to_rdf(faculty, works_json, harvest_timestamp):
    """Convert one faculty member's ORCID data to Turtle string."""
    publications = parse_works(works_json)
    faculty_id = faculty["faculty_id"]

    sections = []
    sections.append(f"# ── Faculty: {faculty['full_name']} ──")
    sections.append(faculty_to_turtle(faculty))

    for pub in publications:
        sections.append(publication_to_turtle(pub))
        sections.append(assertion_to_turtle(faculty_id, pub, harvest_timestamp))

    logger.info(
        "Generated RDF for %s: %d publications",
        faculty["full_name"],
        len(publications),
    )
    return "\n\n".join(sections)


def convert_all_to_rdf(results, output_dir):
    """Convert all harvested results to RDF and write to files."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    harvest_timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    all_sections = [PREFIXES]

    for faculty, works_json in results:
        faculty_rdf = convert_faculty_to_rdf(faculty, works_json, harvest_timestamp)
        all_sections.append(faculty_rdf)

        per_faculty_path = output_dir / f"{faculty['faculty_id']}.ttl"
        with open(per_faculty_path, "w", encoding="utf-8") as outfile:
            outfile.write(PREFIXES + "\n" + faculty_rdf + "\n")
        logger.info("Wrote %s", per_faculty_path)

    combined_path = output_dir / "faculty-orcid.ttl"
    with open(combined_path, "w", encoding="utf-8") as outfile:
        outfile.write("\n\n".join(all_sections) + "\n")
    logger.info("Wrote combined RDF: %s", combined_path)
    return combined_path
