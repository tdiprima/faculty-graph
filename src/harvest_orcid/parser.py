"""Parse ORCID API work responses into structured records."""

import logging

logger = logging.getLogger(__name__)


def extract_external_id(external_ids, id_type):
    """Extract a specific external ID value from ORCID external-ids structure."""
    if not external_ids:
        return None
    for ext_id in external_ids.get("external-id", []):
        if ext_id.get("external-id-type") == id_type:
            return ext_id.get("external-id-value")
    return None


def extract_all_external_ids(external_ids):
    """Extract all external IDs as a dict of {type: value}."""
    result = {}
    if not external_ids:
        return result
    for ext_id in external_ids.get("external-id", []):
        id_type = ext_id.get("external-id-type")
        id_value = ext_id.get("external-id-value")
        if id_type and id_value:
            result[id_type] = id_value
    return result


def parse_publication_date(work_summary):
    """Extract publication date from work summary. Returns ISO date string or None."""
    pub_date = work_summary.get("publication-date")
    if not pub_date:
        return None

    year_obj = pub_date.get("year")
    month_obj = pub_date.get("month")
    day_obj = pub_date.get("day")

    year = year_obj.get("value") if year_obj else None
    month = month_obj.get("value") if month_obj else None
    day = day_obj.get("value") if day_obj else None

    if not year:
        return None

    if month and day:
        return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
    if month:
        return f"{year}-{month.zfill(2)}"
    return year


def parse_journal_title(summary):
    """Extract the containing publication's title from an ORCID work summary.

    ORCID nests the value ({"journal-title": {"value": ...}}) and omits the key
    entirely for works that have no container.
    """
    journal_title = summary.get("journal-title")
    if not journal_title:
        return None
    value = journal_title.get("value")
    return value.strip() if value else None


def parse_works(works_json):
    """Parse ORCID works response into list of publication dicts."""
    publications = []
    work_groups = works_json.get("group", [])

    for group in work_groups:
        work_summaries = group.get("work-summary", [])
        if not work_summaries:
            continue

        summary = work_summaries[0]

        external_ids = group.get("external-ids")
        all_ids = extract_all_external_ids(external_ids)

        title_data = summary.get("title")
        title = None
        if title_data and title_data.get("title"):
            title = title_data["title"].get("value")

        if not title:
            logger.debug("Skipping work with no title")
            continue

        publication = {
            "title": title,
            "doi": all_ids.get("doi"),
            "pmid": all_ids.get("pmid"),
            "type": summary.get("type"),
            "date": parse_publication_date(summary),
            "journal": parse_journal_title(summary),
            "external_ids": all_ids,
            "put_code": summary.get("put-code"),
        }
        publications.append(publication)

    logger.info("Parsed %d publications from ORCID response", len(publications))
    return publications
