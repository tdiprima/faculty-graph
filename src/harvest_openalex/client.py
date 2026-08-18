"""Fetch publication data from OpenAlex API."""

import json
import logging
import os
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from src.config import institution_name
from src.errors import HarvestError
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
RESULTS_PER_PAGE = 200

# OpenAlex caps a cursor walk well below this; the guard exists only so a
# malformed next_cursor cannot spin forever.
MAX_PAGES = 500


def _polite_email():
    """Return email for OpenAlex polite pool access."""
    return os.environ.get("OPENALEX_EMAIL", "")


def _fetch_json(url):
    """Fetch URL and parse JSON response. Raises HarvestError on failure."""
    request = Request(url, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise HarvestError(
            f"HTTP {error.code} from OpenAlex ({error.reason})"
        ) from error
    except URLError as error:
        raise HarvestError(f"Network error reaching OpenAlex: {error.reason}") from error
    except TimeoutError as error:
        raise HarvestError("Timed out waiting for OpenAlex") from error
    except json.JSONDecodeError as error:
        raise HarvestError(f"OpenAlex returned malformed JSON: {error}") from error


def _fetch_all_pages(params, description):
    """Walk an OpenAlex cursor-paginated result set to completion.

    Raises HarvestError rather than returning a partial page set, so a network
    failure mid-walk is never mistaken for a complete harvest.
    """
    params = dict(params)
    params["per-page"] = str(RESULTS_PER_PAGE)
    email = _polite_email()
    if email:
        params["mailto"] = email

    all_results = []
    cursor = "*"
    for _page_number in range(MAX_PAGES):
        params["cursor"] = cursor
        url = f"{OPENALEX_BASE}/works?{urlencode(params)}"
        data = _fetch_json(url)

        results = data.get("results", [])
        all_results.extend(results)

        cursor = data.get("meta", {}).get("next_cursor")
        if not cursor or not results:
            logger.info("OpenAlex %s: %d works", description, len(all_results))
            return all_results

        time.sleep(REQUEST_DELAY_SECONDS)

    raise HarvestError(
        f"OpenAlex cursor walk for {description} exceeded {MAX_PAGES} pages"
    )


def fetch_works_by_orcid(orcid_id):
    """Fetch all works for an ORCID ID from OpenAlex. Handles pagination."""
    params = {"filter": f"author.orcid:https://orcid.org/{orcid_id}"}
    results = _fetch_all_pages(params, f"ORCID fetch for {orcid_id}")
    return {"results": results}


def fetch_works_by_name(full_name, institution=None):
    """Fetch works by author name and institution. Lower confidence fallback.

    institution defaults to the configured INSTITUTION_NAME. Pass an empty
    string to search by name alone across all institutions.
    """
    if institution is None:
        institution = institution_name()
    search_filter = f"authorships.author.display_name.search:{full_name}"
    if institution:
        search_filter += f",authorships.institutions.display_name.search:{institution}"

    results = _fetch_all_pages(
        {"filter": search_filter}, f"name search for {full_name}"
    )
    return {"results": results}


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
    try:
        if search_method == SEARCH_METHOD_ORCID:
            raw_data = fetch_works_by_orcid(orcid_id)
        else:
            raw_data = fetch_works_by_name(full_name)
    except HarvestError as error:
        logger.error("OpenAlex harvest failed for %s: %s", full_name, error)
        return []

    if not raw_data.get("results"):
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
