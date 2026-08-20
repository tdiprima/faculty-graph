# Deployment Guide (Vinculum / Server)

Steps for moving the prototype from local development to a server.

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) for dependency management
- A triple store (Fuseki or QLever)
- Git access to this repo

## Setup

```bash
git clone <repo-url> /opt/faculty-graph
cd /opt/faculty-graph
uv sync
```

`uv sync` creates `.venv/` and installs from `uv.lock`, so the server gets the
exact versions the tests were run against. Add `--extra review` for the YAML
review workflow, `--extra dev` to run the test suite.

## Configuration

Every setting is read from the environment. A `.env` file in the project root is
loaded at startup; anything already exported in the shell wins over it, so a
one-off override does not mean editing the file.

```bash
cp .env.example .env
$EDITOR .env
```

`.env.example` documents each variable. The ones that must be reviewed before a
server run:

| Variable | Why it matters here |
|---|---|
| `INSTITUTION_ROR` | Decides who counts as "us". Comma-separated when one institution has several ROR records — Example University (`abc123456`) and Example University Hospital (`abc123456`) are separate entries, and omitting the second reports the hospital as an outside collaborator. |
| `INSTITUTION_NAME` / `INSTITUTION_AFFILIATION` | Search terms for OpenAlex and PubMed. |
| `FG_BASE_URI` | Namespace of every generated term. Change it *before* the first load — see "Namespace and named graph" below. |
| `NCBI_API_KEY` | Raises PubMed's rate limit from 3 to 10 requests/second. Worth having for a full run. |
| `OPENALEX_EMAIL` | Gets the faster "polite pool". |
| `LOG_LEVEL` | `INFO` for scheduled runs; `DEBUG` produces per-request output. |

`.env` is git-ignored. Keep it readable only by the service account:

```bash
chmod 600 /opt/faculty-graph/.env
chown faculty-graph:faculty-graph /opt/faculty-graph/.env
```

## Verify the Install

```bash
uv sync --extra dev
uv run pytest
```

The suite runs offline, so this is safe to run on the server before the first
harvest. It also confirms the generated Turtle parses, which is the failure mode
that silently produces output no triple store will load.

## QLever Setup

See [qlever-setup.md](qlever-setup.md) for full QLever installation and
configuration instructions (Docker, native build, Qleverfile config, re-indexing
workflow).

## Fuseki Setup

```bash
# Run Fuseki via Docker
docker run -d --name fuseki \
    -p 3030:3030 \
    -v fuseki-data:/fuseki \
    apache/jena-fuseki

# Create dataset
curl -X POST http://localhost:3030/$/datasets \
    -d 'dbName=faculty&dbType=tdb2'
```

## Run the Pipeline

```bash
# Harvest all sources and write RDF
uv run python3 main.py

# Harvest, disambiguate, reconcile, and generate previews
uv run python3 main.py --full

# Individual stages, against data already on disk
uv run python3 main.py --disambiguate
uv run python3 main.py --reconcile
uv run python3 main.py --preview
```

### What a run produces

`data/output/rdf/` holds three different things, and which you load matters:

| Path | Contents |
|---|---|
| `faculty-all.ttl` | The merged roster view — every faculty member, cross-source duplicates already merged. |
| `by-source/*.ttl` | One graph per source, unmerged. This is the harvest of record: it says only what that source reported. |
| `reconciliation.ttl` | Only the links between the per-source graphs, as `fg:MatchAssertion` nodes with method and confidence. `owl:sameAs` appears only for full-confidence matches. |

`scripts/load_graph_fuseki.sh` and `scripts/load_graph_qlever.sh` load
`faculty-all.ttl` only. That is the right default for a browsing endpoint, but a
consumer that needs to see which source claimed what — or to audit a merge —
needs `by-source/` plus `reconciliation.ttl` loaded into separate named graphs
instead. Loading both sets into one graph gives you the merged data twice.

```bash
# Load the merged view into Fuseki
./scripts/load_graph_fuseki.sh http://localhost:3030 faculty
```

### Namespace and named graph

`load_graph_fuseki.sh` writes into the named graph
`http://example.org/faculty-graph/data`, which is hardcoded in the script and
does **not** follow `FG_BASE_URI`. If you change `FG_BASE_URI` for a real
deployment, edit `GRAPH_URI` in that script to match, or you will have data in a
namespace that no verification query below targets.

### Queries

Queries in `queries/` are templates. `--write-queries` resolves them against the
current environment and writes runnable `.rq` files to
`data/output/queries/`, which is what to point a scheduled report or a
dashboard at:

```bash
uv run python3 main.py --list-queries
uv run python3 main.py --write-queries
uv run python3 main.py --query collaborating-institutions
```

An unresolved or empty placeholder raises `ConfigError` rather than producing a
query that runs and returns the wrong rows.

## Scheduled Harvesting

### Cron (weekly, Sunday 2am)

`data/output/logs/` is git-ignored and will not exist on a fresh clone. Create it
before the first scheduled run, or the redirect below fails and the run produces
no record of why.

```bash
mkdir -p /opt/faculty-graph/data/output/logs
crontab -e
# Add:
0 2 * * 0 cd /opt/faculty-graph && /usr/local/bin/uv run python3 main.py --full >> data/output/logs/cron.log 2>&1
```

Cron runs with a minimal environment and no shell profile, so `uv` needs its
absolute path. Configuration still comes from `.env`, which the pipeline loads
itself.

### Systemd Timer

Create `/etc/systemd/system/faculty-harvest.service`:
```ini
[Unit]
Description=Faculty Graph Harvester

[Service]
Type=oneshot
WorkingDirectory=/opt/faculty-graph
ExecStart=/usr/local/bin/uv run python3 main.py --full
User=faculty-graph
Environment=LOG_LEVEL=INFO
```

Create `/etc/systemd/system/faculty-harvest.timer`:
```ini
[Unit]
Description=Weekly faculty graph harvest

[Timer]
OnCalendar=Sun *-*-* 02:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
sudo systemctl enable --now faculty-harvest.timer
```

The service does not load the graph into the triple store — a harvest failure
should not take down a working endpoint. Load as a separate, manual or separately
scheduled step once the run's output has been checked.

## Verify

```bash
# Check SPARQL endpoint. load_graph_fuseki.sh writes into a named graph, so the
# count must target it -- a query against the default graph returns 0.
curl -s 'http://localhost:3030/faculty/sparql' \
    --data-urlencode 'query=SELECT (COUNT(*) as ?n) WHERE {
        GRAPH <http://example.org/faculty-graph/data> { ?s ?p ?o } }' \
    -H 'Accept: application/sparql-results+json'

# Check previews
ls data/output/previews/

# Check how many reconciliation links are waiting on a human
uv run python3 main.py --query pending-reconciliation-review
```

## Network Access

If SPARQL endpoint needs to be accessible:
- Request ports 3030 (Fuseki) or 7001 (QLever) opened
- Consider VPN-only access for initial prototype
- No public access until data is reviewed
