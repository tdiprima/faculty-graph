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

The staging script uses `faculty-all.ttl`, the merged view. To audit sources
instead, set `INPUT_FILES` to the per-source graphs and the links between them:

```ini
[index]
INPUT_FILES = by-source/*.ttl reconciliation.ttl
```

Pick one or the other. QLever indexes everything into a single default graph, so
indexing the merged view *and* the per-source graphs means every statement the
merge kept appears twice, from two different subject IRIs.

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
