# Open Questions

Questions to raise at the next review. Answered ones are kept with their answers
rather than deleted, so that a settled question stays settled and does not get
re-opened from memory six months from now.

## Answered

**Which ontology/vocabulary should we reuse (VIVO, Schema.org, BIBO, custom)?**
Custom `fg:` terms, defined in `ontology/fg.ttl`, aligned to BIBO, Dublin Core,
FOAF, PROV-O, W3C Org, VIVO, and schema.org at the strength the semantics
support. A custom model is acceptable provided it is specified well enough to
ETL cleanly onto whatever the ontology group standardizes — which is why the
alignment ships as machine-checkable axioms rather than as prose. See decision
013 and `modeling-rules.md` rule 10.

**Should rejected matches live in the same named graph or a separate review
graph?** Neither, as it turns out. A rejection is not RDF at all: it lives in
`data/seed/reviews.yaml` and is applied at conversion time by
`src/review/manager.py`, so a rejected work never reaches the graph and a
re-harvest cannot resurrect it. What *does* get a separate graph is the
pipeline's own conclusions — `reconciliation.ttl` holds the cross-source links
and nothing else, so a bad merge is withdrawn by dropping one file. See decision
011 and rules 5 and 7.

**What counts as authoritative besides ORCID?** Today: a human. A publication
found by ORCID-iD search is `authoritative` and one found by name search is
`candidate` (`src/provenance.py`), and a reviewer's decision in `reviews.yaml`
overrides both to `verified` or `rejected`. No other source confers authority.

**How much raw source data should we retain?** All of it. Every response is kept
per source under `data/raw/`, per-source graphs under
`data/output/rdf/by-source/` say only what that source reported, and text the
parser could not decompose is kept verbatim rather than dropped — a PubMed
affiliation line naming three organizations is stored as `fg:affiliationRaw` for
reconciliation to interpret later. See rule 9.

**What network access should the SPARQL endpoint have?** VPN-only for the
prototype, no public access until the data has been reviewed. Recorded in
`deployment.md`.

**Who approves publication matches, and who approves generated faculty page
drafts?** One person: whoever runs the pipeline. This is not a workflow question
until someone else is involved, and the mechanism already exists — `reviews.yaml`
records who decided and when.

## Still Open

These are the ones that need an answer from outside this repo.

1. **Is institution-wide harvesting in scope**, or should the roster remain the
   discovery mechanism with everything else treated as enrichment? This is the
   one question that changes the shape of the pipeline rather than its settings;
   see "Demote the Seed CSV" in `roadmap.md`.
2. **For the TCI work, is the scope an institution, a grant, a topic, or a
   cohort?** The answer determines what replaces the roster as the harvest entry
   point, and it is the difference between this pipeline being reusable and being
   rewritten.
3. **How much unreviewed data is acceptable in the published graph?**
   Institution-wide harvesting means most assertions will never be seen by a
   human. The current model can express that honestly — every assertion carries
   its status — but nothing decides what may be published at which status.
4. **Should collaboration counts include all co-authors, or only those with a
   resolvable ROR ID?** Counting only ROR-identified authors is defensible and
   undercounts; counting all of them means counting affiliation strings that were
   never reconciled.
5. **Who is the first real consumer** — a department website, internal reporting,
   or visualizations? Still unanswered, and it decides whether the merged
   `faculty-all.ttl` view or the per-source graphs are the primary product.
