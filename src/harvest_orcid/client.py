"""Fetch ORCID records for faculty and save raw JSON responses."""

import csv
import json
import logging
import os
import re
import time
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from src.errors import SeedDataError
from src.harvest_orcid.parser import parse_works
from src.provenance import SEARCH_METHOD_ORCID, tag_publications

logger = logging.getLogger(__name__)

ORCID_API_BASE = "https://pub.orcid.org/v3.0"
SOURCE_NAME = "ORCID"

# Every downstream consumer indexes these directly; a missing column must fail
# at load time with a readable message rather than as a bare KeyError later.
REQUIRED_SEED_COLUMNS = ("faculty_id", "full_name", "department", "orcid", "email")
REQUEST_DELAY_SECONDS = 1.0

# faculty_id and orcid are used to build filesystem paths and API URLs
# throughout the pipeline; an unrestricted charset would let a crafted seed
# row escape the intended output directory or alter the ORCID request path.
FACULTY_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
ORCID_PATTERN = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def load_seed_faculty(csv_path):
    """Read and validate the faculty seed list from CSV, return list of dicts.

    Raises SeedDataError when the file is unreadable, the header is missing a
    required column, or a row omits an identifier the pipeline keys on.
    """
    try:
        with open(csv_path, newline="", encoding="utf-8") as csvfile:
            reader = csv.DictReader(csvfile)
            fieldnames = reader.fieldnames or []
            missing_columns = [
                column for column in REQUIRED_SEED_COLUMNS if column not in fieldnames
            ]
            if missing_columns:
                raise SeedDataError(
                    f"{csv_path} is missing required column(s): "
                    f"{', '.join(missing_columns)}"
                )
            rows = list(reader)
    except OSError as error:
        raise SeedDataError(f"Cannot read seed file {csv_path}: {error}") from error
    except UnicodeDecodeError as error:
        raise SeedDataError(f"Seed file {csv_path} is not valid UTF-8: {error}") from error

    faculty = []
    seen_ids = set()
    for line_number, row in enumerate(rows, start=2):
        record = {key: (value or "").strip() for key, value in row.items() if key}

        for column in ("faculty_id", "full_name"):
            if not record.get(column):
                raise SeedDataError(
                    f"{csv_path} line {line_number}: empty required field '{column}'"
                )

        faculty_id = record["faculty_id"]
        if faculty_id in seen_ids:
            raise SeedDataError(
                f"{csv_path} line {line_number}: duplicate faculty_id '{faculty_id}'"
            )
        if not FACULTY_ID_PATTERN.match(faculty_id):
            raise SeedDataError(
                f"{csv_path} line {line_number}: faculty_id '{faculty_id}' contains "
                "characters outside [A-Za-z0-9_-]"
            )

        orcid = record.get("orcid", "")
        if orcid and not ORCID_PATTERN.match(orcid):
            raise SeedDataError(
                f"{csv_path} line {line_number}: orcid '{orcid}' is not a valid ORCID iD"
            )

        email = record.get("email", "")
        if email and not EMAIL_PATTERN.match(email):
            raise SeedDataError(
                f"{csv_path} line {line_number}: email '{email}' is not a valid email address"
            )

        seen_ids.add(faculty_id)
        faculty.append(record)

    if not faculty:
        raise SeedDataError(f"Seed file {csv_path} contains no faculty rows")

    logger.info("Loaded %d faculty from %s", len(faculty), csv_path)
    return faculty


def fetch_orcid_works(orcid_id):
    """Fetch works for a single ORCID ID. Returns parsed JSON."""
    url = f"{ORCID_API_BASE}/{quote(orcid_id, safe='')}/works"
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
        publications = tag_publications(
            parse_works(works_data), SOURCE_NAME, SEARCH_METHOD_ORCID
        )

        results.append((faculty, publications))
        time.sleep(REQUEST_DELAY_SECONDS)

    harvested = sum(1 for _, pubs in results if pubs)
    logger.info("ORCID: harvested %d of %d faculty", harvested, len(faculty_list))
    return results
