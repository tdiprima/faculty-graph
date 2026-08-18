"""Convert harvested publication data into RDF Turtle format.

Accepts pre-parsed publications from any source (ORCID, PubMed, OpenAlex).
Each publication dict must include 'source' and 'assertion_status' fields.
"""

import logging
import re
from datetime import datetime, timezone
from pathlib import Path

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

FGDATA_NAMESPACE = "http://example.org/faculty-graph/data/"


def sanitize_uri_part(value):
    """Make a string safe for use in a URI."""
    return re.sub(r"[^a-zA-Z0-9._-]", "-", value)


def build_data_iri(*path_parts):
    """Build a full angle-bracket IRI under the fgdata namespace.

    Turtle prefixed names cannot contain an unescaped "/", so hierarchical
    identifiers must be emitted as absolute IRIs rather than fgdata:a/b.
    """
    return f"<{FGDATA_NAMESPACE}{'/'.join(path_parts)}>"


def build_faculty_uri(faculty_id):
    """Generate a URI for a faculty member."""
    return build_data_iri("faculty", sanitize_uri_part(str(faculty_id)))


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
    """Generate a URI for a publication based on DOI, PMID, or title."""
    if publication.get("doi"):
        return build_data_iri("work", f"doi-{sanitize_uri_part(publication['doi'])}")
    if publication.get("pmid"):
        return build_data_iri("work", f"pmid-{sanitize_uri_part(str(publication['pmid']))}")
    return build_data_iri("work", f"title-{sanitize_uri_part(publication['title'][:80])}")


def build_assertion_uri(faculty_id, source, publication):
    """Generate a URI for a publication assertion, unique per source."""
    if publication.get("doi"):
        work_key = f"doi-{sanitize_uri_part(publication['doi'])}"
    elif publication.get("pmid"):
        work_key = f"pmid-{sanitize_uri_part(str(publication['pmid']))}"
    else:
        work_key = f"title-{sanitize_uri_part(publication['title'][:60])}"
    source_key = sanitize_uri_part(source.lower())
    faculty_key = sanitize_uri_part(str(faculty_id))
    return build_data_iri("assertion", f"{faculty_key}-{source_key}-{work_key}")


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
        build_faculty_uri(faculty_id),
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

    if publication.get("journal"):
        lines.append(f'    fg:journal          "{escape_turtle_string(publication["journal"])}" ;')

    date_literal = format_date_literal(publication.get("date"))
    if date_literal:
        lines.append(f"    dcterms:date        {date_literal} ;")

    if publication.get("openalex_id"):
        lines.append(f'    fg:openAlexId       "{publication["openalex_id"]}" ;')

    if publication.get("cited_by_count"):
        lines.append(f'    fg:citedByCount     {publication["cited_by_count"]} ;')

    for id_type, id_value in publication.get("external_ids", {}).items():
        if id_type not in ("doi", "pmid", "openalex"):
            lines.append(
                f'    fg:externalId       [ fg:idType "{id_type}" ; '
                f'fg:idValue "{escape_turtle_string(str(id_value))}" ] ;'
            )

    lines[-1] = lines[-1].rstrip(" ;") + " ."
    return "\n".join(lines)


def assertion_to_turtle(faculty_id, publication, harvest_timestamp):
    """Generate Turtle triples for a publication assertion."""
    source = publication.get("source", "unknown")
    status = publication.get("assertion_status", "candidate")
    assertion_uri = build_assertion_uri(faculty_id, source, publication)
    work_uri = build_work_uri(publication)
    source_uri = f"fg:{sanitize_uri_part(source)}"

    lines = [
        f"{assertion_uri}",
        f"    a                   fg:PublicationAssertion ;",
        f"    fg:faculty          {build_faculty_uri(faculty_id)} ;",
        f"    fg:work             {work_uri} ;",
        f"    fg:status           fg:{status} ;",
        f"    fg:source           {source_uri} ;",
        f'    fg:harvestedAt      "{harvest_timestamp}"^^xsd:dateTime ;',
        f"    prov:wasAttributedTo {source_uri} ;",
    ]

    if publication.get("search_method"):
        lines.append(f'    fg:searchMethod     "{publication["search_method"]}" ;')

    if publication.get("reviewed_by"):
        lines.append(f'    fg:reviewedBy       "{publication["reviewed_by"]}" ;')
    if publication.get("reviewed_at"):
        lines.append(f'    fg:reviewedAt       "{publication["reviewed_at"]}"^^xsd:dateTime ;')
    if publication.get("review_note"):
        lines.append(f'    fg:reviewNote       "{escape_turtle_string(publication["review_note"])}" ;')

    lines[-1] = lines[-1].rstrip(" ;") + " ."
    return "\n".join(lines)


