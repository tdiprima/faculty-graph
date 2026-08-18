"""Parse PubMed XML responses into structured publication records."""

import logging

from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException

from src.names import structured_name

logger = logging.getLogger(__name__)


def _get_text(element, path, default=None):
    """Safely extract text from an XML element path."""
    found = element.find(path)
    if found is not None and found.text:
        return found.text.strip()
    return default


def _parse_article_date(article):
    """Extract publication date from PubMed article. Returns ISO date string."""
    for date_tag in ["ArticleDate", ".//PubDate"]:
        date_elem = article.find(date_tag)
        if date_elem is None:
            continue
        year = _get_text(date_elem, "Year")
        month = _get_text(date_elem, "Month")
        day = _get_text(date_elem, "Day")
        if not year:
            continue
        if month and month.isdigit() and day:
            return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
        if month and month.isdigit():
            return f"{year}-{month.zfill(2)}"
        return year
    return None


def _parse_author_orcid(author):
    """Extract an author's ORCID iD from their Identifier elements, if present."""
    for identifier in author.findall("Identifier"):
        if identifier.get("Source") != "ORCID":
            continue
        value = identifier.text.strip() if identifier.text else ""
        if value:
            return value.replace("https://orcid.org/", "").replace("http://orcid.org/", "")
    return None


def _parse_author_affiliations(author):
    """Extract the raw affiliation strings listed for one author.

    PubMed gives affiliation as free text with no identifier, so the string is
    kept exactly as published. Resolving it to an institution is a separate
    reconciliation step, not a parsing one.
    """
    affiliations = []
    for affiliation_info in author.findall("AffiliationInfo"):
        value = _get_text(affiliation_info, "Affiliation")
        if value and value not in affiliations:
            affiliations.append(value)
    return affiliations


def _parse_authors(author_list):
    """Extract structured author records from an AuthorList element.

    LastName and ForeName arrive as separate elements and stay separate: once
    joined they cannot be reliably pulled apart again.
    """
    if author_list is None:
        return []

    authors = []
    for position, author in enumerate(author_list.findall("Author"), start=1):
        family = _get_text(author, "LastName", "")
        given = _get_text(author, "ForeName", "")
        if not family:
            continue

        record = structured_name(given, family)
        record["initials"] = _get_text(author, "Initials")
        record["orcid"] = _parse_author_orcid(author)
        record["affiliations"] = _parse_author_affiliations(author)
        record["position"] = position
        authors.append(record)

    return authors


def _parse_journal_details(article):
    """Extract container details: ISSN, volume, issue, and page range."""
    details = {"issn": None, "volume": None, "issue": None, "pages": None}

    journal = article.find("Journal")
    if journal is not None:
        details["issn"] = _get_text(journal, "ISSN")
        details["volume"] = _get_text(journal, "JournalIssue/Volume")
        details["issue"] = _get_text(journal, "JournalIssue/Issue")

    details["pages"] = _get_text(article, "Pagination/MedlinePgn")
    return details


def _parse_article_ids(pubmed_data):
    """Extract external IDs from PubmedData/ArticleIdList."""
    ids = {}
    if pubmed_data is None:
        return ids
    id_list = pubmed_data.find("ArticleIdList")
    if id_list is None:
        return ids
    for article_id in id_list.findall("ArticleId"):
        id_type = article_id.get("IdType", "")
        value = article_id.text.strip() if article_id.text else ""
        if id_type and value:
            ids[id_type] = value
    return ids


def parse_pubmed_xml(xml_string):
    """Parse PubMed efetch XML into list of publication dicts."""
    publications = []

    try:
        root = ET.fromstring(xml_string)
    except ET.ParseError as error:
        logger.error("Failed to parse PubMed XML: %s", error)
        return publications
    except DefusedXmlException as error:
        logger.error("Rejected PubMed XML with unsafe entity construct: %s", error)
        return publications

    articles = root.findall(".//PubmedArticle")
    for article_elem in articles:
        citation = article_elem.find("MedlineCitation")
        if citation is None:
            continue

        pmid = _get_text(citation, "PMID")
        article = citation.find("Article")
        if article is None:
            continue

        title = _get_text(article, "ArticleTitle")
        if not title:
            continue

        journal = _get_text(article, "Journal/Title")
        coauthors = _parse_authors(article.find("AuthorList"))
        journal_details = _parse_journal_details(article)
        date = _parse_article_date(article)

        pubmed_data = article_elem.find("PubmedData")
        external_ids = _parse_article_ids(pubmed_data)

        doi = external_ids.get("doi")
        if not doi:
            doi = external_ids.get("DOI")

        publication = {
            "title": title,
            "doi": doi,
            "pmid": pmid or external_ids.get("pubmed"),
            "type": "journal-article",
            "date": date,
            "external_ids": external_ids,
            "journal": journal,
            "issn": journal_details["issn"],
            "volume": journal_details["volume"],
            "issue": journal_details["issue"],
            "pages": journal_details["pages"],
            "authors": [author["name"] for author in coauthors],
            "coauthors": coauthors,
        }
        publications.append(publication)

    logger.info("Parsed %d articles from PubMed XML", len(publications))
    return publications
