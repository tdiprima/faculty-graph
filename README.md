# Faculty Graph

An RDF-based pipeline that harvests public faculty publication data from ORCID, PubMed, and OpenAlex, reconciles it into a trusted knowledge graph with human review support, and generates faculty publication previews.

It is institution-agnostic: point it at any university by setting `INSTITUTION_NAME` and supplying your own faculty seed list. Nothing about a specific school is hardcoded.

## What This Prototype Does

- Reads a seed list of faculty, ideally with known ORCID iDs.
- Fetches publication records from three sources: ORCID, PubMed, and OpenAlex.
- Converts harvested data into RDF (Turtle format) with per-source provenance.
- Deduplicates publications by DOI/PMID while preserving separate assertions per source.
- Supports human review decisions (rejections/verifications) that persist across re-harvests.
- Runs LLM-based disambiguation on candidate matches via local Ollama (`gemma4` by default).
- Generates static HTML preview pages for each faculty member.
- Loads RDF into a triple store (Fuseki or QLever) for SPARQL querying.

## What This Prototype Does Not Do (Yet)

- Drupal publishing.
- University-scale coverage.
- Faculty approval workflow.

## Project Structure

```text
faculty-graph/
├── README.md
├── main.py                   # CLI entry point (orchestration only)
├── pyproject.toml
├── docs/
│   ├── questions.md          # Open questions for boss/team
│   ├── decisions.md          # Architectural decisions made
│   ├── sources.md            # API notes and data source docs
│   ├── deployment.md         # Server deployment guide
│   └── qlever-setup.md       # QLever install and indexing guide
├── data/
│   ├── seed/
│   │   ├── faculty.csv.example  # Template seed list (tracked)
│   │   ├── faculty.csv          # Your faculty seed list (git-ignored)
│   │   └── reviews.yaml         # Human review decisions
│   ├── raw/
│   │   ├── orcid/            # Raw ORCID API responses
│   │   ├── pubmed/           # Raw PubMed XML responses
│   │   └── openalex/         # Raw OpenAlex JSON responses
│   └── output/
│       ├── rdf/              # Generated RDF files
│       │   ├── faculty-all.ttl      # Merged graph (what the loaders read)
│       │   ├── by-source/           # One unmerged graph per source
│       │   └── reconciliation.ttl   # Cross-source links, and nothing else
│       ├── previews/         # HTML faculty preview pages
│       ├── disambiguation/   # LLM scoring results
│       └── logs/             # Harvest run logs
├── queries/
│   ├── publications-by-faculty.rq
│   ├── rejected-matches.rq
│   ├── source-overlap.rq
│   ├── coauthors.rq
│   ├── pending-reconciliation-review.rq # Links a human should check
│   ├── source-agreement.rq             # What sources agree on, and how
│   ├── collaborating-institutions.rq   # External institutions we publish with
│   ├── collaborators-by-institution.rq # Drill-down: who, and on what
│   ├── organization-hierarchy.rq       # Departments under institutions
│   ├── topic-publications.rq
│   └── faculty-publications-report.rq
├── src/
│   ├── config.py             # Institution settings read from the environment
│   ├── provenance.py         # Search method -> assertion status rules
│   ├── names.py              # Personal name parts, kept separate
│   ├── errors.py             # HarvestError, SeedDataError, ConfigError
│   ├── harvest_orcid/        # ORCID harvester + seed list loader
│   ├── harvest_pubmed/       # PubMed E-utilities harvester
│   ├── harvest_openalex/     # OpenAlex API harvester
│   ├── rdf_model/            # RDF conversion and model
│   │   ├── converter.py      # Harvested records -> Turtle
│   │   └── organizations.py  # Organization identity (ROR or locally minted)
│   ├── review/               # Human review layer
│   ├── disambiguate/         # LLM disambiguation (Ollama)
│   │   ├── loader.py         # Reloads raw files offline
│   │   └── scorer.py         # Ollama prompting and scoring
│   ├── reconcile/            # Cross-source linking (its own phase)
│   │   ├── loader.py         # Reloads a harvest from disk
│   │   ├── works.py          # Which records describe the same work
│   │   ├── orgs.py           # Which local orgs are known institutions
│   │   └── writer.py         # Emits the links-only graph
│   └── consumers/            # Preview page generator
├── tests/                    # Offline pytest suite
└── scripts/
    ├── run_harvesters.sh     # Run all harvesters with logging
    ├── load_graph_fuseki.sh  # Load RDF into Apache Jena Fuseki
    └── load_graph_qlever.sh  # Load RDF into QLever
```

## Quick Start

```bash
# Install dependencies
uv sync

# Create your faculty seed list from the template
cp data/seed/faculty.csv.example data/seed/faculty.csv
$EDITOR data/seed/faculty.csv

# Tell the pipeline which institution to filter on
export INSTITUTION_NAME="Your University"

# Optional: add PyYAML for human review support
uv sync --extra review

# Run the whole pipeline: harvest every source, disambiguate, build previews
uv run python3 main.py --full

# Output lands in data/output/rdf/, data/raw/, and data/output/previews/
# The combined graph is data/output/rdf/faculty-all.ttl (what the loaders read)
```