def coauthor_to_turtle(publication):
    """Generate Turtle triples for coauthor relationships."""
    coauthors = publication.get("coauthors", [])
    if not coauthors:
        return ""

    work_uri = build_work_uri(publication)
    lines = []
    for coauthor in coauthors:
        name = coauthor.get("name", "")
        if not name:
            continue
        coauthor_uri = build_data_iri("person", sanitize_uri_part(name[:60]))
        lines.append(f"{coauthor_uri}")
        lines.append(f"    a                   foaf:Person ;")
        lines.append(f'    foaf:name           "{escape_turtle_string(name)}" ;')
        if coauthor.get("orcid"):
            lines.append(f'    fg:orcidId          "{coauthor["orcid"]}" ;')
        lines[-1] = lines[-1].rstrip(" ;") + " ."
        lines.append("")
        lines.append(f"{work_uri} dcterms:creator {coauthor_uri} .")

    return "\n".join(lines)


def convert_faculty_to_rdf(faculty, publications, harvest_timestamp):
    """Convert one faculty member's publications to Turtle string."""
    faculty_id = faculty["faculty_id"]
    seen_work_uris = set()
    sections = []
    sections.append(f"# ── Faculty: {faculty['full_name']} ──")
    sections.append(faculty_to_turtle(faculty))

    for pub in publications:
        work_uri = build_work_uri(pub)
        if work_uri not in seen_work_uris:
            sections.append(publication_to_turtle(pub))
            seen_work_uris.add(work_uri)

            coauthor_ttl = coauthor_to_turtle(pub)
            if coauthor_ttl:
                sections.append(coauthor_ttl)

        sections.append(assertion_to_turtle(faculty_id, pub, harvest_timestamp))

    logger.info(
        "Generated RDF for %s: %d publications, %d assertions",
        faculty["full_name"],
        len(seen_work_uris),
        len(publications),
    )
    return "\n\n".join(sections)


def convert_all_to_rdf(all_results, output_dir, review_manager=None):
    """Convert all harvested results to RDF and write files.

    all_results: list of (faculty_dict, publications_list) tuples.
    Each publication must have 'source' and 'assertion_status' set.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    harvest_timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    all_sections = [PREFIXES]

    faculty_pubs = {}
    for faculty, publications in all_results:
        fid = faculty["faculty_id"]
        if fid not in faculty_pubs:
            faculty_pubs[fid] = {"faculty": faculty, "publications": []}
        faculty_pubs[fid]["publications"].extend(publications)

    for fid, data in faculty_pubs.items():
        faculty = data["faculty"]
        publications = data["publications"]

        if review_manager:
            publications = review_manager.apply_reviews(fid, publications)

        faculty_rdf = convert_faculty_to_rdf(faculty, publications, harvest_timestamp)
        all_sections.append(faculty_rdf)

        per_faculty_path = output_dir / f"{fid}.ttl"
        with open(per_faculty_path, "w", encoding="utf-8") as outfile:
            outfile.write(PREFIXES + "\n" + faculty_rdf + "\n")
        logger.info("Wrote %s", per_faculty_path)

    combined_path = output_dir / "faculty-all.ttl"
    with open(combined_path, "w", encoding="utf-8") as outfile:
        outfile.write("\n\n".join(all_sections) + "\n")
    logger.info("Wrote combined RDF: %s", combined_path)
    return combined_path
