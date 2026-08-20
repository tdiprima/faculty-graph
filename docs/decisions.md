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
**Decision:** Emit `<http://example.org/faculty-graph/data/faculty/fac-001>` rather than `fgdata:faculty/fac-001`.
**Reason:** A Turtle prefixed name cannot contain an unescaped `/` (the `PN_LOCAL` production excludes it). The pipeline shipped the prefixed form, and every generated file failed to parse: `riot --validate` reported `Not a valid token for an RDF term: [SLASH]`. Nothing would have loaded into Fuseki or QLever. Escaping as `fgdata:faculty\/fac-001` is legal but easy to get wrong by hand; absolute IRIs are unambiguous. `data/output/rdf/example.ttl` uses the same form, and the test suite parses all generated Turtle with rdflib so this cannot regress silently.

## 006 - Assertion status derived from search method, in one place

**Date:** 2026-08-18
**Decision:** `src/provenance.py` owns the rule that an ORCID-iD search yields `authoritative` and a name search yields `candidate`. Harvesters and the disambiguation loader both call it.
**Reason:** The rule was duplicated inline in three harvest clients. Raw files on disk do not record assertion status, so the disambiguation stage re-derived it separately and drifted: it filtered for `candidate` against records that had never been tagged, matched nothing, and sent zero candidates to the LLM while reporting success. A single shared function means a record reloaded from `data/raw/` carries the status the harvester gave it.

## 007 - A partial harvest is an error, not a result

**Date:** 2026-08-18
**Decision:** `HarvestError` is raised when an OpenAlex cursor walk cannot finish. The harvest for that faculty member yields nothing and writes no raw file.
**Reason:** The pagination loop used to `break` on a network failure and return the pages it had, which is indistinguishable from a complete result. Those truncated records were then written into the graph as `authoritative` provenance. For a project whose whole point is trustworthy provenance, silently losing publications is worse than failing one person's harvest. Failures are logged per faculty member so one bad response does not abort the run.

## 008 - A truncated LLM answer is an error, not a "no"

**Date:** 2026-08-18
**Decision:** `src/disambiguate/scorer.py` sends `think: False` and `format: "json"`, budgets `MAX_RESPONSE_TOKENS = 500`, and treats `done_reason == "length"` or an empty response body as a logged failure that returns `None`.
**Reason:** A thinking-capable model spent the whole 300-token budget on hidden reasoning and returned `response: ""`. The JSON decode then failed with `Expecting value: line 1 column 1 (char 0)`, which reads like a malformed answer rather than a missing one — the operator has no way to tell "the model judged this a non-match" from "the model never got to answer." Naming the truncation in the error message says which knob to turn.

## 009 - Organizations are identified by their ROR IRI

**Date:** 2026-08-18
**Decision:** When a ROR ID is known, `https://ror.org/{id}` *is* the subject IRI of the organization — no locally minted IRI, no `owl:sameAs` bridge. Names are normalized into a local IRI only when no ROR is available. A malformed ROR arriving in harvest data logs a warning and degrades to a local IRI; a malformed ROR in *configuration* fails at startup.
**Reason:** Two sources spelling "Example University" differently converge for free if both carry the same ROR, and any consumer outside this project resolves the same IRI to the same registry record. Minting our own IRI and linking it would mean every consumer has to follow the link to learn anything. The asymmetric handling of bad IDs follows from where the value came from: harvest data is untrusted and one bad record must not abort a run, while configuration is ours and a typo there silently mislabels every collaboration in the graph.

## 010 - Institution identity lives in .env, not in the queries

**Date:** 2026-08-18
**Decision:** `INSTITUTION_ROR` (comma-separated, so an institution with several registered entries counts as one "us") and `FG_BASE_URI` are read from the environment at runtime. Files in `queries/` are templates using `{{PLACEHOLDER}}`; `src/queries.py` substitutes at generation time and raises `ConfigError` on an unknown placeholder, an empty value, or any placeholder still standing after substitution.
**Reason:** The collaboration queries hardcoded Example University's ROR in a `VALUES` clause and the rest hardcoded the default namespace, so adopting the pipeline meant hand-editing eleven `.rq` files and keeping them in sync with `.env`. Failing loudly on an unresolved placeholder matters more than it sounds: a SPARQL query with a leftover `{{...}}` is a syntax error, but one where a placeholder resolved to an empty string is *valid* and quietly returns the wrong rows. Note that Example University (`abc123456`) and Example University Hospital (`abc123456`) are separate ROR records; listing only the first reports the hospital as an outside collaborator.