## Command Line Reference

```text
usage: main.py [--source {orcid,pubmed,openalex}] [--full] [--preview] [--disambiguate]
```

| Flag | Description |
|---|---|
| _(none)_ | Harvest every source and write RDF. No disambiguation, no previews. |
| `--source {orcid,pubmed,openalex}` | Harvest only the named source. Repeat the flag to pick several. Default: all three. Also narrows which sources `--full` harvests. |
| `--full` | Run every stage in order: harvest, disambiguate, reconcile, generate previews. |
| `--preview` | Generate HTML preview pages from data already in `data/raw/`. No network calls. |
| `--disambiguate` | Score candidate matches with the local Ollama model. Reads `data/raw/`, so no network calls to the publication sources. |
| `--reconcile` | Link records that different sources reported separately, writing only links into `reconciliation.ttl`. Reads `data/raw/`; makes no network calls. |

`--preview` and `--disambiguate` run standalone or together; combined, disambiguation
runs first so the previews reflect the fresh scores. Both reload `data/raw/`, so you
can re-run either one without re-harvesting.

```bash
# Harvest everything (default when no flag is given)
uv run python3 main.py

# Harvest a single source
uv run python3 main.py --source orcid

# Harvest two sources
uv run python3 main.py --source pubmed --source openalex

# Full pipeline, but only from ORCID
uv run python3 main.py --full --source orcid

# Rebuild HTML previews from already-harvested data
uv run python3 main.py --preview

# Re-score candidate matches (requires Ollama running with gemma4)
uv run python3 main.py --disambiguate

# Re-link records across sources from an existing harvest
uv run python3 main.py --reconcile
```

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `INSTITUTION_NAME` | Recommended | Institution name as OpenAlex spells it, used to constrain name searches (default: `Example University`). Set it empty to search all institutions. |
| `INSTITUTION_AFFILIATION` | No | Affiliation substring for PubMed searches (default: `INSTITUTION_NAME`). Use a shorter form when papers rarely write the full name. |
| `INSTITUTION_ROR` | Recommended | Your institution's ROR IRI, e.g. `https://ror.org/abc123456` (look it up at <https://ror.org>). Without it the graph cannot tell which collaborations are external. Accepts the bare ID or either IRI form. |
| `FG_BASE_URI` | No | Base IRI for generated RDF; must be absolute and end with `/` (default: `http://example.org/faculty-graph/`) |
| `NCBI_API_KEY` | No | Higher PubMed rate limits (3 req/s without, 10 with) |
| `OPENALEX_EMAIL` | No | OpenAlex polite pool access |
| `OLLAMA_URL` | No | Ollama endpoint (default: `http://localhost:11434`) |
| `OLLAMA_MODEL` | No | Ollama model for disambiguation (default: `gemma4`) |
| `LOG_LEVEL` | No | Logging level (default: `INFO`) |

### Seed List Format

`data/seed/faculty.csv` needs all five columns, header row included:

| Column | Required | Notes |
|---|---|---|
| `faculty_id` | Yes | Your own stable identifier. `[A-Za-z0-9_-]` only — it becomes a filename and an RDF IRI. Must be unique. |
| `full_name` | Yes | `First Last`. PubMed name searches use the first and last whitespace-separated tokens. |
| `department` | No | Free text. Passed to the LLM disambiguator as context. |
| `orcid` | No | `0000-0000-0000-0000` form (trailing `X` allowed). Supply it wherever you can: an iD yields `authoritative` assertions, a bare name yields `candidate` ones needing review. |
| `email` | No | Emitted as `foaf:mbox`. |

```csv
faculty_id,full_name,department,orcid,email
fac-001,Josiah Carberry,Psychoceramics,0000-0002-1825-0097,josiah.carberry@example.edu
fac-002,Ada Lovelace,Computer Science,,ada.lovelace@example.edu
```

The whole file is validated before any network call, so a malformed row fails
immediately with the offending line number rather than midway through a harvest.

### Adapting to Your Institution

1. Copy `data/seed/faculty.csv.example` to `data/seed/faculty.csv` and list your
   faculty. `faculty.csv` is git-ignored, so real names and email addresses stay
   out of version control.
2. Set `INSTITUTION_NAME` to the name OpenAlex uses for your institution — search
   <https://api.openalex.org/institutions?search=> to confirm the exact spelling.
   Getting this wrong silently returns zero name-search results.
3. If your papers list a shorter affiliation than the full legal name, set
   `INSTITUTION_AFFILIATION` to that shorter form for PubMed.
4. Optionally set `FG_BASE_URI` to a namespace you control. If you do, update the
   matching `PREFIX` lines in `queries/*.rq` — they are written against the
   default namespace.
5. Edit `queries/topic-publications.rq` to use the keywords your institution
   reports on.

None of these settings affect ORCID-iD searches: an iD is authoritative on its
own, so it is never filtered by institution.

