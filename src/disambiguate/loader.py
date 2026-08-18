"""Reload harvested raw files into publication records for disambiguation.

Disambiguation runs against an existing harvest on disk rather than re-fetching,
so it must reconstruct the provenance the harvest clients assigned. Raw files do
not store the assertion status, so it is re-derived from the same rules the
clients use: the PubMed filename suffix records the search method, and OpenAlex
searches by ORCID iD when the faculty member has one.
"""

import json
import logging
from pathlib import Path

from src.harvest_openalex.parser import parse_works as parse_openalex_works
from src.harvest_orcid.parser import parse_works as parse_orcid_works
from src.harvest_pubmed.parser import parse_pubmed_xml
from src.provenance import (
    SEARCH_METHOD_NAME,
    SEARCH_METHOD_ORCID,
    STATUS_CANDIDATE,
    search_method_for_faculty,
    tag_publications,
)

logger = logging.getLogger(__name__)

OPENALEX_SOURCE = "OpenAlex"
ORCID_SOURCE = "ORCID"
PUBMED_SOURCE = "PubMed"

PUBMED_SEARCH_METHODS = (SEARCH_METHOD_ORCID, SEARCH_METHOD_NAME)


def _read_json(path):
    """Read a JSON raw file, returning None when it is missing or malformed."""
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as infile:
            return json.load(infile)
    except json.JSONDecodeError as error:
        logger.error("Malformed JSON in raw file %s: %s", path, error)
        return None


def load_known_works(faculty, raw_orcid_dir):
    """Load the faculty member's ORCID-verified publications.

    These are passed to the LLM as known-good examples. Returns an empty list
    when the faculty member has no ORCID iD or no ORCID harvest on disk.
    """
    orcid_id = faculty.get("orcid", "").strip()
    if not orcid_id:
        return []

    data = _read_json(Path(raw_orcid_dir) / f"{orcid_id}.json")
    if data is None:
        return []
    return tag_publications(
        parse_orcid_works(data), ORCID_SOURCE, SEARCH_METHOD_ORCID
    )


def load_openalex_publications(faculty, raw_openalex_dir):
    """Load OpenAlex publications for one faculty member from raw JSON."""
    data = _read_json(Path(raw_openalex_dir) / f"{faculty['faculty_id']}.json")
    if data is None:
        return []
    search_method = search_method_for_faculty(faculty)
    return tag_publications(
        parse_openalex_works(data), OPENALEX_SOURCE, search_method
    )


def load_pubmed_publications(faculty, raw_pubmed_dir):
    """Load PubMed publications for one faculty member from raw XML.

    The harvester writes one file per search method, so the suffix determines
    whether the records are authoritative or candidates.
    """
    raw_pubmed_dir = Path(raw_pubmed_dir)
    publications = []

    for search_method in PUBMED_SEARCH_METHODS:
        xml_path = raw_pubmed_dir / f"{faculty['faculty_id']}-{search_method}.xml"
        if not xml_path.exists():
            continue
        xml_data = xml_path.read_text(encoding="utf-8")
        publications.extend(
            tag_publications(
                parse_pubmed_xml(xml_data), PUBMED_SOURCE, search_method
            )
        )

    return publications


def load_candidates(faculty, raw_pubmed_dir, raw_openalex_dir):
    """Load every publication needing disambiguation for one faculty member.

    Only name-search results are returned; ORCID-matched works are already
    authoritative and need no LLM judgement.
    """
    publications = load_pubmed_publications(faculty, raw_pubmed_dir)
    publications.extend(load_openalex_publications(faculty, raw_openalex_dir))

    candidates = [
        pub for pub in publications
        if pub.get("assertion_status") == STATUS_CANDIDATE
    ]
    logger.debug(
        "Loaded %d candidates from %d raw publications for %s",
        len(candidates),
        len(publications),
        faculty["faculty_id"],
    )
    return candidates
