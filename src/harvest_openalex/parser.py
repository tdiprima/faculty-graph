"""Parse OpenAlex API responses into structured publication records."""

import logging

logger = logging.getLogger(__name__)


def _extract_doi(work):
    """Extract bare DOI from OpenAlex work (strips https://doi.org/ prefix)."""
    doi = work.get("doi")
    if not doi:
        return None
    return doi.replace("https://doi.org/", "").replace("http://doi.org/", "")


def _extract_coauthors(work):
    """Extract coauthor info from authorships."""
    coauthors = []
    for authorship in work.get("authorships", []):
        author = authorship.get("author", {})
        name = author.get("display_name")
        if not name:
            continue
        orcid = author.get("orcid")
        if orcid:
            orcid = orcid.replace("https://orcid.org/", "")
        institutions = [
            inst.get("display_name", "")
            for inst in authorship.get("institutions", [])
            if inst.get("display_name")
        ]
        coauthors.append({
            "name": name,
            "orcid": orcid,
            "institutions": institutions,
        })
    return coauthors


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

        publication = {
            "title": title,
            "doi": doi,
            "pmid": pmid,
            "type": work.get("type"),
            "date": work.get("publication_date"),
            "external_ids": external_ids,
            "journal": None,
            "authors": [a["name"] for a in _extract_coauthors(work)],
            "openalex_id": external_ids.get("openalex"),
            "coauthors": _extract_coauthors(work),
            "concepts": _extract_concepts(work),
            "cited_by_count": work.get("cited_by_count", 0),
        }

        primary_location = work.get("primary_location", {})
        if primary_location:
            source = primary_location.get("source")
            if source:
                publication["journal"] = source.get("display_name")

        publications.append(publication)

    logger.info("Parsed %d works from OpenAlex response", len(publications))
    return publications
