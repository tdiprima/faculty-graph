"""Fetch publication data from OpenAlex API."""

import json
import logging
import os
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from src.harvest_openalex.parser import parse_works
from src.provenance import (
    SEARCH_METHOD_ORCID,
    search_method_for_faculty,
    tag_publications,
)

logger = logging.getLogger(__name__)

OPENALEX_BASE = "https://api.openalex.org"
SOURCE_NAME = "OpenAlex"
REQUEST_DELAY_SECONDS = 0.2


def _polite_email():
    """Return email for OpenAlex polite pool access."""
    return os.environ.get("OPENALEX_EMAIL", "")


def _fetch_json(url):
    """Fetch URL and parse JSON response."""
    request = Request(url, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        logger.error("HTTP %d fetching %s: %s", error.code, url, error.reason)
        return None
    except URLError as error:
        logger.error("Network error fetching %s: %s", url, error.reason)
        return None


def fetch_works_by_orcid(orcid_id):
    """Fetch all works for an ORCID ID from OpenAlex. Handles pagination."""
    all_results = []
    params = {
        "filter": f"author.orcid:https://orcid.org/{orcid_id}",
        "per-page": "200",
    }
    email = _polite_email()
    if email:
        params["mailto"] = email

    cursor = "*"
    while cursor:
        params["cursor"] = cursor
        url = f"{OPENALEX_BASE}/works?{urlencode(params)}"
        data = _fetch_json(url)
        if not data:
            break

        results = data.get("results", [])
        all_results.extend(results)

        meta = data.get("meta", {})
        cursor = meta.get("next_cursor")
        if not results:
            break

        time.sleep(REQUEST_DELAY_SECONDS)

    logger.info("OpenAlex ORCID fetch for %s: %d works", orcid_id, len(all_results))
    return {"results": all_results}


def fetch_works_by_name(full_name, institution="Example University"):
    """Fetch works by author name and institution. Lower confidence fallback."""
    all_results = []
    search_filter = f"authorships.author.display_name.search:{full_name}"
    if institution:
        search_filter += f",authorships.institutions.display_name.search:{institution}"

    params = {
        "filter": search_filter,
        "per-page": "200",
    }
    email = _polite_email()
    if email:
        params["mailto"] = email

    cursor = "*"
    while cursor:
        params["cursor"] = cursor
        url = f"{OPENALEX_BASE}/works?{urlencode(params)}"
        data = _fetch_json(url)
        if not data:
            break

        results = data.get("results", [])
        all_results.extend(results)

        meta = data.get("meta", {})
        cursor = meta.get("next_cursor")
        if not results:
            break

        time.sleep(REQUEST_DELAY_SECONDS)

    logger.info("OpenAlex name search for %s: %d works", full_name, len(all_results))
    return {"results": all_results}


def save_raw_response(faculty_id, data, output_dir):
    """Save raw OpenAlex response to JSON file."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{faculty_id}.json"
    with open(output_path, "w", encoding="utf-8") as outfile:
        json.dump(data, outfile, indent=2, ensure_ascii=False)
    logger.info("Saved raw OpenAlex response: %s", output_path)


def harvest_faculty(faculty, raw_dir):
    """Harvest OpenAlex data for one faculty member. Returns list of publication dicts."""
    orcid_id = faculty.get("orcid", "").strip()
    full_name = faculty["full_name"]
    faculty_id = faculty["faculty_id"]

    search_method = search_method_for_faculty(faculty)
    if search_method == SEARCH_METHOD_ORCID:
        raw_data = fetch_works_by_orcid(orcid_id)
    else:
        raw_data = fetch_works_by_name(full_name)

    if not raw_data or not raw_data.get("results"):
        logger.warning("No OpenAlex data for %s", full_name)
        return []

    save_raw_response(faculty_id, raw_data, raw_dir)
    publications = tag_publications(parse_works(raw_data), SOURCE_NAME, search_method)

    logger.info(
        "OpenAlex harvest for %s: %d publications",
        full_name,
        len(publications),
    )
    return publications


def harvest_all(faculty_list, raw_dir):
    """Harvest OpenAlex for all faculty. Returns list of (faculty, publications) tuples."""
    results = []
    for faculty in faculty_list:
        publications = harvest_faculty(faculty, raw_dir)
        results.append((faculty, publications))
        time.sleep(REQUEST_DELAY_SECONDS)
    return results
