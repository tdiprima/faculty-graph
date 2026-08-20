# Faculty Graph

Harvests public faculty publication data from ORCID, PubMed, and OpenAlex, then
writes RDF files.

## How To Run It

Run these commands from this folder:

```bash
uv sync --extra all
test -f .env || cp .env.example .env
test -f data/seed/faculty.csv || cp data/seed/faculty.csv.example data/seed/faculty.csv
```

Edit `.env` and fill in your institution info:

```text
INSTITUTION_NAME
INSTITUTION_AFFILIATION
INSTITUTION_ROR
OPENALEX_EMAIL
```

Edit `data/seed/faculty.csv` and replace the example people with your faculty.
Keep the header row exactly as-is:

```csv
faculty_id,full_name,department,orcid,email
```

Then run the harvest:

```bash
uv run python main.py
```

The main output file is:

```text
data/output/rdf/faculty-all.ttl
```

Raw downloaded data goes here:

```text
data/raw/
```

## Useful Extras

Generate HTML preview pages:

```bash
uv run python main.py --preview
```

Preview files go here:

```text
data/output/previews/
```

Run everything, including disambiguation, reconciliation, and previews:

```bash
uv run python main.py --full
```

Run tests:

```bash
uv sync --extra dev
uv run pytest
```

If `uv` is not installed:

```bash
python -m pip install uv
```

---

*Code and docs written by AI, steered by a human.*

<br>
