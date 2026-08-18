"""Split personal names into their parts without inventing structure.

Sources differ in what they give us. PubMed supplies LastName and ForeName as
distinct XML elements; OpenAlex and ORCID supply only a rendered display string.
Concatenating structured parts loses information that cannot be recovered, so
structured parts are kept verbatim wherever a source provides them.

Where only a display string exists, a split is a guess. This module guesses only
when the form is unambiguous and reports None otherwise, so a downstream
consumer can tell a parsed name from an assumed one. Every name record carries
`name_source` recording which of the two it is.
"""

import logging
import re

logger = logging.getLogger(__name__)

STRUCTURED = "structured"
DISPLAY = "display"

_WHITESPACE = re.compile(r"\s+")

# Name particles bind to the family name ("van der Waals"), so a trailing-token
# split would cut them in the wrong place.
NAME_PARTICLES = frozenset({
    "van", "von", "der", "den", "de", "del", "della", "di", "da", "dos", "du",
    "la", "le", "el", "al", "bin", "ibn", "ter", "ten", "af", "av", "mac", "mc",
    "st", "san", "santa",
})

# Generational and honorific suffixes are not family names.
NAME_SUFFIXES = frozenset({
    "jr", "sr", "ii", "iii", "iv", "v", "phd", "md", "dds", "dvm", "msc", "mph",
})


def normalize_whitespace(value):
    """Collapse whitespace runs and strip the ends."""
    return _WHITESPACE.sub(" ", str(value or "").strip())


def join_name(given_name, family_name):
    """Render structured parts as a display string.

    The parts stay on the record alongside this value; nothing here replaces
    them.
    """
    given = normalize_whitespace(given_name)
    family = normalize_whitespace(family_name)
    if given and family:
        return f"{given} {family}"
    return family or given


def _strip_suffix(tokens):
    """Drop a trailing generational or honorific suffix token."""
    if len(tokens) < 2:
        return tokens
    last = tokens[-1].rstrip(".").lower()
    if last in NAME_SUFFIXES:
        return tokens[:-1]
    return tokens


def split_display_name(display_name):
    """Guess given and family parts from a rendered name.

    Returns (given_name, family_name), either of which may be None. A name is
    left unsplit rather than split wrongly: a single token, or one whose
    penultimate token is a particle, has no unambiguous reading.
    """
    normalized = normalize_whitespace(display_name)
    if not normalized:
        return None, None

    # "Family, Given" is explicit about which part is which.
    if "," in normalized:
        family, _, given = normalized.partition(",")
        family = normalize_whitespace(family)
        given = normalize_whitespace(given)
        if family and given:
            return given, family
        return None, None

    tokens = _strip_suffix(normalized.split(" "))
    if len(tokens) < 2:
        return None, None

    # Walk back over particles so "Ludwig van Beethoven" yields "van Beethoven".
    family_start = len(tokens) - 1
    while family_start > 1 and tokens[family_start - 1].rstrip(".").lower() in NAME_PARTICLES:
        family_start -= 1

    given = " ".join(tokens[:family_start])
    family = " ".join(tokens[family_start:])
    if not given or not family:
        return None, None
    return given, family


def structured_name(given_name, family_name, display_name=None):
    """Build a name record from parts a source stated explicitly."""
    given = normalize_whitespace(given_name) or None
    family = normalize_whitespace(family_name) or None
    return {
        "name": normalize_whitespace(display_name) or join_name(given, family),
        "given_name": given,
        "family_name": family,
        "name_source": STRUCTURED,
    }


def display_name_record(display_name):
    """Build a name record from a rendered string, splitting it if that is safe."""
    name = normalize_whitespace(display_name)
    given, family = split_display_name(name)
    return {
        "name": name,
        "given_name": given,
        "family_name": family,
        "name_source": DISPLAY,
    }
