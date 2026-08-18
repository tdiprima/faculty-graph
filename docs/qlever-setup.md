# QLever Setup Guide

QLever is a high-performance SPARQL engine developed at the University of Freiburg. Unlike Fuseki, it loads data at index-build time rather than via SPARQL UPDATE, so the workflow is: prepare files, build index, start server.

## Prerequisites

- Docker (recommended) or a native build
- At least 4 GB RAM for indexing
- Generated RDF files from `python3 main.py`

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

Create `/opt/qlever-faculty/Qleverfile` with this content:

```ini
[data]
NAME = faculty
GET_DATA_CMD = cat /input/faculty-all.ttl
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
# Copy RDF data into the working directory
cp /opt/faculty-graph/data/output/rdf/faculty-all.ttl /opt/qlever-faculty/

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
cd /opt/qlever-faculty
cp /opt/faculty-graph/data/output/rdf/faculty-all.ttl .
qlever stop
qlever index
qlever start
```

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

After QLever is running:

```bash
./scripts/load_graph_qlever.sh http://localhost:7001
```

This copies the RDF and prints the re-index steps.

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
