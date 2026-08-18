"""Decide when two harvested records describe the same publication.

Sources disagree about the same work in predictable ways: DOIs differ in case
and carry version suffixes, figshare deposits repeat an article under a "Data
from ..." title, and punctuation drifts between listings. These are string
variations, not judgement calls, so they are resolved by rule here rather than
by the LLM stage, which keeps the generated graph reproducible across runs.

Both the HTML preview and the RDF converter group records through this module,
so the two consumers can never disagree about what counts as one work.
"""

import logging
import re

logger = logging.getLogger(__name__)

DOI_URL_PREFIXES = ("https://doi.org/", "http://doi.org/", "doi:")

# Repositories mint a new DOI per deposited version: 10.1158/x.22418981.v1.
DOI_VERSION_SUFFIX = re.compile(r"\.v\d+$")

# figshare prefixes a deposit's title with the phrase, so it is not part of the
# work's real title.
DEPOSIT_TITLE_PREFIXES = ("data from ",)

_PUNCTUATION = re.compile(r"[^\w\s]")
_WHITESPACE = re.compile(r"\s+")

# Short titles ("Erratum", "Introduction") repeat across unrelated works, so a
# title alone may only merge records when it is long enough to be distinctive.
TITLE_KEY_MIN_WORDS = 6

# Repository deposits mirror an article rather than being the work of record,
# so they never win primary selection against a real publication.
DEPOSIT_TYPES = ("other", "dataset", "supplementary-materials")


def normalize_doi(doi):
    """Reduce a DOI to its comparable form.

    DOIs are case-insensitive, and sources disagree on case, on the resolver
    prefix, and on version suffixes. Only the comparison key is normalized; the
    displayed and published DOI keeps whatever the source reported.
    """
    if not doi:
        return ""
    normalized = str(doi).strip().lower()
    for prefix in DOI_URL_PREFIXES:
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):]
            break
    normalized = normalized.strip("/")
    return DOI_VERSION_SUFFIX.sub("", normalized)


def normalize_pmid(pmid):
    """Reduce a PubMed identifier to its comparable form."""
    return str(pmid or "").strip()


def normalize_title(title):
    """Reduce a title to a comparable form.

    Strips the deposit prefix, punctuation (which absorbs serial-comma and
    trailing-period differences), and whitespace runs.
    """
    if not title:
        return ""
    normalized = _WHITESPACE.sub(" ", str(title).strip().lower())
    for prefix in DEPOSIT_TITLE_PREFIXES:
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):]
            break
    normalized = _PUNCTUATION.sub(" ", normalized)
    words = _WHITESPACE.sub(" ", normalized).strip().split()
    return " ".join(_collapse_repeated_phrase(words))


def _collapse_repeated_phrase(words):
    """Reduce a title that repeats itself to a single copy of the phrase.

    Some repository deposits are titled by concatenating the article title onto
    itself, sometimes joined by "from": "<title> from <title>". The two halves
    may differ in punctuation, which normalization has already removed.
    """
    for split_index, word in enumerate(words):
        if word != "from":
            continue
        left = words[:split_index]
        right = words[split_index + 1:]
        if left and left == right:
            return left

    half, remainder = divmod(len(words), 2)
    if half and not remainder and words[:half] == words[half:]:
        return words[:half]

    return words


def title_key(title):
    """Return a title's merge key, or an empty string when it is too generic."""
    normalized = normalize_title(title)
    if len(normalized.split()) < TITLE_KEY_MIN_WORDS:
        return ""
    return normalized


def identity_keys(publication):
    """Return every key by which this record can be matched to the same work."""
    keys = []

    doi = normalize_doi(publication.get("doi"))
    if doi:
        keys.append(("doi", doi))

    pmid = normalize_pmid(publication.get("pmid"))
    if pmid:
        keys.append(("pmid", pmid))

    title = title_key(publication.get("title"))
    if title:
        keys.append(("title", title))

    return keys


def is_deposit(publication):
    """Is this record a repository deposit mirroring a published work?"""
    return str(publication.get("type") or "").strip().lower() in DEPOSIT_TYPES


def group_publications(publications):
    """Group records that describe the same work, preserving input order.

    Returns a list of lists. A record matched on any one identifier lends its
    remaining identifiers to the group, so a PMID-only record still joins the
    work a DOI first established.
    """
    groups = []
    group_by_key = {}

    for publication in publications:
        keys = identity_keys(publication)
        group = _find_group(keys, group_by_key)

        if group is None:
            group = [publication]
            groups.append(group)
        else:
            group.append(publication)

        for key in keys:
            group_by_key.setdefault(key, group)

    return groups


def _find_group(keys, group_by_key):
    """Return the group these identifiers already belong to, if any."""
    for key in keys:
        group = group_by_key.get(key)
        if group is not None:
            return group
    return None


def choose_primary(group):
    """Pick the record that best represents the work.

    A published article outranks a repository deposit of it, and a record with a
    DOI outranks one without. Ties break on the normalized DOI so the choice is
    stable no matter which order the harvesters ran in.
    """
    def rank(publication):
        return (
            is_deposit(publication),
            not publication.get("doi"),
            normalize_doi(publication.get("doi")),
        )

    return min(group, key=rank)


def collect_alternate_ids(group, primary):
    """Return the identifiers the group carries beyond the primary record's.

    Deposit and version DOIs are real citable identifiers, so they are kept as
    alternates on the merged work rather than discarded.
    """
    primary_doi = normalize_doi(primary.get("doi"))
    primary_pmid = normalize_pmid(primary.get("pmid"))

    alternate_dois = []
    alternate_pmids = []

    for publication in group:
        doi = publication.get("doi")
        if doi and normalize_doi(doi) != primary_doi and doi not in alternate_dois:
            alternate_dois.append(doi)

        pmid = normalize_pmid(publication.get("pmid"))
        if pmid and pmid != primary_pmid and pmid not in alternate_pmids:
            alternate_pmids.append(pmid)

    return alternate_dois, alternate_pmids


def collect_sources(group):
    """Return every source that reported this work, in encounter order."""
    sources = []
    for publication in group:
        source = publication.get("source")
        if source and source not in sources:
            sources.append(source)
    return sources


def merge_group(group):
    """Fold a group of duplicate records into one publication dict.

    The primary record supplies the displayed fields; the rest contribute their
    identifiers and their provenance.
    """
    primary = choose_primary(group)
    merged = dict(primary)

    alternate_dois, alternate_pmids = collect_alternate_ids(group, primary)
    if alternate_dois:
        merged["alternate_dois"] = alternate_dois
    if alternate_pmids:
        merged["alternate_pmids"] = alternate_pmids

    merged["_sources"] = collect_sources(group)

    if len(group) > 1:
        logger.debug(
            "Merged %d records into work %r (alternate DOIs: %s)",
            len(group),
            merged.get("title", "")[:60],
            alternate_dois,
        )
    return merged


def merge_publications(publications):
    """Collapse duplicate records into one entry per distinct work."""
    merged = [merge_group(group) for group in group_publications(publications)]
    if len(merged) != len(publications):
        logger.info(
            "Merged %d harvested records into %d distinct works",
            len(publications),
            len(merged),
        )
    return merged
