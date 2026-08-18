"""Fetch ORCID records for faculty and save raw JSON responses."""

import csv
import json
import logging
import os
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from src.harvest_orcid.parser import parse_works

logger = logging.getLogger(__name__)

ORCID_API_BASE = "https://pub.orcid.org/v3.0"
REQUEST_DELAY_SECONDS = 1.0


def load_seed_faculty(csv_path):
    """Read faculty seed list from CSV, return list of dicts."""
    faculty = []
    with open(csv_path, newline="", encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            faculty.append(row)
    return faculty


def fetch_orcid_works(orcid_id):
    """Fetch works for a single ORCID ID. Returns parsed JSON."""
    url = f"{ORCID_API_BASE}/{orcid_id}/works"
    request = Request(url, headers={"Accept": "application/json"})

    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        logger.error("HTTP %d fetching ORCID %s: %s", error.code, orcid_id, error.reason)
        return None
    except URLError as error:
        logger.error("Network error fetching ORCID %s: %s", orcid_id, error.reason)
        return None


def save_raw_response(orcid_id, data, output_dir):
    """Save raw ORCID API response to JSON file."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{orcid_id}.json"
    with open(output_path, "w", encoding="utf-8") as outfile:
        json.dump(data, outfile, indent=2, ensure_ascii=False)
    logger.info("Saved raw response: %s", output_path)
    return output_path


def harvest_all(faculty_list, raw_output_dir):
    """Fetch ORCID works for all faculty.

    Returns list of (faculty_dict, parsed_publications) tuples.
    Each publication has source='ORCID' and assertion_status='authoritative'.
    """
    results = []
    for faculty in faculty_list:
        orcid_id = faculty.get("orcid", "").strip()
        if not orcid_id:
            logger.warning("Skipping %s: no ORCID ID", faculty.get("full_name", "unknown"))
            results.append((faculty, []))
            continue

        logger.info("Fetching ORCID works for %s (%s)", faculty["full_name"], orcid_id)
        works_data = fetch_orcid_works(orcid_id)

        if works_data is None:
            logger.warning("No data returned for %s", faculty["full_name"])
            results.append((faculty, []))
            continue

        save_raw_response(orcid_id, works_data, raw_output_dir)
        publications = parse_works(works_data)

        for pub in publications:
            pub["source"] = "ORCID"
            pub["assertion_status"] = "authoritative"

        results.append((faculty, publications))
        time.sleep(REQUEST_DELAY_SECONDS)

    harvested = sum(1 for _, pubs in results if pubs)
    logger.info("ORCID: harvested %d of %d faculty", harvested, len(faculty_list))
    return results
