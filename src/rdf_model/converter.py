"""Convert harvested publication data into RDF Turtle format.

Accepts pre-parsed publications from any source (ORCID, PubMed, OpenAlex).
Each publication dict must include 'source' and 'assertion_status' fields.
"""

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from src.config import base_uri, institution_name, institution_ror
from src.identity import (
    group_publications,
    merge_group,
    normalize_doi,
    normalize_pmid,
)
from src.names import display_name_record, structured_name
from src.rdf_model.organizations import (
    OrganizationRegistry,
    build_organization,
    department_organization,
    name_key,
    organization_from_institution,
)

logger = logging.getLogger(__name__)

# Read once at import: the base IRI must not change partway through a run, or
# a single graph would carry terms under two different namespaces.
FG_NAMESPACE = base_uri()
FGDATA_NAMESPACE = f"{FG_NAMESPACE}data/"

PREFIXES = f"""\
@prefix rdf:    <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs:   <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:    <http://www.w3.org/2001/XMLSchema#> .
@prefix foaf:   <http://xmlns.com/foaf/0.1/> .
@prefix bibo:   <http://purl.org/ontology/bibo/> .
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix prov:   <http://www.w3.org/ns/prov#> .
@prefix org:    <http://www.w3.org/ns/org#> .
@prefix owl:    <http://www.w3.org/2002/07/owl#> .
@prefix fg:     <{FG_NAMESPACE}> .
@prefix fgdata: <{FGDATA_NAMESPACE}> .
"""


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
    """Generate the cross-source URI for a publication.

    Identifiers are normalized first: DOIs are case-insensitive, so the same
    work must not mint two IRIs because two sources cased its DOI differently.
    """
    return build_data_iri("work", work_key_for(publication))


def build_organization_uri(organization):
    """Return the IRI that stands for this organization.

    A ROR identifier is already a globally resolvable IRI naming exactly this
    organization, so it is used as the subject directly. Anything else gets a
    locally minted IRI, which says plainly that the identity is ours rather than
    the registry's.
    """
    if organization.get("ror"):
        return f"<{organization['ror']}>"
    return build_data_iri("org", f"name-{sanitize_uri_part(name_key(organization['name']))}")


def work_key_for(publication):
    """Return the identifier fragment that names this work.

    Shared by the cross-source work IRI and the per-source one so the two can
    never disagree about which identifier a work is keyed on.
    """
    doi = normalize_doi(publication.get("doi"))
    if doi:
        return f"doi-{sanitize_uri_part(doi)}"
    pmid = normalize_pmid(publication.get("pmid"))
    if pmid:
        return f"pmid-{sanitize_uri_part(pmid)}"
    return f"title-{sanitize_uri_part(publication['title'][:80])}"


def build_source_work_uri(source, publication):
    """Generate a work IRI scoped to the source that reported it.

    The cross-source IRI from build_work_uri deliberately collapses records that
    share an identifier. A per-source graph must not do that: it records what one
    source said, on its own, so that linking it to another source's record is a
    separate, reversible, reviewable assertion rather than a silent merge.
    """
    source_key = sanitize_uri_part(str(source or "unknown").lower())
    return build_data_iri("work", source_key, work_key_for(publication))


def build_authorship_uri(publication, coauthor, work_uri):
    """Return the IRI for one author's contribution to one work.

    Keyed on the work and the author's position, which is what makes an
    authorship unique: the same person may appear twice on a work under
    different affiliations.
    """
    work_key = work_uri.strip("<>").rsplit("/", 1)[-1]
    position = coauthor.get("position") or 0
    person_key = sanitize_uri_part(str(coauthor.get("name", ""))[:60])
    return build_data_iri("authorship", f"{work_key}-{position}-{person_key}")


def build_person_uri(coauthor):
    """Return the IRI for a co-author.

    ORCID is used when the source supplied one: it identifies a person globally,
    where a name collides between different people and splits one person across
    spellings. Reconciling the name-keyed nodes is a later phase.
    """
    orcid = str(coauthor.get("orcid") or "").strip()
    if orcid:
        return build_data_iri("person", f"orcid-{sanitize_uri_part(orcid)}")
    return build_data_iri("person", sanitize_uri_part(str(coauthor.get("name", ""))[:60]))


