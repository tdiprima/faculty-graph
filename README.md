# Faculty Graph

An RDF-based pipeline that harvests public faculty publication data from ORCID, PubMed, and OpenAlex, reconciles it into a trusted knowledge graph with human review support, and generates faculty publication previews.

## What This Prototype Does

- Reads a seed list of BMI faculty with known ORCID IDs.
- Fetches publication records from three sources: ORCID, PubMed, and OpenAlex.
- Converts harvested data into RDF (Turtle format) with per-source provenance.
- Deduplicates publications by DOI/PMID while preserving separate assertions per source.
- Supports human review decisions (rejections/verifications) that persist across re-harvests.
- Runs LLM-based disambiguation on candidate matches via local Ollama (gemma4).
- Generates static HTML preview pages for each faculty member.
- Loads RDF into a triple store (Fuseki or QLever) for SPARQL querying.

## What This Prototype Does Not Do (Yet)

- Drupal publishing.
- University-scale coverage.
- Faculty approval workflow.
- TCIA-specific harvesting.

## Project Structure

```text
faculty-graph/
├── README.md
├── docs/
│   ├── questions.md          # Open questions for boss/team
│   ├── decisions.md          # Architectural decisions made
│   ├── sources.md            # API notes and data source docs
│   └── deployment.md         # Server deployment guide
├── data/
│   ├── seed/
│   │   ├── faculty.csv       # Faculty seed list
│   │   └── reviews.yaml      # Human review decisions
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
│   ├── tcia-publications.rq
│   └── faculty-publications-report.rq
├── src/
│   ├── harvest_orcid/        # ORCID harvester
│   ├── harvest_pubmed/       # PubMed E-utilities harvester
│   ├── harvest_openalex/     # OpenAlex API harvester
│   ├── rdf_model/            # RDF conversion and model
│   ├── review/               # Human review layer
│   ├── disambiguate/         # LLM disambiguation (Ollama/gemma4)
│   └── consumers/            # Preview page generator
└── scripts/
    ├── run_harvesters.sh     # Run all harvesters with logging
    ├── load_graph_fuseki.sh  # Load RDF into Apache Jena Fuseki
    └── load_graph_qlever.sh  # Load RDF into QLever
```

## Quick Start

```bash
# Install dependencies
pip install -e .

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
```

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `NCBI_API_KEY` | No | Higher PubMed rate limits (3 req/s without, 10 with) |
| `OPENALEX_EMAIL` | No | OpenAlex polite pool access |
| `OLLAMA_URL` | No | Ollama endpoint (default: `http://localhost:11434`) |
| `OLLAMA_MODEL` | No | Ollama model for disambiguation (default: `gemma4`) |
| `LOG_LEVEL` | No | Logging level (default: `INFO`) |

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
  - faculty_id: bmi-001
    work_id: "doi:10.1234/wrong-person"
    reason: "Different J. Saltz at another institution"
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

See `data/output/rdf/example.ttl` for the hand-written reference model showing faculty, publications, provenance, and assertion statuses (candidate, verified, rejected, authoritative).
