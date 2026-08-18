# Modeling Rules

The commitments this graph makes about its own shape. They exist so that mapping
this model onto another one — VIVO, FaBiO, whatever the ontology group settles
on — is an ETL exercise rather than an archaeology exercise.

Each rule is stated with what it costs, because a rule with no cost is not a
rule, it is a preference.

## 1. Never concatenate what a source stated separately

If a source gives family name and given name as distinct fields, they stay
distinct. Once joined, they cannot be reliably pulled apart: `"Ludwig van
Beethoven"` and `"Maria dos Santos Silva"` do not split on the last space, and no
amount of later cleverness recovers what the source already knew.

The same applies to page ranges (`bibo:pageStart` and `bibo:pageEnd` alongside
the printed `bibo:pages`), and to any compound value a source hands over
pre-separated.

**Cost:** more fields, and more places for a parser to be wrong.

**Where enforced:** `src/names.py`, `src/harvest_pubmed/parser.py`.

## 2. Never invent structure a source did not state

The other half of rule 1. OpenAlex gives one rendered name string, so any split
of it is a guess. The guess is still worth making — most names split correctly —
but it is *labelled* as a guess with `fg:nameSource "display"`, and where the
form is ambiguous no guess is made at all.

A consumer that cares about name accuracy can therefore filter on provenance
rather than discovering the problem in production.

**Cost:** consumers must check `fg:nameSource` to know what they have.

**Where enforced:** `src/names.py`, `split_display_name`.

## 3. Every assertion carries its source

No triple in this graph says "this person wrote this paper" as a bare fact. It
says "PubMed claimed, on this date, found by name search, that this person wrote
this paper." Sources disagree and matches are sometimes wrong, and a graph that
has flattened away who claimed what cannot represent either.

**Cost:** an extra node per harvested record, and queries must join through it.

**Where enforced:** `fg:PublicationAssertion` in `src/rdf_model/converter.py`.

## 4. A locally minted IRI says so

An IRI under `fgdata:` is ours. It means "we needed to name this thing and no
registry had". An IRI under `https://ror.org/` is the registry's and resolves.
`fg:identifierKind` states which kind a node is, so nothing downstream mistakes a
local guess for a global identifier.

**Cost:** two classes of identifier to reason about.

**Where enforced:** `src/rdf_model/organizations.py`.

## 5. Conclusions live apart from observations

What a source said goes in `by-source/`. What the pipeline concluded about it —
that two records are the same work, that a local organization is a registered one
— goes in `reconciliation.ttl`, as `fg:MatchAssertion` nodes carrying method and
confidence.

Withdrawing a conclusion is therefore not loading one file. Re-harvesting is
never the remedy for a bad match.

**Cost:** the merged view is a derived artifact, not the primary one, and
consumers must know which graph they want.

**Where enforced:** `src/reconcile/`.

## 6. Confidence reflects the evidence, not the record

A match is reported at the strength of the key that actually *joined* the
records. Two records that each carry a DOI, but not the same DOI, were joined by
something else — reporting that as a DOI match would assert a certainty the
evidence does not support.

Only a full-confidence match is asserted as `owl:sameAs`. Anything weaker is
recorded with `fg:needsHumanReview` and left for a person.

**Cost:** more links await review than a more confident pipeline would produce.

**Where enforced:** `src/reconcile/works.py`, `group_match_method`.

## 7. A human decision is never overwritten

A rejection persists across re-harvests. The pipeline may re-find a work a
reviewer threw out, but it does not silently re-add it.

**Cost:** review state is a real input that must be carried between runs.

**Where enforced:** `src/review/manager.py`.

## 8. Facts are attached at the level they are true

An author's institution is recorded on the `fg:Authorship`, not on the person,
because it is a fact about that author on that paper. People move; the paper
records where they were. Attaching it to the person would make the graph assert
that someone is *currently* at an institution they left a decade ago.

Similarly, `fg:citedByCount` is a measurement taken at harvest time, not a
property of the work.

**Cost:** an extra node between person and work, and one more hop in queries.

**Where enforced:** `fg:Authorship` in `src/rdf_model/converter.py`.

## 9. Unparsed source text is kept, not discarded

A PubMed affiliation line names several organizations at once. Rather than
guessing which, the line is kept verbatim as `fg:affiliationRaw` for
reconciliation to interpret. The same principle keeps `fg:department` as a string
next to the `org:memberOf` link derived from it.

The string is what the source said; the link is what we concluded. Keeping both
is what makes the conclusion auditable.

**Cost:** redundancy, and consumers must know which of the two to trust.

## 10. Every term is defined and every definition is used

`ontology/fg.ttl` defines every `fg:` term with a label, comment, domain, and
range, and states its alignment to standard vocabularies at the strength the
semantics support — `owl:equivalentProperty` only for genuine identity,
`rdfs:subPropertyOf` for narrowing, `rdfs:seeAlso` where the relationship is real
but not interchangeable.

`tests/test_ontology.py` checks both directions: a term emitted but undefined
fails, and a term defined but unused fails.

**Cost:** adding a term is a two-file change.

## Known gaps

Stated here rather than discovered later:

- **Journals are literals, not resources.** `fg:journal` is a string. Modelling a
  journal as a node with ISSN identity is the obvious next step and is not done.
- **Works are all typed `bibo:AcademicArticle`,** including datasets and
  preprints, regardless of what `fg:workType` says.
- **Organization hierarchy is one level deep.** A department hangs off an
  institution; institutes, schools, and colleges between them are not modelled.
- **Organization reconciliation is offline.** It matches only against
  organizations already in the harvest. No ror.org lookup.
- **A distinctive shared title merges records with different DOIs.** Right for
  two deposits of one article, wrong for two works that share a title. The link
  is review-flagged either way.