def build_assertion_uri(faculty_id, source, publication):
    """Generate a URI for a publication assertion, unique per source."""
    if normalize_doi(publication.get("doi")):
        work_key = f"doi-{sanitize_uri_part(normalize_doi(publication['doi']))}"
    elif normalize_pmid(publication.get("pmid")):
        work_key = f"pmid-{sanitize_uri_part(normalize_pmid(publication['pmid']))}"
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


def format_integer_literal(value):
    """Return a bare xsd:integer literal for value, or None if it isn't integer-safe.

    Emitted unquoted, so a non-integer value here would inject raw Turtle rather
    than break out of a string literal; only a validated int is ever returned.
    """
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return None


def home_organization():
    """Build the organization record for the institution running this pipeline.

    Returns None when INSTITUTION_NAME is empty, which is the documented way of
    saying "do not constrain by institution". Departments then stand alone
    rather than being parented to a guess.
    """
    name = institution_name()
    if not name:
        return None
    return build_organization(name, ror=institution_ror())


def organization_to_turtle(organization, parent_uri=None):
    """Generate Turtle triples describing one organization."""
    lines = [
        build_organization_uri(organization),
        f"    a                   fg:Organization, org:Organization ;",
        f'    rdfs:label          "{escape_turtle_string(organization["name"])}" ;',
        f'    foaf:name           "{escape_turtle_string(organization["name"])}" ;',
    ]

    if organization.get("ror"):
        lines.append(f'    fg:rorId            <{organization["ror"]}> ;')

    if organization.get("country_code"):
        lines.append(
            f'    fg:countryCode      "{escape_turtle_string(str(organization["country_code"]))}" ;'
        )

    if organization.get("type"):
        lines.append(
            f'    fg:orgType          "{escape_turtle_string(str(organization["type"]))}" ;'
        )

    lines.append(f'    fg:identifierKind   "{organization["kind"]}" ;')

    if parent_uri:
        lines.append(f"    org:subOrganizationOf {parent_uri} ;")

    lines[-1] = lines[-1].rstrip(" ;") + " ."
    return "\n".join(lines)


def _page_lines(pages):
    """Emit the page range as printed, plus its endpoints when they parse out."""
    if not pages:
        return []

    pages = str(pages).strip()
    lines = [f'    bibo:pages          "{escape_turtle_string(pages)}" ;']

    start, separator, end = pages.partition("-")
    start = start.strip()
    end = end.strip()
    if separator and start and end:
        lines.append(f'    bibo:pageStart      "{escape_turtle_string(start)}" ;')
        lines.append(f'    bibo:pageEnd        "{escape_turtle_string(end)}" ;')

    return lines


def faculty_name(faculty):
    """Build a name record for a seed faculty member.

    A seed list that states given and family names separately is believed; one
    that gives only full_name is split by the same rules co-author names go
    through, and carries the same fg:nameSource marker saying the split is a
    guess.
    """
    if faculty.get("given_name") and faculty.get("family_name"):
        return structured_name(
            faculty["given_name"], faculty["family_name"], faculty["full_name"]
        )
    return display_name_record(faculty["full_name"])


def faculty_to_turtle(faculty, department_uri=None):
    """Generate Turtle triples for a faculty member.

    The department string the seed list supplied is kept alongside the link to
    the department resource. The string is what the source said; the link is
    what we concluded it meant, and losing either would make the conclusion
    unauditable.
    """
    faculty_id = faculty["faculty_id"]
    name = faculty_name(faculty)
    lines = [
        build_faculty_uri(faculty_id),
        f"    a                   foaf:Person ;",
        f'    foaf:name           "{escape_turtle_string(faculty["full_name"])}" ;',
    ]

    if name["given_name"]:
        lines.append(
            f'    foaf:givenName      "{escape_turtle_string(name["given_name"])}" ;'
        )
    if name["family_name"]:
        lines.append(
            f'    foaf:familyName     "{escape_turtle_string(name["family_name"])}" ;'
        )
    if name["given_name"] or name["family_name"]:
        lines.append(
            f'    fg:nameSource       "{escape_turtle_string(name["name_source"])}" ;'
        )

    lines.extend([
        f'    fg:facultyId        "{escape_turtle_string(faculty_id)}" ;',
        f'    fg:department       "{escape_turtle_string(faculty["department"])}" ;',
    ])

    if department_uri:
        lines.append(f"    org:memberOf        {department_uri} ;")

    lines.append(f'    fg:orcidId          "{escape_turtle_string(faculty["orcid"])}" ;')
    lines.append(f'    foaf:mbox           <mailto:{quote(faculty["email"], safe="@.")}> .')
    return "\n".join(lines)


