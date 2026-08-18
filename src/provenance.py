"""Provenance tagging shared by every harvest source.

A publication found through an ORCID iD is authoritative: the identifier binds
the work to the person. A publication found by name search is only a candidate
until disambiguation or human review confirms it.
"""

SEARCH_METHOD_ORCID = "orcid"
SEARCH_METHOD_NAME = "name"

STATUS_AUTHORITATIVE = "authoritative"
STATUS_CANDIDATE = "candidate"

_STATUS_BY_SEARCH_METHOD = {
    SEARCH_METHOD_ORCID: STATUS_AUTHORITATIVE,
    SEARCH_METHOD_NAME: STATUS_CANDIDATE,
}


def status_for_search_method(search_method):
    """Map a search method to the assertion status it produces."""
    if search_method not in _STATUS_BY_SEARCH_METHOD:
        raise ValueError(f"Unknown search method: {search_method!r}")
    return _STATUS_BY_SEARCH_METHOD[search_method]


def search_method_for_faculty(faculty):
    """Return the search method a harvester uses for this faculty member.

    ORCID search when the faculty member has an iD, name search otherwise.
    """
    if faculty.get("orcid", "").strip():
        return SEARCH_METHOD_ORCID
    return SEARCH_METHOD_NAME


def tag_publications(publications, source, search_method):
    """Stamp source provenance onto parsed publications. Modifies in place.

    Harvest clients and the offline loader both call this, so raw files
    reloaded from disk carry the same status the harvester assigned.
    """
    status = status_for_search_method(search_method)
    for publication in publications:
        publication["source"] = source
        publication["assertion_status"] = status
        publication["search_method"] = search_method
    return publications
