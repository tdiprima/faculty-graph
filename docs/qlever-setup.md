# QLever Setup Guide

QLever is a high-performance SPARQL engine developed at the University of Freiburg. Unlike Fuseki, it loads data at index-build time rather than via SPARQL UPDATE, so the workflow is: prepare files, build index, start server.

## Prerequisites

- Docker (recommended) or a native build
- At least 4 GB RAM for indexing
- Generated RDF files from `uv run python3 main.py`

## Option 1: Docker (Recommended)

### Install the QLever CLI

```bash
pip install qlever
```

### Create a working directory

```bash
mkdir -p /opt/qlever-faculty
cd /opt/qlever-faculty
```

### Create a Qleverfile

Create `/opt/qlever-faculty/Qleverfile` with this content. Qleverfile keys have
changed between QLever releases, so if `qlever index` rejects one, check
`qlever setup-config` output for the version you installed:

```ini
[data]
NAME = faculty
# The staging script has already put faculty-all.ttl in this directory, so
# there is nothing to fetch. A GET_DATA_CMD pointing somewhere else would
# quietly index stale data, or nothing at all.
GET_DATA_CMD = echo "using staged faculty-all.ttl"
DATA_FORMAT = ttl

[index]
INPUT_FILES = faculty-all.ttl
SETTINGS_JSON = {"ascii-prefixes-only": false, "num-triples-per-batch": 100000}

[server]
PORT = 7001
MEMORY_FOR_QUERIES = 2G
TIMEOUT = 30s

[docker]
IMAGE = adfreiburg/qlever
```

### Build and run

```bash
# Stage the RDF into the working directory
QLEVER_DATA_DIR=/opt/qlever-faculty /opt/faculty-graph/scripts/load_graph_qlever.sh

# Build the index
qlever index

# Start the server
qlever start

# Verify
qlever status
```

The SPARQL endpoint is now at `http://localhost:7001`.

### Test a query

```bash
curl -s 'http://localhost:7001' \
    --data-urlencode 'query=SELECT (COUNT(*) AS ?n) WHERE { ?s ?p ?o }' \
    -H 'Accept: application/sparql-results+json'
```

### Reload after re-harvesting

QLever requires re-indexing when data changes:

```bash
QLEVER_DATA_DIR=/opt/qlever-faculty /opt/faculty-graph/scripts/load_graph_qlever.sh
cd /opt/qlever-faculty
qlever stop
qlever index
qlever start
```

The server keeps serving the previous index until `qlever start` runs against
the new one, so a re-harvest never leaves the endpoint down — but it also means
a count taken before the restart reports the old data.

## Option 2: Docker without the CLI

If you prefer not to install the QLever CLI:

```bash
cd /opt/qlever-faculty

# Copy data
cp /opt/faculty-graph/data/output/rdf/faculty-all.ttl .

# Build index
docker run --rm \
    -v "$(pwd):/data" \
    -w /data \
    adfreiburg/qlever \
    IndexBuilderMain \
    -f faculty-all.ttl \
    -i faculty \
    -s '{"ascii-prefixes-only": false}'

# Run server
docker run -d \
    --name qlever-faculty \
    -p 7001:7001 \
    -v "$(pwd):/data" \
    -w /data \
    adfreiburg/qlever \
    ServerMain \
    -i faculty \
    -p 7001
```

## Option 3: Native build (Ubuntu/RHEL)

See the QLever GitHub repository for build instructions:
https://github.com/ad-freiburg/qlever

Build dependencies (Ubuntu):

```bash
sudo apt install build-essential cmake libboost-all-dev
git clone --recursive https://github.com/ad-freiburg/qlever.git
cd qlever && mkdir build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j$(nproc)
```

Then use `IndexBuilderMain` and `ServerMain` directly instead of Docker.

## Loading with the faculty-graph script

```bash
./scripts/load_graph_qlever.sh
```

The script copies `faculty-all.ttl` into `QLEVER_DATA_DIR` (default
`qlever-data/` in the project root) and prints the index and start commands for
whichever toolchain is installed — the `qlever` CLI if it is on PATH, otherwise
the equivalent Docker invocations. It loads nothing itself, because QLever has
no upload endpoint to load into.

If a server is already running at the endpoint, the script reports its current
triple count. That number is the *previous* index: it changes only after a
rebuild and restart.

### Which files to index

**The production index is `faculty-all.ttl` only.** That is settled — see
decision 014 in `decisions.md`. `by-source/*.ttl` and `reconciliation.ttl` are
audit artifacts: read them, query them ad hoc, reload them after a bad merge, but
keep them out of the index QLever serves.

The reason is that QLever indexes into a single default graph. `faculty-all.ttl`
already merges what the per-source graphs state separately, so indexing both puts
those facts in twice under different subject IRIs. The data would not be *wrong*,
but every count, join, and aggregate would have to account for the duplication,
and the first query that forgets inflates its numbers with nothing to signal it.

There is a non-default provenance profile for the case where sources must be
queryable rather than auditable:

```ini
[index]
INPUT_FILES = by-source/*.ttl reconciliation.ttl
```

Use it in a *separate* index, never alongside the canonical one. If per-source
querying becomes a standing requirement rather than an occasional check, the
answer is Fuseki named graphs or a QLever quads representation — not merging the
two profiles into one index.

## QLever UI (optional)

QLever has a web-based query UI:

```bash
docker run -d \
    --name qlever-ui \
    -p 7000:7000 \
    -e QLEVER_API_URL=http://localhost:7001 \
    adfreiburg/qlever-ui
```

Then open `http://localhost:7000` in a browser.

## Troubleshooting

**Index fails with out-of-memory**: Reduce `num-triples-per-batch` in the Qleverfile settings, or add more RAM.

**Server won't start**: Check that the index files exist in the working directory (`faculty.index.*` files). If missing, re-run `qlever index`.

**Port already in use**: Change `PORT` in the Qleverfile or use `-p 7002:7001` in Docker.

**Slow queries**: QLever is optimized for large datasets. For the faculty-graph prototype size (~5MB), query time is negligible. If queries are slow, check that the index was built correctly.