def publication_to_turtle(publication, work_uri=None):
    """Generate Turtle triples for a single publication.

    work_uri is supplied by the per-source writer, which keys works by source so
    that two sources describing one article stay two nodes until something links
    them.
    """
    if work_uri is None:
        work_uri = build_work_uri(publication)
    lines = [
        f"{work_uri}",
        f"    a                   bibo:AcademicArticle ;",
        f'    dcterms:title       "{escape_turtle_string(publication["title"])}" ;',
    ]

    if publication.get("doi"):
        lines.append(f'    bibo:doi            "{escape_turtle_string(str(publication["doi"]))}" ;')

    if publication.get("pmid"):
        lines.append(f'    bibo:pmid           "{escape_turtle_string(str(publication["pmid"]))}" ;')

    if publication.get("type"):
        lines.append(f'    fg:workType         "{escape_turtle_string(publication["type"])}" ;')

    if publication.get("journal"):
        lines.append(f'    fg:journal          "{escape_turtle_string(publication["journal"])}" ;')

    if publication.get("issn"):
        lines.append(f'    bibo:issn           "{escape_turtle_string(str(publication["issn"]))}" ;')

    if publication.get("volume"):
        lines.append(f'    bibo:volume         "{escape_turtle_string(str(publication["volume"]))}" ;')

    if publication.get("issue"):
        lines.append(f'    bibo:issue          "{escape_turtle_string(str(publication["issue"]))}" ;')

    lines.extend(_page_lines(publication.get("pages")))

    date_literal = format_date_literal(publication.get("date"))
    if date_literal:
        lines.append(f"    dcterms:date        {date_literal} ;")

    if publication.get("openalex_id"):
        lines.append(f'    fg:openAlexId       "{escape_turtle_string(str(publication["openalex_id"]))}" ;')

    cited_by = format_integer_literal(publication.get("cited_by_count"))
    if cited_by is not None:
        lines.append(f"    fg:citedByCount     {cited_by} ;")

    for alternate_doi in publication.get("alternate_dois", []):
        lines.append(
            f'    fg:externalId       [ fg:idType "doi" ; '
            f'fg:idValue "{escape_turtle_string(str(alternate_doi))}" ] ;'
        )

    for alternate_pmid in publication.get("alternate_pmids", []):
        lines.append(
            f'    fg:externalId       [ fg:idType "pmid" ; '
            f'fg:idValue "{escape_turtle_string(str(alternate_pmid))}" ] ;'
        )

    for id_type, id_value in publication.get("external_ids", {}).items():
        if id_type not in ("doi", "pmid", "openalex"):
            lines.append(
                f'    fg:externalId       [ fg:idType "{escape_turtle_string(str(id_type))}" ; '
                f'fg:idValue "{escape_turtle_string(str(id_value))}" ] ;'
            )

    lines[-1] = lines[-1].rstrip(" ;") + " ."
    return "\n".join(lines)


def assertion_to_turtle(faculty_id, publication, harvest_timestamp, work_uri=None):
    """Generate Turtle triples for a publication assertion.

    work_uri is supplied by the caller when this record was merged into another
    record's work, so the assertion points at the surviving work node rather than
    minting a duplicate one from its own identifiers.
    """
    source = publication.get("source", "unknown")
    status = publication.get("assertion_status", "candidate")
    assertion_uri = build_assertion_uri(faculty_id, source, publication)
    if work_uri is None:
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
        lines.append(f'    fg:reviewedBy       "{escape_turtle_string(str(publication["reviewed_by"]))}" ;')
    if publication.get("reviewed_at"):
        lines.append(f'    fg:reviewedAt       "{escape_turtle_string(str(publication["reviewed_at"]))}"^^xsd:dateTime ;')
    if publication.get("review_note"):
        lines.append(f'    fg:reviewNote       "{escape_turtle_string(publication["review_note"])}" ;')

    lines[-1] = lines[-1].rstrip(" ;") + " ."
    return "\n".join(lines)


