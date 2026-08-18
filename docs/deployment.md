# Deployment Guide (Vinculum / Server)

Steps for moving the prototype from local development to a server.

## Prerequisites

- Python 3.12+
- A triple store (Fuseki or QLever)
- Git access to this repo

## Setup

```bash
# Clone and install
git clone <repo-url> /opt/faculty-graph
cd /opt/faculty-graph
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# Optional: set environment variables
export NCBI_API_KEY=your_key       # higher PubMed rate limits
export OPENALEX_EMAIL=your@email   # OpenAlex polite pool
export OLLAMA_URL=http://localhost:11434  # LLM disambiguation (optional)
export OLLAMA_MODEL=gemma4         # Ollama model for disambiguation
export LOG_LEVEL=INFO
```

## QLever Setup

See [qlever-setup.md](qlever-setup.md) for full QLever installation and configuration instructions (Docker, native build, Qleverfile config, re-indexing workflow).

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

## Verify the Install

```bash
pip install -e ".[dev]"
pytest
```

The suite runs offline, so this is safe to run on the server before the first
harvest. It also confirms the generated Turtle parses, which is the failure
mode that silently produces output no triple store will load.

## Run the Pipeline

```bash
# Full harvest
python3 main.py

# Load into Fuseki (reads data/output/rdf/faculty-all.ttl)
./scripts/load_graph_fuseki.sh http://localhost:3030 faculty

# Generate previews
python3 main.py --preview
```

## Scheduled Harvesting

### Cron (weekly, Sunday 2am)

```bash
crontab -e
# Add:
0 2 * * 0 cd /opt/faculty-graph && .venv/bin/python3 main.py >> data/output/logs/cron.log 2>&1
```

### Systemd Timer

Create `/etc/systemd/system/faculty-harvest.service`:
```ini
[Unit]
Description=Faculty Graph Harvester

[Service]
Type=oneshot
WorkingDirectory=/opt/faculty-graph
ExecStart=/opt/faculty-graph/.venv/bin/python3 main.py
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
```

## Network Access

If SPARQL endpoint needs to be accessible:
- Request ports 3030 (Fuseki) or 7001 (QLever) opened
- Consider VPN-only access for initial prototype
- No public access until data is reviewed
