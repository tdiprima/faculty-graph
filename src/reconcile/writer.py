"""Write reconciliation links as their own graph.

Nothing here restates what a source said. This graph contains only the
pipeline's own conclusions about which records refer to the same thing, each one
carrying the method and confidence behind it. Because the conclusions live in
their own file, undoing them is a matter of not loading it.
"""

import logging
from datetime import datetime, timezone
from pathlib import Path

from src.rdf_model.converter import (
    PREFIXES,
    build_data_iri,
    build_organization_uri,
    build_source_work_uri,
    build_work_uri,
    escape_turtle_string,
    sanitize_uri_part,
    work_key_for,
)
from src.reconcile.orgs import build_organization_matches
from src.reconcile.works import build_work_matches

logger = logging.getLogger(__name__)

RECONCILIATION_FILENAME = "reconciliation.ttl"

# Links at or above this confidence are additionally asserted as owl:sameAs, so
# a triple store treats the nodes as one. Below it, the match assertion stands
# alone and a human decides.
SAME_AS_CONFIDENCE = 1.0


def build_match_uri(kind, key):
    """Build the IRI for one match assertion."""
    return build_data_iri("match", kind, sanitize_uri_part(key))


def work_match_to_turtle(match, canonical_uri, timestamp):
    """Generate Turtle for one cross-source work link."""
    sections = []

    for publication in match["members"]:
        source = publication.get("source", "unknown")
        source_work_uri = build_source_work_uri(source, publication)
        match_uri = build_match_uri(
            "work",
            f"{sanitize_uri_part(str(source).lower())}-{work_key_for(publication)}",
        )

        lines = [
            f"{match_uri}",
            f"    a                   fg:MatchAssertion ;",
            f"    fg:matchedRecord    {source_work_uri} ;",
            f"    fg:matchedTo        {canonical_uri} ;",
            f'    fg:matchMethod      "{escape_turtle_string(match["method"])}" ;',
            f'    fg:matchConfidence  "{match["confidence"]}"^^xsd:decimal ;',
            f"    fg:source           fg:{sanitize_uri_part(str(source))} ;",
            f'    fg:reconciledAt     "{timestamp}"^^xsd:dateTime ;',
        ]
        if match["needs_review"]:
            lines.append(f"    fg:needsHumanReview true ;")

        lines[-1] = lines[-1].rstrip(" ;") + " ."
        sections.append("\n".join(lines))

        if match["confidence"] >= SAME_AS_CONFIDENCE:
            sections.append(f"{source_work_uri} owl:sameAs {canonical_uri} .")

    return "\n\n".join(sections)


def organization_match_to_turtle(match, timestamp):
    """Generate Turtle for one organization link."""
    local_uri = build_organization_uri(match["local"])
    target_uri = build_organization_uri(match["target"])
    match_uri = build_match_uri("org", match["local"]["key"])

    lines = [
        f"{match_uri}",
        f"    a                   fg:MatchAssertion ;",
        f"    fg:matchedRecord    {local_uri} ;",
        f"    fg:matchedTo        {target_uri} ;",
        f'    fg:matchMethod      "{escape_turtle_string(match["method"])}" ;',
        f'    fg:matchConfidence  "{match["confidence"]}"^^xsd:decimal ;',
        f'    fg:reconciledAt     "{timestamp}"^^xsd:dateTime ;',
    ]
    if match["needs_review"]:
        lines.append(f"    fg:needsHumanReview true ;")

    lines[-1] = lines[-1].rstrip(" ;") + " ."
    sections = ["\n".join(lines)]

    if match["confidence"] >= SAME_AS_CONFIDENCE:
        sections.append(f"{local_uri} owl:sameAs {target_uri} .")

    return "\n\n".join(sections)


def build_reconciliation_turtle(publications, organizations):
    """Build the complete reconciliation graph as a Turtle document."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    sections = [PREFIXES, "# ── Cross-source work links ──"]

    work_matches = build_work_matches(publications)
    for match in work_matches:
        canonical_uri = build_work_uri(match["members"][0])
        sections.append(work_match_to_turtle(match, canonical_uri, timestamp))

    sections.append("# ── Organization links ──")
    organization_matches = build_organization_matches(organizations)
    for match in organization_matches:
        sections.append(organization_match_to_turtle(match, timestamp))

    return "\n\n".join(sections) + "\n", work_matches, organization_matches


def write_reconciliation(publications, organizations, output_dir):
    """Write the reconciliation graph and return its path."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    turtle, work_matches, organization_matches = build_reconciliation_turtle(
        publications, organizations
    )

    path = output_dir / RECONCILIATION_FILENAME
    with open(path, "w", encoding="utf-8") as outfile:
        outfile.write(turtle)

    needs_review = sum(
        1 for match in work_matches + organization_matches if match["needs_review"]
    )
    logger.info(
        "Wrote %s: %d work links, %d organization links, %d need human review",
        path,
        len(work_matches),
        len(organization_matches),
        needs_review,
    )
    return path
