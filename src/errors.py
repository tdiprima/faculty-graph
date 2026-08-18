"""Domain errors shared across the pipeline."""


class HarvestError(Exception):
    """A harvest could not be completed.

    Raised instead of returning partial data: a truncated result set that looks
    complete would be written to RDF as authoritative provenance.
    """


class SeedDataError(Exception):
    """The faculty seed list is missing, malformed, or incomplete.

    The seed CSV is the pipeline's only untrusted input; every harvester keys
    on its columns, so it is validated once at load time.
    """
