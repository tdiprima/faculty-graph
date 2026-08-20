# Roadmap: Responding to Review Feedback

Source: recorded feedback in `Wow.txt`. This document restates each concern as a
concrete modeling requirement, records where the current code falls short, and
proposes a phased plan.

## Summary of the Feedback

1. **Do not make the model person-roster-centric.** The same pipeline must serve
   other engagements (TCI work), so nothing should assume "a fixed list of our
   people" is the root of the graph.
2. **Cross-institution collaboration is a first-class product.** Showing that a
   Example University researcher published with MIT, Rensselaer, or Princeton is as
   valuable as the publication record itself.
3. **Keep all accurate data.** Journal volume, issue, and pages are explicitly
   wanted. More detail is never a problem; subsets can be derived later.
4. **Model at "planetary scale."** A department is meaningless on its own — it
   belongs to an institute, which belongs to a university. Model the hierarchy.
5. **Use ROR IRIs** (<https://ror.org>) to identify institutions, while accepting
   that one source says "Example University" and another gives a ROR ID.
6. **Keep each source's data organized as harvested. Reconcile in a later phase.**
   Do not try to homogenize everything at ingest time.
7. **Do not mush fields together.** Family name and given name must stay separate;
   once concatenated they cannot be reliably pulled apart.
8. **Expect external ontology alignment.** A custom model is acceptable provided
   it is well-specified enough to ETL cleanly onto whatever standard emerges from
   the ontology group's "minimal set of terms for library-type information."

## Where the Code Stood at Review Time

This table is a snapshot taken *before* the phases below were carried out. It is
kept because the plan only makes sense against the state it was written for; see
"Where the Code Stands Now" underneath for what changed. Evidence cites function
names rather than line numbers, which rot.

| # | Concern | Status | Evidence |
|---|---|---|---|
| 1 | Not roster-centric | **Not met** | `convert_all_to_rdf` (`src/rdf_model/converter.py`) keys the entire graph by `faculty_id` from the seed CSV. A person absent from `data/seed/faculty.csv` cannot appear as anything but an unlinked co-author. |
| 2 | Collaboration visible | **Not met** | `_extract_coauthors` (`src/harvest_openalex/parser.py`) does collect each author's institutions, but `coauthor_to_turtle` (`src/rdf_model/converter.py`) emits only name and ORCID. The institution list is dropped before it reaches RDF. PubMed affiliations are never parsed at all. |
| 3 | Volume / issue / pages | **Not met** | No parser extracts them. PubMed XML carries `Journal/JournalIssue/Volume`, `Issue`, and `Pagination/MedlinePgn` in responses we already fetch and discard. |
| 4 | Organizational hierarchy | **Not met** | Department is a bare string literal on the person: `fg:department "Biomedical Informatics"` (`src/rdf_model/converter.py`). No university, no institute, no containment. |
| 5 | ROR identifiers | **Not met** | ROR appears nowhere in the codebase. OpenAlex returns a ROR ID on every institution object we currently discard. |
| 6 | Per-source organisation, later reconciliation | **Partly met** | Good: raw responses are kept per source under `data/raw/`, and every harvested record emits its own `fg:PublicationAssertion` with `fg:source` and `prov:wasAttributedTo`, so provenance survives. Gap: work merging happens inline during conversion (`merge_group`, then in the converter's merge path), so reconciliation is not a separately runnable, separately reviewable phase. |
| 7 | Fields kept separate | **Not met** | `_parse_authors` (`src/harvest_pubmed/parser.py`) reads `LastName` and `ForeName` as distinct XML elements and then concatenates them into one string, which is precisely the loss the feedback warns about. Only `foaf:name` is emitted. |
| 8 | Mappable to a standard | **Partly met** | Standard vocabularies are already used where they fit (`bibo`, `dcterms`, `foaf`, `prov`). Gap: the `fg:` terms are not defined anywhere — there is no ontology file stating what `fg:PublicationAssertion` means or what its domain and range are, which is what an ETL onto another model would need. |

## Where the Code Stands Now

All four phases below are complete. Concern by concern:

| # | Concern | Now | Where |
|---|---|---|---|
| 1 | Not roster-centric | **Still open** | The graph is still keyed by `faculty_id` from the seed CSV. Organizations and co-authors are now first-class, so the structure no longer *requires* a roster, but the entry point does. See "Demote the Seed CSV" below — proposed, not decided. |
| 2 | Collaboration visible | **Met** | `fg:Authorship` links work, person, and organization. `queries/collaborating-institutions.rq` and `collaborators-by-institution.rq` answer it directly. |
| 3 | Volume / issue / pages | **Met** | `bibo:volume`, `bibo:issue`, `bibo:pageStart` / `bibo:pageEnd` alongside the printed `bibo:pages`, plus ISSN, from `src/harvest_pubmed/parser.py` and `src/harvest_openalex/parser.py`. |
| 4 | Organizational hierarchy | **Partly met** | `org:subOrganizationOf` links department to institution. Institutes, schools, and colleges between them are still not modelled — recorded as a known gap in `modeling-rules.md`. |
| 5 | ROR identifiers | **Met** | A known ROR IRI *is* the organization's subject IRI (decision 009). Configured per deployment via `INSTITUTION_ROR`. Not met: looking up a ROR for an organization absent from the harvest, which needs a network boundary of its own. |
| 6 | Per-source organisation, later reconciliation | **Met** | `--reconcile` reads `by-source/*.ttl` and writes only links, into `reconciliation.ttl` (decision 011). |
| 7 | Fields kept separate | **Met** | `src/names.py`; a split of a rendered display name is labelled a guess with `fg:nameSource`, and no guess is made where the form is ambiguous. |
| 8 | Mappable to a standard | **Met** | `ontology/fg.ttl`, with `tests/test_ontology.py` failing on a term that is emitted but undefined or defined but unused. |


## Plan

The phases are ordered so that each one is useful on its own, and so that the
cheap fixes that unblock the most visible request — collaboration — come first.

### Phase 1 — Stop discarding data at the parser boundary — **done**

No modeling decisions required; these are fields we already receive and throw away.

1. **Split personal names.** Add `family_name` and `given_name` to every author
   record from all three parsers, keeping the joined `name` as a display
   convenience. Emit `foaf:familyName` and `foaf:givenName` alongside `foaf:name`.
2. **Capture affiliations.** Parse `AffiliationInfo/Affiliation` from PubMed and
   keep the OpenAlex institution objects whole — display name, ROR ID, and country
   code — instead of reducing them to display names.
3. **Capture bibliographic detail.** Add volume, issue, pages, and ISSN to the
   publication record from PubMed and OpenAlex, and emit them as `bibo:volume`,
   `bibo:issue`, `bibo:pageStart` / `bibo:pageEnd`.
4. **Emit an author position.** Record each author's ordinal on the work, plus the
   first-author and corresponding-author flags OpenAlex provides.

At the end of this phase the raw files and the parsed records carry everything
needed for Phase 2, even though the graph shape has not changed much.

### Phase 2 — Model organizations as first-class resources — **done**

This is the phase that answers "show that we work with MIT."

1. **Introduce `fg:Organization`**, identified by its ROR IRI
   (`https://ror.org/abc123456` for Example University) whenever a ROR ID is known, and
   by a local minted IRI when it is not.
2. **Model containment** with `org:subOrganizationOf` (W3C Org ontology, a better
   fit here than inventing `fg:` terms): department is a sub-organization of an
   institute or college, which is a sub-organization of a university.
3. **Model affiliation as a relationship, not an attribute.** Replace the
   `fg:department` string literal with a link from the person to an organization
   resource. Keep the original source string on the relationship so an unmatched
   affiliation is never silently lost.
4. **Attach affiliations to authorship, not just to people.** An author's
   institution is a fact about that author *on that paper* at that time. Model an
   `fg:Authorship` node linking work, person, organization, and position. This is
   what makes "which institutions co-authored this paper" a one-hop query and
   makes the collaboration report fall out directly.
5. **Derive a collaboration view.** Add a SPARQL query under `queries/` that
   returns, per external institution, the count of works co-authored with our
   institution. This is the deliverable the feedback is actually asking for.

### Phase 3 — Make reconciliation an explicit pipeline phase — **done**, except the ROR API lookup

This matches the "keep it per source, connect it later" strategy.

1. **Separate harvest output from reconciled output.** Write one graph per source
   (`data/output/rdf/by-source/pubmed.ttl`, and so on) containing only what that
   source asserted, with no cross-source merging.
2. **Add a reconcile stage** (`--reconcile`) that reads the per-source graphs and
   emits only linking assertions — `owl:sameAs` or a reviewable
   `fg:MatchAssertion` — into a separate graph. Existing work-merge logic in
   `src/identity.py` moves here rather than running inside the converter.
3. **Reconcile organizations, not just works.** The "Example University"
   string versus the ROR IRI problem is exactly a reconciliation task: string
   match, then ROR API lookup, then a match assertion with a confidence and a
   source. Reuse the review and confidence machinery that already exists for
   publication disambiguation.
4. **Keep every merge reversible.** Because links live in their own graph, a bad
   reconciliation is dropped by reloading one file, not by re-harvesting.

### Phase 4 — Write down the ontology — **done**

Needed before the ontology group's discussion, so we arrive with something
concrete rather than a description.

1. **Publish `ontology/fg.ttl`** defining every `fg:` term with `rdfs:label`,
   `rdfs:comment`, `rdfs:domain`, and `rdfs:range`.
2. **Record alignment axioms** to the vocabularies most likely to come up —
   BIBO, FaBiO, VIVO, Dublin Core, PROV-O, W3C Org, schema.org — as
   `rdfs:subClassOf` / `owl:equivalentProperty` statements. The claim "our custom
   model maps cleanly onto yours" then ships as machine-checkable assertions.
3. **Document the modeling rules** we are committing to: identifiers are never
   concatenated, every assertion carries its source, and every locally minted IRI
   states what external identifier it stands for.

### Phase 5 — Make institution identity configurable — **done**

Not in the original plan; it surfaced while doing Phase 2, when the collaboration
queries turned out to need a hardcoded ROR to say who "we" are.

1. **Read institution identity from the environment.** `INSTITUTION_ROR` accepts
   several comma-separated RORs, because one institution can hold more than one
   registered entry and a paper shared between two of them is internal, not a
   collaboration.
2. **Turn `queries/` into templates.** Placeholders are resolved at generation
   time from the same configuration the pipeline runs on, so pointing the
   pipeline at a different institution is an `.env` edit rather than a sweep
   through eleven `.rq` files.
3. **Fail loud on an unresolved placeholder.** A leftover `{{...}}` is a SPARQL
   syntax error, but a placeholder that resolved to an empty string produces a
   *valid* query returning the wrong rows.

See decision 010 in `decisions.md`.


## Recommendation: Demote the Seed CSV

The current pipeline treats `data/seed/faculty.csv` as the definitive list of who
exists. Everything is harvested per roster row, and the graph is written per
`faculty_id`. That conflicts with the feedback in three ways: it is inherently
roster-centric, it makes an external collaborator structurally second-class, and
it does not transfer to an engagement whose scope is not a list of our people.

**The proposal is not to delete the seed list, but to change its job.**

Today the CSV is a *gate*: no row, no data. It should become an *authority
overlay*: a statement that these specific people are ours, with these ORCID iDs
and these departments, applied on top of a graph harvested by other means.

Concretely:

- **Add institution-scoped harvesting.** OpenAlex supports filtering works by
  institution ROR ID directly. One query returns every work affiliated with the
  institution over a date range, with no roster involved. This becomes the primary
  discovery path; ORCID-iD harvesting stays as the high-confidence path.
- **Let people be discovered, not declared.** Any author on a harvested work
  becomes a `foaf:Person` in the graph. A roster row then adds authority to a
  person who is already there, rather than being the reason they exist.
- **Keep the roster's real value, which is authority.** A known ORCID iD is what
  makes an assertion `authoritative` rather than `candidate`
  (`src/provenance.py`). That distinction is genuinely useful and should survive
  unchanged.
- **Replace `faculty_id` as the graph's organising key.** Partition output by
  source and by organization instead of by roster row. `faculty_id` stays as one
  external identifier among several on a person — no more privileged than an ORCID
  iD or an OpenAlex author ID.

The practical payoff: the same pipeline pointed at a different ROR produces a
different institution's graph with no seed file at all, which is what makes it
reusable for TCI work. The cost is scale — institution-wide harvesting returns far
more data than a roster of a few dozen people, so Phase 3's reconciliation quality
stops being a nicety and becomes the thing that determines whether the graph is
trustworthy.

### Open questions for the next review

These are tracked in [questions.md](questions.md) alongside the questions this
work has already answered, so there is one register rather than two.
