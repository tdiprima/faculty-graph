"""Institution-specific configuration, read from the environment.

Nothing in this pipeline is hardcoded to a single university. Every value that
differs between institutions lives here and is supplied through environment
variables, so the same code runs anywhere without edits.

Environment variables:
    INSTITUTION_NAME         Full institution name as it appears in OpenAlex
                             (default: "Example University").
    INSTITUTION_AFFILIATION  Substring used for PubMed affiliation searches.
                             Defaults to INSTITUTION_NAME. Use a shorter,
                             distinctive form when the full name is rarely
                             written out on papers (e.g. "Example U" or a
                             city name).
    FG_BASE_URI              Base IRI for generated RDF. Must be absolute and
                             end with "/" (default:
                             "http://example.org/faculty-graph/").
"""

import os

from src.errors import ConfigError

DEFAULT_INSTITUTION_NAME = "Example University"
DEFAULT_BASE_URI = "http://example.org/faculty-graph/"


def institution_name():
    """Institution display name used for OpenAlex institution filtering.

    An empty value is legal and means "do not constrain name searches by
    institution" — broader recall, more false matches for review.
    """
    return os.environ.get("INSTITUTION_NAME", DEFAULT_INSTITUTION_NAME).strip()


def institution_affiliation():
    """Affiliation substring used for PubMed affiliation searches.

    Falls back to the institution name so a single variable is enough for
    institutions whose papers spell the name out in full.
    """
    affiliation = os.environ.get("INSTITUTION_AFFILIATION", "").strip()
    return affiliation or institution_name()


def base_uri():
    """Base IRI for every generated RDF term.

    Validated at read time: a malformed base would silently produce Turtle that
    no triple store can load.
    """
    value = os.environ.get("FG_BASE_URI", DEFAULT_BASE_URI).strip()
    if not value.startswith(("http://", "https://")):
        raise ConfigError(
            f"FG_BASE_URI must start with http:// or https:// (got {value!r})"
        )
    if not value.endswith("/"):
        raise ConfigError(f"FG_BASE_URI must end with '/' (got {value!r})")
    return value