## 011 - Reconciliation is a separate phase with reviewable assertions

**Date:** 2026-08-18
**Decision:** Cross-source linking moved out of conversion into `src/reconcile/`, run by `--reconcile` and written to its own `reconciliation.ttl`. Each link is an `fg:MatchAssertion` carrying `fg:matchMethod` and `fg:matchConfidence`; `owl:sameAs` is emitted only at `SAME_AS_CONFIDENCE = 1.0`.
**Reason:** The feedback asked for each source's data to stay organized as harvested and be reconciled later. Merging inline during conversion left no artifact to review — a wrong merge could only be found by reading the merged output and inferring what had happened. A standalone file of assertions can be queried (`pending-reconciliation-review.rq`), corrected, and regenerated without re-harvesting. Reserving `owl:sameAs` for certainty keeps a reasoner from propagating a guess: `owl:sameAs` is not a hint, it licenses every statement about one node to be inferred about the other.

## 012 - A match method must be shared by every member of the group

**Date:** 2026-08-18
**Decision:** `group_match_method` intersects `identity_keys` across all members and reports the strongest key *present in the intersection*, not the strongest key any member carries.
**Reason:** The first implementation reported the strongest identifier each record happened to have. Two records with **different** DOIs that grouped on a matching title were therefore reported as a DOI match at confidence 1.0 — which under decision 011 emits `owl:sameAs` between two genuinely different works, the single worst thing this pipeline can do. Caught by a test before it ever ran on real data; the test remains as the regression guard.

## 013 - The fg: vocabulary is defined in a file, not implied by output

**Date:** 2026-08-18
**Decision:** `ontology/fg.ttl` declares every `fg:` class and property with domain, range, and alignment axioms onto BIBO, Dublin Core, FOAF, PROV-O, W3C Org, and VIVO. Properties shared by two classes get an `owl:unionOf` domain. `docs/modeling-rules.md` states the commitments the ontology cannot express.
**Reason:** The feedback accepts a custom model provided it is well-specified enough to ETL cleanly onto whatever the ontology group standardizes. Terms that exist only as strings in a converter are not specified — the mapping would have to be reverse-engineered from sample output, which finds the common cases and misses the rare ones. The `owl:unionOf` detail is worth stating because it is an easy and silent mistake: two `rdfs:domain` statements mean a subject is in *both* classes, so writing them out would have asserted that every publication assertion is also an authorship.

## 014 - QLever is the store, and it indexes the merged view only

**Date:** 2026-08-20
**Decision:** QLever is the deployment target. Its index is built from `faculty-all.ttl` alone — the canonical merged view. `by-source/*.ttl` and `reconciliation.ttl` stay audit and debug artifacts, outside the production index. Indexing them instead is a documented, non-default profile (`docs/qlever-setup.md`, "Which files to index"). Fuseki remains supported but optional.
**Reason:** QLever indexes into a single default graph, which is what makes it a clean fit: the queries in `queries/` carry no `GRAPH` clause, so they work against it unchanged, while on Fuseki a named-graph load leaves them returning zero rows unless `tdb2:unionDefaultGraph` is set.

That same single graph is why the two file sets cannot both be indexed. `faculty-all.ttl` merges what the per-source graphs state separately, so indexing both puts the merged facts in twice under different subject IRIs. Nothing about that is *wrong* — the IRIs are distinct and the reconciliation links relate them — but every count, join, and aggregate would then have to be written with the duplication in mind, and one query that forgets inflates its numbers silently. A canonical index whose triples mean what they appear to mean is worth more than provenance visibility we can get another way.

The reason this is a decision and not a default is that provenance is a real requirement of this project, and this choice defers it rather than dropping it. When "who claimed what?" needs to be queryable rather than auditable, the answer is Fuseki named graphs or a QLever quads representation — not compromising the canonical index. Decision 011 already keeps the per-source graphs and their links as standalone files, regenerable by `--reconcile` without re-harvesting, so nothing is lost by leaving them out of the index today.
