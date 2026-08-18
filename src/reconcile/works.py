"""Decide which per-source work records describe the same publication.

The grouping rules already live in src/identity.py and are shared with the
converter and the preview, so this module does not re-invent them. What it adds
is the part that only matters once matching is a separate phase: saying *why*
two records were linked and *how sure* the pipeline is, so a human can review
the judgement instead of finding it already baked into the graph.
"""

import logging

from src.identity import group_publications, identity_keys

logger = logging.getLogger(__name__)

# How much to trust a link, by the identifier that produced it. A DOI or a PMID
# names a work; a title merely describes one, and titles collide.
MATCH_METHOD_DOI = "doi"
MATCH_METHOD_PMID = "pmid"
MATCH_METHOD_TITLE = "title"

CONFIDENCE_BY_METHOD = {
    MATCH_METHOD_DOI: 1.0,
    MATCH_METHOD_PMID: 1.0,
    MATCH_METHOD_TITLE: 0.75,
}

# Links at or above this confidence are asserted as owl:sameAs. Below it, the
# link is recorded as a reviewable match assertion only, so a title collision
# never silently fuses two different works.
SAME_AS_CONFIDENCE = 1.0

# A single record matched to nothing is not a link and produces no assertion.
MIN_GROUP_SIZE = 2


def match_method(publication):
    """Return the strongest identifier this record can be matched on."""
    keys = dict(identity_keys(publication))
    if MATCH_METHOD_DOI in keys:
        return MATCH_METHOD_DOI
    if MATCH_METHOD_PMID in keys:
        return MATCH_METHOD_PMID
    if MATCH_METHOD_TITLE in keys:
        return MATCH_METHOD_TITLE
    return None


# Strongest identifier first: a link is reported at the strength of the key that
# actually joined the records, never at the strength of a key they merely each
# happen to carry.
MATCH_METHOD_STRENGTH = (MATCH_METHOD_DOI, MATCH_METHOD_PMID, MATCH_METHOD_TITLE)


def group_match_method(group):
    """Return the method that actually joined every member of a group.

    Only a key all members share can be said to have joined them. Two records
    carrying different DOIs were not linked by DOI even though both have one —
    reporting that as a DOI match would assert certainty the evidence does not
    support. Grouping is also transitive, so a group can exist with no key common
    to all of it; that case is reported at the lowest confidence.
    """
    shared = None
    for publication in group:
        keys = set(identity_keys(publication))
        shared = keys if shared is None else (shared & keys)

    shared_methods = {method for method, _ in (shared or set())}
    for method in MATCH_METHOD_STRENGTH:
        if method in shared_methods:
            return method

    return MATCH_METHOD_TITLE


def confidence_for(method):
    """Return the confidence a match method carries."""
    return CONFIDENCE_BY_METHOD.get(method, CONFIDENCE_BY_METHOD[MATCH_METHOD_TITLE])


def sources_in(group):
    """Return the distinct sources represented in a group, in encounter order."""
    sources = []
    for publication in group:
        source = publication.get("source")
        if source and source not in sources:
            sources.append(source)
    return sources


def build_work_matches(publications):
    """Return one match record per group of records describing the same work.

    Records that matched nothing are omitted: there is no link to assert about a
    work only one source reported.
    """
    matches = []
    for group in group_publications(publications):
        if len(group) < MIN_GROUP_SIZE:
            continue

        method = group_match_method(group)
        confidence = confidence_for(method)
        matches.append({
            "members": list(group),
            "method": method,
            "confidence": confidence,
            "sources": sources_in(group),
            "needs_review": confidence < SAME_AS_CONFIDENCE,
        })

    logger.info(
        "Reconciled %d records into %d cross-source work links",
        len(publications),
        len(matches),
    )
    return matches
