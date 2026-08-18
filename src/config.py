"""Institution-specific configuration, read from the environment.

Nothing in this pipeline is hardcoded to a single university. Every value that
differs between institutions lives here and is supplied through environment
variables, so the same code runs anywhere without edits.

Values come from the environment. A .env file in the project root is loaded at
startup for convenience, but anything already exported in the shell wins over it:
a one-off override must not require editing a file.

Environment variables:
    INSTITUTION_NAME         Full institution name as it appears in OpenAlex
                             (default: "Example University").
    INSTITUTION_AFFILIATION  Substring used for PubMed affiliation searches.
                             Defaults to INSTITUTION_NAME. Use a shorter,
                             distinctive form when the full name is rarely
                             written out on papers (e.g. "Example U" or a
                             city name).
    INSTITUTION_ROR          Research Organization Registry IRI(s) for this
                             institution, e.g. "https://ror.org/abc123456".
                             Accepts several separated by commas, for an
                             institution with more than one registered entry
                             (a university and its hospital). Optional, but
                             without it the graph cannot tell which
                             collaborations are external.
    FG_BASE_URI              Base IRI for generated RDF. Must be absolute and
                             end with "/" (default:
                             "http://example.org/faculty-graph/").
"""

import logging
import os
import re
from pathlib import Path

from src.errors import ConfigError

logger = logging.getLogger(__name__)

DEFAULT_INSTITUTION_NAME = "Example University"
DEFAULT_BASE_URI = "http://example.org/faculty-graph/"

ENV_FILENAME = ".env"

ROR_IRI_PREFIX = "https://ror.org/"

# ROR identifiers are a fixed-length base32 string with a two-digit checksum.
ROR_ID_PATTERN = re.compile(r"^0[0-9a-hj-km-np-tv-z]{6}[0-9]{2}$")


def project_root():
    """The repository root, derived from this file's location."""
    return Path(__file__).resolve().parent.parent


def load_env_file(path=None):
    """Load .env into the environment without overriding what is already set.

    Returns the path loaded, or None when there is no .env or python-dotenv is
    missing. A missing .env is normal: every value has a default or is optional,
    and CI passes them through the real environment.
    """
    path = Path(path) if path else project_root() / ENV_FILENAME

    try:
        from dotenv import load_dotenv
    except ImportError:
        logger.warning(
            "python-dotenv is not installed, so %s was not read. "
            "Install dependencies with: uv sync",
            path,
        )
        return None

    if not path.exists():
        logger.debug("No %s found; reading configuration from the environment", path)
        return None

    # override=False: an exported variable beats the file, so a one-off run does
    # not mean editing configuration.
    load_dotenv(path, override=False)
    logger.info("Loaded configuration from %s", path)
    return path


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


def institution_rors():
    """Every ROR IRI that counts as this institution, in the order configured.

    One institution may hold several registered entries — a university and its
    hospital are separate ROR records — and a paper written jointly by two of
    them is internal, not an outside collaboration. Returns an empty list when
    unset; the pipeline still runs, it simply cannot label a collaboration as
    external because it does not know which organization is us.
    """
    raw = os.environ.get("INSTITUTION_ROR", "")
    identifiers = []
    for candidate in raw.split(","):
        canonical = normalize_ror(candidate)
        if canonical and canonical not in identifiers:
            identifiers.append(canonical)
    return identifiers


def institution_ror():
    """The primary ROR IRI for this institution, or None when unset.

    The first configured identifier. Used where exactly one organization must be
    named, such as the institution a department hangs beneath.
    """
    identifiers = institution_rors()
    return identifiers[0] if identifiers else None
