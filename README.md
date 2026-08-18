# Faculty Graph

An RDF-based pipeline that harvests public faculty publication data from sources like ORCID, PubMed, and OpenAlex, reconciles it into a trusted knowledge graph, and later uses it to power accurate faculty profiles, reports, and visualizations.

## What This Prototype Does

- Reads a seed list of BMI faculty with known ORCID IDs.
- Fetches publication records from ORCID's public API.
- Converts harvested data into RDF (Turtle format).
- Loads RDF into a local triple store for SPARQL querying.
- Tracks assertion provenance: every fact records its source, status, and timestamp.

## What This Prototype Does Not Do (Yet)

- PubMed or OpenAlex harvesting.
- LLM-based disambiguation.
- Drupal publishing.
- University-scale coverage.
- Automated scheduling.

## Project Structure

```text
faculty-graph/
├── README.md
├── docs/
│   ├── questions.md        # Open questions for boss/team
│   ├── decisions.md        # Architectural decisions made
│   └── sources.md          # API notes and data source docs
├── data/
│   ├── seed/
│   │   └── faculty.csv     # Faculty seed list
│   ├── raw/
│   │   └── orcid/          # Raw ORCID API responses
│   └── output/
│       └── rdf/            # Generated RDF files
├── queries/
│   ├── publications-by-faculty.rq
│   ├── rejected-matches.rq
│   └── source-overlap.rq
├── src/
│   ├── harvest_orcid/      # ORCID harvester
│   ├── rdf_model/          # RDF conversion and model
│   └── review/             # Human review logic
└── scripts/
    └── load_graph.sh       # Triple store loading script
```

## Quick Start

```bash
# Install dependencies
pip install -e .

# Set ORCID API credentials (optional - public API works without)
export ORCID_CLIENT_ID=your_client_id
export ORCID_CLIENT_SECRET=your_client_secret

# Run the ORCID harvester
python -m src.harvest_orcid.client

# Output lands in data/output/rdf/ and data/raw/orcid/
```

## Data Model

See `data/output/rdf/example.ttl` for the hand-written reference model showing faculty, publications, provenance, and assertion statuses.
