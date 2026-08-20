# Faculty Graph

This project harvests public faculty publication data from ORCID, PubMed, and
OpenAlex, turns it into RDF, and can generate simple HTML preview pages.

Read this first if you just want to run it.

## The Short Version

Run these from the project folder:

```bash
uv sync --extra all
test -f .env || cp .env.example .env
test -f data/seed/faculty.csv || cp data/seed/faculty.csv.example data/seed/faculty.csv
vim .env
vim data/seed/faculty.csv
uv run python3 main.py
```

After that, look here:

```text
data/raw/                 downloaded source responses
data/output/rdf/           RDF Turtle files
data/output/rdf/faculty-all.ttl
```

To make HTML preview pages too:

```bash
uv run python3 main.py --preview
```

Open the generated files in:

```text
data/output/previews/
```

## Step By Step

### 1. Go To The Project

```bash
cd /path/to/faculty-graph
```

Sanity check:

```bash
pwd
```

You should be inside a folder named `faculty-graph`.

### 2. Install Python Dependencies

```bash
uv sync --extra all
```

Why: this creates the local Python environment and installs the packages the
pipeline imports.

If `uv` is not installed, install it first:

```bash
python3 -m pip install uv
```

Then run `uv sync --extra all` again.

### 3. Create Your Local Config

```bash
test -f .env || cp .env.example .env
```

Then edit it:

```bash
vim .env
```

Set these first:

```text
INSTITUTION_NAME="Your University Name"
INSTITUTION_AFFILIATION="Short name used in paper affiliations"
INSTITUTION_ROR="https://ror.org/yourrorid"
OPENALEX_EMAIL="you@example.edu"
```

Notes:

- Find the ROR ID at <https://ror.org>.
- `NCBI_API_KEY` is optional. PubMed works without it, just slower.
- `.env` is ignored by git. Put real local values there.

### 4. Create The Faculty List

```bash
test -f data/seed/faculty.csv || cp data/seed/faculty.csv.example data/seed/faculty.csv
```

Then edit it:

```bash
vim data/seed/faculty.csv
```

Keep this exact header:

```csv
faculty_id,full_name,department,orcid,email
```

Example row:

```csv
fac-001,Ada Lovelace,Computer Science,,ada.lovelace@example.edu
```

Better row, if you know the ORCID:

```csv
fac-001,Ada Lovelace,Computer Science,0000-0002-1825-0097,ada.lovelace@example.edu
```

Why ORCID matters: ORCID matches are much more trustworthy than name searches.

### 5. Run A Tiny Sanity Check

```bash
uv run python3 main.py --list-queries
```

If this prints query names, the app can start and read config.

### 6. Run The Harvest

```bash
uv run python3 main.py
```

This harvests all three sources:

- ORCID
- PubMed
- OpenAlex

It writes RDF here:

```text
data/output/rdf/
```

The main file most loaders use is:

```text
data/output/rdf/faculty-all.ttl
```

### 7. Generate Preview Pages

```bash
uv run python3 main.py --preview
```

Then open the HTML files in:

```text
data/output/previews/
```

## Common Commands

Harvest everything:

```bash
uv run python3 main.py
```

Harvest only ORCID:

```bash
uv run python3 main.py --source orcid
```

Harvest only PubMed:

```bash
uv run python3 main.py --source pubmed
```

Harvest only OpenAlex:

```bash
uv run python3 main.py --source openalex
```

Regenerate previews without downloading anything new:

```bash
uv run python3 main.py --preview
```

Run reconciliation without downloading anything new:

```bash
uv run python3 main.py --reconcile
```

Print one SPARQL query:

```bash
uv run python3 main.py --query collaborating-institutions
```

Write all resolved SPARQL queries:

```bash
uv run python3 main.py --write-queries
```

Run tests:

```bash
uv sync --extra dev
uv run pytest
```

## Full Pipeline With LLM Disambiguation

This command does the most:

```bash
uv run python3 main.py --full
```

It runs:

1. harvest
2. LLM disambiguation
3. reconciliation
4. previews

Important: `--full` expects Ollama to be running locally.

Your `.env` controls the Ollama settings:

```text
OLLAMA_URL="http://localhost:11434"
OLLAMA_MODEL="gemma4"
```

If you do not have Ollama ready, do this instead:

```bash
uv run python3 main.py
uv run python3 main.py --reconcile
uv run python3 main.py --preview
```

That skips the LLM step.

## What Files Matter

Input files you edit:

```text
.env
data/seed/faculty.csv
data/seed/reviews.yaml
```

Output files the app creates:

```text
data/raw/
data/output/rdf/
data/output/previews/
data/output/disambiguation/
data/output/queries/
```

Most important RDF output:

```text
data/output/rdf/faculty-all.ttl
```

## Loading The RDF Into A Triple Store

Use QLever if you do not already have a different store picked.

First generate RDF:

```bash
uv run python3 main.py
```

Then stage it for QLever:

```bash
./scripts/load_graph_qlever.sh
```

The script prints the next QLever commands to run. The usual version is:

```bash
cd qlever-data
qlever stop
qlever index
qlever start
```

Full QLever notes are in [docs/qlever-setup.md](docs/qlever-setup.md).

Fuseki is optional. See [docs/deployment.md](docs/deployment.md) if you need it.

## If Something Breaks

### `Seed file not found`

You skipped this:

```bash
test -f data/seed/faculty.csv || cp data/seed/faculty.csv.example data/seed/faculty.csv
```

Then edit the new file.

### `Invalid seed data`

Check `data/seed/faculty.csv`.

The required columns are:

```csv
faculty_id,full_name,department,orcid,email
```

Rules:

- `faculty_id` cannot be blank.
- `full_name` cannot be blank.
- `faculty_id` must be unique.
- ORCID can be blank, but if present it must look like `0000-0000-0000-0000`.

### No Results

Check these in `.env`:

```text
INSTITUTION_NAME
INSTITUTION_AFFILIATION
INSTITUTION_ROR
```

Also add ORCID IDs to `data/seed/faculty.csv` wherever possible.

### `--full` Fails At Disambiguation

Ollama is probably not running, or the configured model is not available.

Use the no-LLM path:

```bash
uv run python3 main.py
uv run python3 main.py --reconcile
uv run python3 main.py --preview
```

### Dependency Problems

Run:

```bash
uv sync --extra all
```

For tests, run:

```bash
uv sync --extra dev
```

## Project Map

```text
main.py                 command-line entry point
src/                    pipeline code
data/seed/              your faculty list and review decisions
data/raw/               downloaded source data
data/output/rdf/        generated RDF
data/output/previews/   generated HTML previews
queries/                SPARQL query templates
ontology/fg.ttl         local vocabulary
docs/                   deeper notes
tests/                  offline pytest suite
```

## Deeper Docs

- [docs/deployment.md](docs/deployment.md)
- [docs/qlever-setup.md](docs/qlever-setup.md)
- [docs/modeling-rules.md](docs/modeling-rules.md)
- [docs/roadmap.md](docs/roadmap.md)
- [docs/sources.md](docs/sources.md)

---

*Code and docs written by AI, steered by a human.*

<br>
