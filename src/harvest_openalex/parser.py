"""Parse OpenAlex API responses into structured publication records."""

import logging

from src.names import display_name_record

logger = logging.getLogger(__name__)


def _extract_doi(work):
    """Extract bare DOI from OpenAlex work (strips https://doi.org/ prefix)."""
    doi = work.get("doi")
    if not doi:
        return None
    return doi.replace("https://doi.org/", "").replace("http://doi.org/", "")


def _extract_institutions(authorship):
    """Extract the institutions credited on one authorship.

    The whole institution object is kept, not just its label: OpenAlex supplies
    a ROR identifier, which is what lets "Example University" from one source
    and a ROR IRI from another be recognised as the same organization later.
    """
    institutions = []
    for institution in authorship.get("institutions", []):
        display_name = institution.get("display_name")
        if not display_name:
            continue
        openalex_id = institution.get("id", "") or ""
        institutions.append({
            "display_name": display_name,
            "ror": institution.get("ror"),
            "country_code": institution.get("country_code"),
            "type": institution.get("type"),
            "openalex_id": openalex_id.replace("https://openalex.org/", "") or None,
        })
    return institutions


def _extract_coauthors(work):
    """Extract coauthor info from authorships.

    OpenAlex renders author names as a single display string, so the given and
    family parts here are inferred rather than stated; each record carries the
    name_source flag that says so.
    """
    coauthors = []
    for position, authorship in enumerate(work.get("authorships", []), start=1):
        author = authorship.get("author", {})
        name = author.get("display_name")
        if not name:
            continue

        orcid = author.get("orcid")
        if orcid:
            orcid = orcid.replace("https://orcid.org/", "")

        openalex_author_id = author.get("id", "") or ""

        record = display_name_record(name)
        record["orcid"] = orcid
        record["openalex_author_id"] = (
            openalex_author_id.replace("https://openalex.org/", "") or None
        )
        record["institutions"] = _extract_institutions(authorship)
        record["position"] = position
        record["author_position"] = authorship.get("author_position")
        record["is_corresponding"] = bool(authorship.get("is_corresponding"))
        coauthors.append(record)

    return coauthors


def _format_page_range(first_page, last_page):
    """Render a page range the way a citation would print it."""
    first = str(first_page).strip() if first_page else ""
    last = str(last_page).strip() if last_page else ""
    if first and last and first != last:
        return f"{first}-{last}"
    return first or last or None


def _extract_concepts(work):
    """Extract topic/concept labels from work."""
    concepts = []
    for topic in work.get("topics", []):
        name = topic.get("display_name")
        if name:
            concepts.append(name)
    if not concepts:
        for concept in work.get("concepts", []):
            name = concept.get("display_name")
            if name and concept.get("score", 0) > 0.3:
                concepts.append(name)
    return concepts


def _extract_external_ids(work):
    """Extract all external identifiers from work."""
    ids = {}
    doi = _extract_doi(work)
    if doi:
        ids["doi"] = doi

    openalex_id = work.get("id", "")
    if openalex_id:
        ids["openalex"] = openalex_id.replace("https://openalex.org/", "")

    biblio_ids = work.get("ids", {})
    if biblio_ids.get("pmid"):
        pmid = biblio_ids["pmid"].replace("https://pubmed.ncbi.nlm.nih.gov/", "")
        ids["pmid"] = pmid
    if biblio_ids.get("pmcid"):
        ids["pmcid"] = biblio_ids["pmcid"]

    return ids


def parse_works(works_response):
    """Parse OpenAlex works response into list of publication dicts."""
    publications = []
    results = works_response.get("results", [])

    for work in results:
        title = work.get("title")
        if not title:
            continue

        external_ids = _extract_external_ids(work)
        doi = _extract_doi(work)
        pmid = external_ids.get("pmid")
        coauthors = _extract_coauthors(work)

        publication = {
            "title": title,
            "doi": doi,
            "pmid": pmid,
            "type": work.get("type"),
            "date": work.get("publication_date"),
            "external_ids": external_ids,
            "journal": None,
            "authors": [a["name"] for a in coauthors],
            "openalex_id": external_ids.get("openalex"),
            "coauthors": coauthors,
            "concepts": _extract_concepts(work),
            "cited_by_count": work.get("cited_by_count", 0),
        }

        biblio = work.get("biblio") or {}
        publication["volume"] = biblio.get("volume")
        publication["issue"] = biblio.get("issue")
        publication["pages"] = _format_page_range(
            biblio.get("first_page"), biblio.get("last_page")
        )
        publication["issn"] = None

        primary_location = work.get("primary_location", {})
        if primary_location:
            source = primary_location.get("source")
            if source:
                publication["journal"] = source.get("display_name")
                publication["issn"] = source.get("issn_l")

        publications.append(publication)

    logger.info("Parsed %d works from OpenAlex response", len(publications))
    return publications