def _coauthor_organizations(coauthor, registry):
    """Register every organization this authorship names, returning their IRIs."""
    uris = []
    for institution in coauthor.get("institutions", []):
        organization = registry.add(organization_from_institution(institution))
        if not organization:
            continue
        uri = build_organization_uri(organization)
        if uri not in uris:
            uris.append(uri)
    return uris


def person_to_turtle(coauthor):
    """Generate Turtle triples describing one co-author as a person."""
    person_uri = build_person_uri(coauthor)
    lines = [
        f"{person_uri}",
        f"    a                   foaf:Person ;",
        f'    foaf:name           "{escape_turtle_string(coauthor["name"])}" ;',
    ]

    if coauthor.get("given_name"):
        lines.append(
            f'    foaf:givenName      "{escape_turtle_string(str(coauthor["given_name"]))}" ;'
        )
    if coauthor.get("family_name"):
        lines.append(
            f'    foaf:familyName     "{escape_turtle_string(str(coauthor["family_name"]))}" ;'
        )
    if coauthor.get("name_source"):
        lines.append(
            f'    fg:nameSource       "{escape_turtle_string(str(coauthor["name_source"]))}" ;'
        )
    if coauthor.get("orcid"):
        lines.append(
            f'    fg:orcidId          "{escape_turtle_string(str(coauthor["orcid"]))}" ;'
        )

    lines[-1] = lines[-1].rstrip(" ;") + " ."
    return "\n".join(lines)


def authorship_to_turtle(publication, coauthor, work_uri, registry):
    """Generate Turtle triples for one author's contribution to one work.

    An author's institution is a fact about that author on that paper, not a
    standing fact about the person, so affiliation hangs off the authorship
    rather than off the person. This is what makes "which institutions produced
    this work together" answerable in one hop.
    """
    authorship_uri = build_authorship_uri(publication, coauthor, work_uri)
    person_uri = build_person_uri(coauthor)

    lines = [
        f"{authorship_uri}",
        f"    a                   fg:Authorship ;",
        f"    fg:work             {work_uri} ;",
        f"    fg:author           {person_uri} ;",
    ]

    position = format_integer_literal(coauthor.get("position"))
    if position is not None:
        lines.append(f"    fg:position         {position} ;")

    if coauthor.get("author_position"):
        lines.append(
            f'    fg:authorRole       "{escape_turtle_string(str(coauthor["author_position"]))}" ;'
        )

    if coauthor.get("is_corresponding"):
        lines.append(f"    fg:isCorresponding  true ;")

    for organization_uri in _coauthor_organizations(coauthor, registry):
        lines.append(f"    fg:affiliatedWith   {organization_uri} ;")

    # Free-text affiliation lines name several organizations at once, so they
    # stay as unresolved source strings for the reconciliation phase to read.
    for affiliation in coauthor.get("affiliations", []):
        lines.append(
            f'    fg:affiliationRaw   "{escape_turtle_string(str(affiliation))}" ;'
        )

    lines[-1] = lines[-1].rstrip(" ;") + " ."
    return "\n".join(lines)


def coauthor_to_turtle(publication, registry=None, work_uri=None):
    """Generate Turtle triples for a work's authors and their affiliations."""
    coauthors = publication.get("coauthors", [])
    if not coauthors:
        return ""

    if registry is None:
        registry = OrganizationRegistry()

    if work_uri is None:
        work_uri = build_work_uri(publication)
    sections = []
    for coauthor in coauthors:
        if not coauthor.get("name"):
            continue
        person_uri = build_person_uri(coauthor)
        sections.append(person_to_turtle(coauthor))
        sections.append(f"{work_uri} dcterms:creator {person_uri} .")
        sections.append(authorship_to_turtle(publication, coauthor, work_uri, registry))

    return "\n\n".join(sections)


