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
