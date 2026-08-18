"""Reload a harvest from disk for reconciliation.

Reconciliation runs against the raw files an earlier harvest wrote, not against
a fresh fetch: it is a judgement about data already collected, and re-fetching
would make the judgement depend on what the sources happen to say today.
"""

import logging

from src.disambiguate.loader import (
    load_known_works,
    load_openalex_publications,
    load_pubmed_publications,
)
from src.rdf_model.organizations import (
    department_organization,
    organization_from_institution,
)

logger = logging.getLogger(__name__)


def load_publications(faculty, paths):
    """Load every harvested record for one faculty member, from every source."""
    publications = list(load_known_works(faculty, paths["raw_orcid"]))
    publications.extend(load_pubmed_publications(faculty, paths["raw_pubmed"]))
    publications.extend(load_openalex_publications(faculty, paths["raw_openalex"]))
    return publications


def collect_organizations(faculty_list, publications_by_faculty, registry):
    """Register every organization the harvest named, from any source."""
    for faculty in faculty_list:
        registry.add(department_organization(faculty.get("department")))

    for publications in publications_by_faculty.values():
        for publication in publications:
            for coauthor in publication.get("coauthors", []):
                for institution in coauthor.get("institutions", []):
                    registry.add(organization_from_institution(institution))

    return registry
