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
│       ├── previews/         # HTML faculty preview pages
│       ├── disambiguation/   # LLM scoring results
│       └── logs/             # Harvest run logs
├── queries/
│   ├── publications-by-faculty.rq
│   ├── rejected-matches.rq
│   ├── source-overlap.rq
│   ├── coauthors.rq
│   ├── topic-publications.rq
│   └── faculty-publications-report.rq
├── src/
│   ├── config.py             # Institution settings read from the environment
│   ├── provenance.py         # Search method -> assertion status rules
│   ├── errors.py             # HarvestError, SeedDataError, ConfigError
│   ├── harvest_orcid/        # ORCID harvester + seed list loader
│   ├── harvest_pubmed/       # PubMed E-utilities harvester
│   ├── harvest_openalex/     # OpenAlex API harvester
│   ├── rdf_model/            # RDF conversion and model
│   ├── review/               # Human review layer
│   ├── disambiguate/         # LLM disambiguation (Ollama)
│   │   ├── loader.py         # Reloads raw files offline
│   │   └── scorer.py         # Ollama prompting and scoring
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
pip install -e .

# Create your faculty seed list from the template
cp data/seed/faculty.csv.example data/seed/faculty.csv
$EDITOR data/seed/faculty.csv

# Tell the pipeline which institution to filter on
export INSTITUTION_NAME="Your University"

# Optional: install PyYAML for human review support
pip install -e ".[review]"

# Run all harvesters (no API keys needed for public APIs)
python3 main.py

# Run a single source
python3 main.py --source orcid
python3 main.py --source pubmed
python3 main.py --source openalex

# Generate HTML preview pages
python3 main.py --preview

# Run LLM disambiguation (requires Ollama running with gemma4)
python3 main.py --disambiguate

# Output lands in data/output/rdf/, data/raw/, and data/output/previews/
# The combined graph is data/output/rdf/faculty-all.ttl (what the loaders read)
```

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `INSTITUTION_NAME` | Recommended | Institution name as OpenAlex spells it, used to constrain name searches (default: `Example University`). Set it empty to search all institutions. |
| `INSTITUTION_AFFILIATION` | No | Affiliation substring for PubMed searches (default: `INSTITUTION_NAME`). Use a shorter form when papers rarely write the full name. |
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
pip install -e ".[dev]"
pytest
```

The suite is offline and deterministic: every source response is built from
synthetic fixtures in `tests/fixtures.py`, so no test touches the network or
reads `data/raw/`.

`tests/test_converter.py` parses all generated Turtle with `rdflib`. Those tests
skip if `rdflib` is missing rather than failing, but a triple store will reject
output they would have caught, so install the `dev` extra before trusting a run.

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

---

## 🤖 AI-Native Development

**Architected by GPT-5.5. Built by Opus-5. Directed by a human.**

Architecture, implementation, and documentation were generated with AI, with human direction, testing, review, and final approval.

<br>