def convert_faculty_to_rdf(faculty, publications, harvest_timestamp):
    """Convert one faculty member's publications to Turtle string.

    Records describing the same work are merged into a single work node, but every
    harvested record still emits its own assertion: the merge removes duplicate
    works from the graph without erasing which source claimed what.
    """
    faculty_id = faculty["faculty_id"]
    registry = OrganizationRegistry()

    home = registry.add(home_organization())
    home_uri = build_organization_uri(home) if home else None

    department = registry.add(department_organization(faculty.get("department")))
    department_uri = build_organization_uri(department) if department else None

    sections = []
    sections.append(f"# ── Faculty: {faculty['full_name']} ──")
    sections.append(faculty_to_turtle(faculty, department_uri))

    groups = group_publications(publications)
    work_sections = []
    for group in groups:
        merged_work = merge_group(group)
        work_uri = build_work_uri(merged_work)

        work_sections.append(publication_to_turtle(merged_work))

        coauthor_ttl = coauthor_to_turtle(merged_work, registry)
        if coauthor_ttl:
            work_sections.append(coauthor_ttl)

        for pub in group:
            work_sections.append(
                assertion_to_turtle(faculty_id, pub, harvest_timestamp, work_uri)
            )

    # Organizations are emitted after the works that referenced them, because
    # the registry only knows the full set once every authorship has been read.
    sections.append("# ── Organizations ──")
    for organization in registry.all():
        parent_uri = home_uri if organization is department else None
        sections.append(organization_to_turtle(organization, parent_uri))

    sections.extend(work_sections)

    logger.info(
        "Generated RDF for %s: %d works from %d assertions, %d organizations",
        faculty["full_name"],
        len(groups),
        len(publications),
        len(registry),
    )
    return "\n\n".join(sections)


def convert_source_to_rdf(faculty, publications, source, harvest_timestamp):
    """Convert one source's records for one faculty member, without merging.

    This is the per-source view: every record this source reported becomes its
    own work node, keyed by source, even when two records share a DOI. Nothing
    here decides that two sources describe the same work — that judgement is the
    reconciliation phase's, and keeping it out of here is what makes it
    reversible.
    """
    faculty_id = faculty["faculty_id"]
    registry = OrganizationRegistry()

    home = registry.add(home_organization())
    home_uri = build_organization_uri(home) if home else None

    department = registry.add(department_organization(faculty.get("department")))
    department_uri = build_organization_uri(department) if department else None

    sections = [f"# ── {source}: {faculty['full_name']} ──"]
    sections.append(faculty_to_turtle(faculty, department_uri))

    work_sections = []
    for publication in publications:
        work_uri = build_source_work_uri(source, publication)

        work_sections.append(publication_to_turtle(publication, work_uri))
        work_sections.append(
            f"{work_uri} fg:reportedBy       fg:{sanitize_uri_part(source)} ."
        )

        coauthor_ttl = coauthor_to_turtle(publication, registry, work_uri)
        if coauthor_ttl:
            work_sections.append(coauthor_ttl)

        work_sections.append(
            assertion_to_turtle(faculty_id, publication, harvest_timestamp, work_uri)
        )

    sections.append("# ── Organizations ──")
    for organization in registry.all():
        parent_uri = home_uri if organization is department else None
        sections.append(organization_to_turtle(organization, parent_uri))

    sections.extend(work_sections)
    return "\n\n".join(sections)


def convert_by_source(all_results, output_dir, review_manager=None):
    """Write one unmerged Turtle graph per source.

    Returns {source: path}. These graphs are the harvest of record: each says
    only what one source reported, so a bad reconciliation is undone by dropping
    one links file rather than by re-harvesting.
    """
    output_dir = Path(output_dir) / "by-source"
    output_dir.mkdir(parents=True, exist_ok=True)
    harvest_timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    by_source = {}
    for faculty, publications in all_results:
        for publication in publications:
            source = publication.get("source", "unknown")
            by_source.setdefault(source, {}).setdefault(
                faculty["faculty_id"], {"faculty": faculty, "publications": []}
            )["publications"].append(publication)

    written = {}
    for source, faculty_records in by_source.items():
        sections = [PREFIXES]
        for faculty_id, data in faculty_records.items():
            publications = data["publications"]
            if review_manager:
                publications = review_manager.apply_reviews(faculty_id, publications)
            sections.append(
                convert_source_to_rdf(
                    data["faculty"], publications, source, harvest_timestamp
                )
            )

        source_path = output_dir / f"{sanitize_uri_part(source.lower())}.ttl"
        with open(source_path, "w", encoding="utf-8") as outfile:
            outfile.write("\n\n".join(sections) + "\n")
        logger.info("Wrote per-source RDF: %s", source_path)
        written[source] = source_path

    return written


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

    convert_by_source(all_results, output_dir, review_manager)
    return combined_path
