"""Identify organizations and decide what IRI stands for each one.

An organization arrives from three directions and they do not agree. OpenAlex
supplies a ROR identifier. PubMed supplies a free-text affiliation line. The
faculty seed list supplies a bare department name. Only the first is globally
identified, so only the first gets a globally meaningful IRI.

The rule here: a ROR identifier becomes the subject IRI directly, so two sources
naming the same institution converge on one node without any matching step. An
organization with no ROR gets a locally minted IRI derived from its normalized
name, which is honest about being a local guess and is what the reconciliation
phase will later link to a ROR node.

Free-text affiliation lines are deliberately not minted as organizations. A
string like "Dept of Pathology, Example University, NY 11794, USA" names
several organizations at once, and deciding which is a reconciliation judgement,
not a naming one.
"""

import logging
import re

from src.config import normalize_ror

logger = logging.getLogger(__name__)

_PUNCTUATION = re.compile(r"[^\w\s]")
_WHITESPACE = re.compile(r"\s+")

# Leading articles differ between sources naming one organization ("The
# University of X" against "University of X"), so they are not part of the key.
LEADING_ARTICLES = ("the ",)

# Longest organization name kept in a minted IRI. Names longer than this are
# real but unwieldy; the full name always survives as the node's label.
MAX_NAME_KEY_LENGTH = 80

ORGANIZATION_KIND_ROR = "ror"
ORGANIZATION_KIND_LOCAL = "local"


def normalize_org_name(name):
    """Reduce an organization name to a comparable key.

    Case, punctuation, whitespace runs, and a leading article are all
    presentation rather than identity.
    """
    normalized = _WHITESPACE.sub(" ", str(name or "").strip().lower())
    for article in LEADING_ARTICLES:
        if normalized.startswith(article):
            normalized = normalized[len(article):]
            break
    normalized = _PUNCTUATION.sub(" ", normalized)
    return _WHITESPACE.sub(" ", normalized).strip()


def name_key(name):
    """Return the slug used to mint an IRI for an organization with no ROR."""
    normalized = normalize_org_name(name)
    if not normalized:
        return ""
    return normalized[:MAX_NAME_KEY_LENGTH].strip().replace(" ", "-")


def build_organization(display_name, ror=None, country_code=None, org_type=None):
    """Build an organization record, or None when it has no usable name.

    A malformed ROR is dropped rather than raised on: harvested data is not
    configuration, and one bad identifier in a thousand-work harvest must not
    end the run. The organization survives as a local node instead.
    """
    name = _WHITESPACE.sub(" ", str(display_name or "").strip())
    if not name:
        return None

    canonical_ror = None
    if ror:
        try:
            canonical_ror = normalize_ror(ror)
        except Exception as error:  # ConfigError, but harvest data must not abort the run
            logger.warning("Ignoring malformed ROR %r for %r: %s", ror, name, error)
            canonical_ror = None

    return {
        "name": name,
        "ror": canonical_ror,
        "country_code": (country_code or None),
        "type": (org_type or None),
        "key": canonical_ror or f"name:{name_key(name)}",
        "kind": ORGANIZATION_KIND_ROR if canonical_ror else ORGANIZATION_KIND_LOCAL,
    }


def organization_from_institution(institution):
    """Build an organization record from a harvested institution value.

    Accepts either the full dict OpenAlex supplies or a bare display name,
    because older harvest files on disk carry the bare form.
    """
    if isinstance(institution, str):
        return build_organization(institution)
    if not isinstance(institution, dict):
        return None
    return build_organization(
        institution.get("display_name"),
        ror=institution.get("ror"),
        country_code=institution.get("country_code"),
        org_type=institution.get("type"),
    )


def department_organization(department_name):
    """Build an organization record for a seed-list department.

    A department name is local by definition — ROR registers institutions, not
    their internal units — so this never carries a ROR identifier.
    """
    return build_organization(department_name)


class OrganizationRegistry:
    """Collect the distinct organizations seen while converting one document.

    Records that name the same organization are folded together, with a later
    record filling in fields an earlier one left empty. The registry preserves
    first-seen order so generated Turtle is stable across runs.
    """

    def __init__(self):
        self._by_key = {}

    def add(self, organization):
        """Register an organization and return the stored record for it."""
        if not organization:
            return None

        existing = self._by_key.get(organization["key"])
        if existing is None:
            self._by_key[organization["key"]] = dict(organization)
            return self._by_key[organization["key"]]

        for field in ("country_code", "type"):
            if not existing.get(field) and organization.get(field):
                existing[field] = organization[field]
        return existing

    def all(self):
        """Return every registered organization, in first-seen order."""
        return list(self._by_key.values())

    def __len__(self):
        return len(self._by_key)
