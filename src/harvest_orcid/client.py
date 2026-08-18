"""Fetch ORCID records for faculty and save raw JSON responses."""

import csv
import json
import logging
import os
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

logger = logging.getLogger(__name__)

ORCID_API_BASE = "https://pub.orcid.org/v3.0"
REQUEST_DELAY_SECONDS = 1.0


def load_seed_faculty(csv_path):
    """Read faculty seed list from CSV, return list of dicts."""
    faculty = []
    with open(csv_path, newline="", encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            if row.get("orcid", "").strip():
                faculty.append(row)
            else:
                logger.warning("Skipping %s: no ORCID ID", row.get("full_name", "unknown"))
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


def harvest_all(seed_csv, raw_output_dir):
    """Fetch ORCID works for all faculty in seed list. Returns list of (faculty_dict, works_json) tuples."""
    faculty_list = load_seed_faculty(seed_csv)
    if not faculty_list:
        logger.error("No faculty with ORCID IDs found in %s", seed_csv)
        return []

    results = []
    for faculty in faculty_list:
        orcid_id = faculty["orcid"].strip()
        logger.info("Fetching ORCID works for %s (%s)", faculty["full_name"], orcid_id)

        works_data = fetch_orcid_works(orcid_id)
        if works_data is None:
            logger.warning("No data returned for %s", faculty["full_name"])
            continue

        save_raw_response(orcid_id, works_data, raw_output_dir)
        results.append((faculty, works_data))
        time.sleep(REQUEST_DELAY_SECONDS)

    logger.info("Harvested %d of %d faculty", len(results), len(faculty_list))
    return results


def main():
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    project_root = Path(__file__).resolve().parent.parent.parent
    seed_csv = project_root / "data" / "seed" / "faculty.csv"
    raw_dir = project_root / "data" / "raw" / "orcid"
    rdf_output_dir = project_root / "data" / "output" / "rdf"

    if not seed_csv.exists():
        logger.error("Seed file not found: %s", seed_csv)
        sys.exit(1)

    results = harvest_all(seed_csv, raw_dir)
    if not results:
        logger.error("No ORCID data harvested")
        sys.exit(1)

    from src.rdf_model.converter import convert_all_to_rdf
    convert_all_to_rdf(results, rdf_output_dir)
    logger.info("Pipeline complete")


if __name__ == "__main__":
    main()