## Tests

```bash
uv sync --extra dev
uv run pytest
```

The suite is offline and deterministic: every source response is built from
synthetic fixtures in `tests/fixtures.py`, so no test touches the network or
reads `data/raw/`.

`tests/test_converter.py` parses all generated Turtle with `rdflib`. Those tests
skip if `rdflib` is missing rather than failing, but a triple store will reject
output they would have caught, so sync the `dev` extra before trusting a run.

## Human Review

Edit `data/seed/reviews.yaml` to add rejections or verifications:

```yaml
rejections:
  - faculty_id: fac-001
    work_id: "doi:10.1234/wrong-person"
    reason: "Different J. Carberry at another institution"
    reviewed_by: human
    reviewed_at: 2026-08-18
```

Review decisions persist across re-harvests. The pipeline never overwrites a human decision.

## Loading into a Triple Store

```bash
# Fuseki (easiest - runs via Docker)
docker run -d --name fuseki -p 3030:3030 apache/jena-fuseki
curl -X POST http://localhost:3030/$/datasets -d 'dbName=faculty&dbType=tdb2'
./scripts/load_graph_fuseki.sh http://localhost:3030 faculty

# QLever
./scripts/load_graph_qlever.sh http://localhost:7001
```

## Data Model

See `data/output/rdf/example.ttl` for the hand-written reference model showing
faculty, publications, provenance, and assertion statuses (candidate, verified,
rejected, authoritative).

Node IRIs are written in full angle-bracket form
(`<http://example.org/faculty-graph/data/faculty/fac-001>`) rather than as
prefixed names. A Turtle prefixed name cannot contain an unescaped `/`, so
`fgdata:faculty/fac-001` is not parseable and no triple store will load it.

Assertion status is derived from how a publication was found: an ORCID-iD
search yields `authoritative`, a name search yields `candidate`. That rule lives
in `src/provenance.py` and is shared by the harvesters and the disambiguation
loader, so a record reloaded from `data/raw/` carries the status the harvester
gave it.

### Organizations and Collaboration

Institutions are resources, not strings. When a source supplies a ROR
identifier, that IRI is the organization's subject IRI directly, so two sources
naming the same institution converge on one node without any matching step.
An organization with no ROR gets a locally minted IRI under `fgdata:org/`, and
`fg:identifierKind` records which of the two it is (`"ror"` or `"local"`) so the
local ones can be found and reconciled later.

Affiliation hangs off an `fg:Authorship` node rather than off the person. An
author's institution is a fact about that author on that paper — people move,
and the paper records where they were at the time. This is what makes
`queries/collaborating-institutions.rq` a one-hop query.

Free-text affiliation lines from PubMed are deliberately *not* turned into
organizations. A string like `"Dept of Pathology, Example University, NY
11794, USA"` names several organizations at once, so it is kept verbatim as
`fg:affiliationRaw` for a later reconciliation pass to interpret.

### Reconciliation Is Its Own Phase

Harvesting records what each source said. Deciding that two sources described
the same thing is a separate judgement, and it lives in its own file:

- `data/output/rdf/by-source/*.ttl` — one graph per source, **unmerged**. Work
  IRIs are scoped by source (`fgdata:work/pubmed/doi-…`), so two sources
  describing one article stay two nodes.
- `data/output/rdf/reconciliation.ttl` — **only** links. Each is an
  `fg:MatchAssertion` carrying `fg:matchMethod`, `fg:matchConfidence`, and the
  source it came from. Nothing in this file restates what a source said.
- `data/output/rdf/faculty-all.ttl` — the merged graph the loader scripts read,
  unchanged.

A link is asserted as `owl:sameAs` only at full confidence — a shared DOI or
PMID. A link resting on a title match is recorded with `fg:needsHumanReview true`
and no `owl:sameAs`, so a title collision never silently fuses two works.
Confidence reflects the key that actually *joined* the records: two records that
each carry a DOI but not the *same* DOI are a title match, not a DOI match.

Because links live in their own file, undoing a bad reconciliation means not
loading it. Re-harvesting is never required.

Organization reconciliation works the same way, matching locally minted
organizations to ROR-identified ones by name. It is offline: it matches only
against organizations already present in the harvest. Names too generic to
identify an institution (`"School of Medicine"`, `"Cancer Center"`) and names
claimed by two different registered organizations are left unreconciled rather
than guessed. Querying ror.org for institutions absent from the harvest is not
implemented — that needs a network boundary and its own consent.

Personal names keep their parts: `foaf:givenName` and `foaf:familyName` are
emitted separately from `foaf:name`, and `fg:nameSource` says whether a source
stated the parts (`"structured"`) or we split a rendered string (`"display"`).
A name that cannot be split unambiguously is left unsplit rather than split
wrongly.

---

## 🤖 AI-Native Development

**Architected by GPT-5.5. Built by Opus-5. Directed by a human.**

Architecture, implementation, and documentation were generated with AI, with human direction, testing, review, and final approval.

<br>
