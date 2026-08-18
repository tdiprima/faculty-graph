# Architectural Decisions

Record decisions here so future-you knows why things are the way they are.

## 001 - Start with ORCID as first source

**Date:** 2026-08-18
**Decision:** ORCID is the first harvested source.
**Reason:** Boss considers ORCID authoritative. Provides stable identifiers that help disambiguate PubMed and OpenAlex later.

## 002 - Use Turtle as primary RDF serialization

**Date:** 2026-08-18
**Decision:** Use Turtle (.ttl) for RDF output.
**Reason:** Human-readable, widely supported, easy to hand-edit for testing.

## 003 - Assertion-based provenance model

**Date:** 2026-08-18
**Decision:** Every publication-faculty link is wrapped in an assertion that tracks source, status, timestamp, and reviewer.
**Reason:** Must never overwrite human corrections when re-harvesting. Assertion statuses (candidate, verified, rejected, authoritative) let the pipeline and humans coexist.

## 004 - Seed list as CSV

**Date:** 2026-08-18
**Decision:** Faculty seed list stored as simple CSV in data/seed/faculty.csv.
**Reason:** Easy to edit, version, and extend. No tooling overhead.

## 005 - Node IRIs written in full, not as prefixed names

**Date:** 2026-08-18
**Decision:** Emit `<http://example.org/faculty-graph/data/faculty/bmi-001>` rather than `fgdata:faculty/bmi-001`.
**Reason:** A Turtle prefixed name cannot contain an unescaped `/` (the `PN_LOCAL` production excludes it). The pipeline shipped the prefixed form, and every generated file failed to parse: `riot --validate` reported `Not a valid token for an RDF term: [SLASH]`. Nothing would have loaded into Fuseki or QLever. Escaping as `fgdata:faculty\/bmi-001` is legal but easy to get wrong by hand; absolute IRIs are unambiguous. `data/output/rdf/example.ttl` uses the same form, and the test suite parses all generated Turtle with rdflib so this cannot regress silently.

## 006 - Assertion status derived from search method, in one place

**Date:** 2026-08-18
**Decision:** `src/provenance.py` owns the rule that an ORCID-iD search yields `authoritative` and a name search yields `candidate`. Harvesters and the disambiguation loader both call it.
**Reason:** The rule was duplicated inline in three harvest clients. Raw files on disk do not record assertion status, so the disambiguation stage re-derived it separately and drifted: it filtered for `candidate` against records that had never been tagged, matched nothing, and sent zero candidates to the LLM while reporting success. A single shared function means a record reloaded from `data/raw/` carries the status the harvester gave it.

## 007 - A partial harvest is an error, not a result

**Date:** 2026-08-18
**Decision:** `HarvestError` is raised when an OpenAlex cursor walk cannot finish. The harvest for that faculty member yields nothing and writes no raw file.
**Reason:** The pagination loop used to `break` on a network failure and return the pages it had, which is indistinguishable from a complete result. Those truncated records were then written into the graph as `authoritative` provenance. For a project whose whole point is trustworthy provenance, silently losing publications is worse than failing one person's harvest. Failures are logged per faculty member so one bad response does not abort the run.
