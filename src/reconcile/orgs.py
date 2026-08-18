"""Decide which locally identified organizations are known institutions.

Harvesting mints a local IRI for any organization a source named without a ROR
identifier. Reconciliation is where those local nodes are matched to the ROR
nodes that name the same institution — the "one source says Example University
University, another gives the ROR" problem, resolved as an explicit, reviewable
assertion rather than at ingest.

Matching here is offline: a local organization is linked to a ROR organization
already present in the harvest whose name it shares. Querying ror.org for
institutions absent from the harvest is a further step, deliberately not taken
here, because a network lookup belongs behind its own boundary and its own
consent.
"""

import logging

from src.rdf_model.organizations import (
    ORGANIZATION_KIND_LOCAL,
    ORGANIZATION_KIND_ROR,
    normalize_org_name,
)

logger = logging.getLogger(__name__)

MATCH_METHOD_EXACT_NAME = "exact-name"

# An exact normalized-name match between two organizations in the same harvest
# is strong but not certain: "School of Medicine" is a real name at hundreds of
# universities. It stays below the threshold that would assert owl:sameAs.
CONFIDENCE_EXACT_NAME = 0.9

SAME_AS_CONFIDENCE = 1.0

# Names too generic to identify an institution on their own. A local node with
# one of these is left unreconciled rather than attached to whichever registered
# organization happens to share the string.
AMBIGUOUS_NAMES = frozenset({
    "school of medicine",
    "medical school",
    "department of medicine",
    "school of nursing",
    "college of arts and sciences",
    "graduate school",
    "the graduate center",
    "research institute",
    "cancer center",
    "unknown",
})


def is_ambiguous(name):
    """Is this name too generic to identify one institution?"""
    return normalize_org_name(name) in AMBIGUOUS_NAMES


def index_by_name(organizations):
    """Index ROR-identified organizations by their normalized name.

    A name claimed by two different registered organizations is dropped from the
    index: it cannot identify either of them, and guessing would be worse than
    leaving the local node unmatched.
    """
    candidates = {}
    contested = set()

    for organization in organizations:
        if organization.get("kind") != ORGANIZATION_KIND_ROR:
            continue
        key = normalize_org_name(organization["name"])
        if not key:
            continue
        existing = candidates.get(key)
        if existing is not None and existing["ror"] != organization["ror"]:
            contested.add(key)
            continue
        candidates[key] = organization

    for key in contested:
        logger.warning(
            "Name %r is claimed by more than one registered organization; "
            "leaving it unreconciled",
            key,
        )
        candidates.pop(key, None)

    return candidates


def build_organization_matches(organizations):
    """Return one match record per local organization that names a known one.

    Local organizations with no match are omitted; they stay local nodes, which
    is the honest outcome for an organization nothing in the harvest identifies.
    """
    by_name = index_by_name(organizations)
    matches = []

    for organization in organizations:
        if organization.get("kind") != ORGANIZATION_KIND_LOCAL:
            continue

        name = organization["name"]
        if is_ambiguous(name):
            logger.debug("Skipping ambiguous organization name %r", name)
            continue

        target = by_name.get(normalize_org_name(name))
        if target is None:
            continue

        matches.append({
            "local": organization,
            "target": target,
            "method": MATCH_METHOD_EXACT_NAME,
            "confidence": CONFIDENCE_EXACT_NAME,
            "needs_review": CONFIDENCE_EXACT_NAME < SAME_AS_CONFIDENCE,
        })

    logger.info(
        "Reconciled %d of %d organizations to a registered identifier",
        len(matches),
        len(organizations),
    )
    return matches
