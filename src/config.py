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
    INSTITUTION_ROR          Research Organization Registry IRI for this
                             institution, e.g. "https://ror.org/abc123456".
                             Optional, but without it the graph cannot tell
                             which collaborations are external.
    FG_BASE_URI              Base IRI for generated RDF. Must be absolute and
                             end with "/" (default:
                             "http://example.org/faculty-graph/").
"""

import os
import re

from src.errors import ConfigError

DEFAULT_INSTITUTION_NAME = "Example University"
DEFAULT_BASE_URI = "http://example.org/faculty-graph/"

ROR_IRI_PREFIX = "https://ror.org/"

# ROR identifiers are a fixed-length base32 string with a two-digit checksum.
ROR_ID_PATTERN = re.compile(r"^0[0-9a-hj-km-np-tv-z]{6}[0-9]{2}$")


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


def normalize_ror(value):
    """Reduce a ROR identifier to its canonical IRI form.

    Sources write the same identifier three ways: bare ("abc123456"), as an
    http IRI, and as an https IRI. They denote one organization, so they must
    collapse to one subject IRI or the graph would split it into three.

    Returns None for an empty value. Raises ConfigError when a non-empty value
    is not a well-formed ROR identifier, because a malformed one would mint a
    plausible-looking IRI that resolves to nothing.
    """
    text = str(value or "").strip()
    if not text:
        return None

    for prefix in ("https://ror.org/", "http://ror.org/", "ror.org/"):
        if text.lower().startswith(prefix):
            text = text[len(prefix):]
            break

    identifier = text.strip("/").lower()
    if not ROR_ID_PATTERN.match(identifier):
        raise ConfigError(
            f"Not a well-formed ROR identifier: {value!r}. "
            f"Expected nine characters like 'abc123456', optionally prefixed "
            f"with {ROR_IRI_PREFIX}"
        )
    return f"{ROR_IRI_PREFIX}{identifier}"


def institution_ror():
    """Canonical ROR IRI for this institution, or None when unset.

    Without it the pipeline still runs; it simply cannot label a collaboration
    as external, because it does not know which organization is us.
    """
    return normalize_ror(os.environ.get("INSTITUTION_ROR", ""))
