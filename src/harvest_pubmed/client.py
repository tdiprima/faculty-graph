"""Fetch PubMed records for faculty via NCBI E-utilities."""

import json
import logging
import os
import time
from pathlib import Path
from urllib.parse import quote_plus, urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from src.harvest_pubmed.parser import parse_pubmed_xml
from src.provenance import SEARCH_METHOD_NAME, SEARCH_METHOD_ORCID, tag_publications

logger = logging.getLogger(__name__)

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
SOURCE_NAME = "PubMed"
REQUEST_DELAY_SECONDS = 0.4


def _api_params():
    """Build common API parameters including optional API key."""
    params = {}
    api_key = os.environ.get("NCBI_API_KEY")
    if api_key:
        params["api_key"] = api_key
    return params


def _fetch_url(url):
    """Fetch URL content with timeout and error handling."""
    request = Request(url)
    try:
        with urlopen(request, timeout=30) as response:
            return response.read().decode("utf-8")
    except HTTPError as error:
        logger.error("HTTP %d fetching %s: %s", error.code, url, error.reason)
        return None
    except URLError as error:
        logger.error("Network error fetching %s: %s", url, error.reason)
        return None


def search_by_orcid(orcid_id):
    """Search PubMed for articles by ORCID author ID. Returns list of PMIDs."""
    params = _api_params()
    params.update({
        "db": "pubmed",
        "term": f"{orcid_id}[auid]",
        "retmode": "json",
        "retmax": "10000",
    })
    url = f"{EUTILS_BASE}/esearch.fcgi?{urlencode(params)}"
    raw = _fetch_url(url)
    if not raw:
        return []

    data = json.loads(raw)
    pmids = data.get("esearchresult", {}).get("idlist", [])
    logger.info("PubMed ORCID search for %s: %d results", orcid_id, len(pmids))
    return pmids


def search_by_name(full_name, affiliation="Example University"):
    """Search PubMed by author name and affiliation. Returns list of PMIDs."""
    parts = full_name.strip().split()
    if len(parts) < 2:
        logger.warning("Cannot parse name for PubMed search: %s", full_name)
        return []

    last_name = parts[-1]
    first_name = parts[0]
    term = f"{last_name} {first_name}[author] AND {affiliation}[affiliation]"

    params = _api_params()
    params.update({
        "db": "pubmed",
        "term": term,
        "retmode": "json",
        "retmax": "10000",
    })
    url = f"{EUTILS_BASE}/esearch.fcgi?{urlencode(params)}"
    raw = _fetch_url(url)
    if not raw:
        return []

    data = json.loads(raw)
    pmids = data.get("esearchresult", {}).get("idlist", [])
    logger.info("PubMed name search for %s: %d results", full_name, len(pmids))
    return pmids


def fetch_records(pmids):
    """Fetch full PubMed records by PMID list. Returns XML string."""
    if not pmids:
        return None

    batch_size = 200
    all_xml_parts = []

    for start in range(0, len(pmids), batch_size):
        batch = pmids[start:start + batch_size]
        params = _api_params()
        params.update({
            "db": "pubmed",
            "id": ",".join(batch),
            "rettype": "xml",
            "retmode": "xml",
        })
        url = f"{EUTILS_BASE}/efetch.fcgi?{urlencode(params)}"
        xml_data = _fetch_url(url)
        if xml_data:
            all_xml_parts.append(xml_data)
        time.sleep(REQUEST_DELAY_SECONDS)

    return "\n".join(all_xml_parts) if all_xml_parts else None


def save_raw_response(faculty_id, data, output_dir, suffix=""):
    """Save raw PubMed response to file."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{faculty_id}{suffix}.xml"
    output_path = output_dir / filename
    with open(output_path, "w", encoding="utf-8") as outfile:
        outfile.write(data)
    logger.info("Saved raw PubMed response: %s", output_path)


def harvest_faculty(faculty, raw_dir):
    """Harvest PubMed data for one faculty member. Returns list of publication dicts."""
    orcid_id = faculty.get("orcid", "").strip()
    full_name = faculty["full_name"]
    faculty_id = faculty["faculty_id"]
    all_publications = []
    seen_pmids = set()

    if orcid_id:
        pmids = search_by_orcid(orcid_id)
        time.sleep(REQUEST_DELAY_SECONDS)
        if pmids:
            xml_data = fetch_records(pmids)
            if xml_data:
                save_raw_response(faculty_id, xml_data, raw_dir, f"-{SEARCH_METHOD_ORCID}")
                publications = tag_publications(
                    parse_pubmed_xml(xml_data), SOURCE_NAME, SEARCH_METHOD_ORCID
                )
                for pub in publications:
                    if pub.get("pmid"):
                        seen_pmids.add(pub["pmid"])
                all_publications.extend(publications)
            time.sleep(REQUEST_DELAY_SECONDS)

    pmids = search_by_name(full_name)
    time.sleep(REQUEST_DELAY_SECONDS)
    new_pmids = [p for p in pmids if p not in seen_pmids]

    if new_pmids:
        xml_data = fetch_records(new_pmids)
        if xml_data:
            save_raw_response(faculty_id, xml_data, raw_dir, f"-{SEARCH_METHOD_NAME}")
            publications = tag_publications(
                parse_pubmed_xml(xml_data), SOURCE_NAME, SEARCH_METHOD_NAME
            )
            all_publications.extend(publications)

    logger.info(
        "PubMed harvest for %s: %d publications",
        full_name,
        len(all_publications),
    )
    return all_publications


def harvest_all(faculty_list, raw_dir):
    """Harvest PubMed for all faculty. Returns list of (faculty, publications) tuples."""
    results = []
    for faculty in faculty_list:
        publications = harvest_faculty(faculty, raw_dir)
        results.append((faculty, publications))
        time.sleep(REQUEST_DELAY_SECONDS)
    return results
