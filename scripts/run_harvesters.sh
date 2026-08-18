#!/usr/bin/env bash

# Run all harvesters, generate RDF, and optionally load into triple store.
#
# Usage:
#   ./scripts/run_harvesters.sh                    # harvest all sources
#   ./scripts/run_harvesters.sh --source orcid     # harvest ORCID only
#   ./scripts/run_harvesters.sh --load fuseki       # harvest + load into Fuseki
#   ./scripts/run_harvesters.sh --load qlever       # harvest + load into QLever

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOG_DIR="${PROJECT_ROOT}/data/output/logs"
TIMESTAMP=$(date +"%Y%m%d-%H%M%S")
LOG_FILE="${LOG_DIR}/harvest-${TIMESTAMP}.log"

print_usage() {
    echo "Usage: $0 [--source orcid|pubmed|openalex] [--load fuseki|qlever] [--preview]"
    echo ""
    echo "Run the faculty graph harvesting pipeline."
    echo ""
    echo "Options:"
    echo "  --source SOURCE   Harvest from specific source (can repeat)"
    echo "  --load STORE      Load RDF into triple store after harvest"
    echo "  --preview         Generate HTML preview pages after harvest"
    echo "  --help            Show this help"
}

SOURCE_ARGS=""
LOAD_STORE=""
GENERATE_PREVIEW=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --source)
            SOURCE_ARGS="${SOURCE_ARGS} --source $2"
            shift 2
            ;;
        --load)
            LOAD_STORE="$2"
            shift 2
            ;;
        --preview)
            GENERATE_PREVIEW="true"
            shift
            ;;
        --help|-h)
            print_usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            print_usage
            exit 1
            ;;
    esac
done

mkdir -p "${LOG_DIR}"

echo "=== Faculty Graph Harvest: ${TIMESTAMP} ==="
echo "Logging to: ${LOG_FILE}"

cd "${PROJECT_ROOT}"

echo "Starting harvest..."
if python main.py ${SOURCE_ARGS} 2>&1 | tee "${LOG_FILE}"; then
    echo "Harvest completed successfully."
else
    echo "ERROR: Harvest failed. Check ${LOG_FILE}" >&2
    exit 1
fi

if [[ -n "${GENERATE_PREVIEW}" ]]; then
    echo "Generating previews..."
    python main.py --preview 2>&1 | tee --append "${LOG_FILE}"
fi

if [[ -n "${LOAD_STORE}" ]]; then
    echo "Loading into ${LOAD_STORE}..."
    case "${LOAD_STORE}" in
        fuseki)
            "${SCRIPT_DIR}/load_graph_fuseki.sh" 2>&1 | tee --append "${LOG_FILE}"
            ;;
        qlever)
            "${SCRIPT_DIR}/load_graph_qlever.sh" 2>&1 | tee --append "${LOG_FILE}"
            ;;
        *)
            echo "Unknown store: ${LOAD_STORE}" >&2
            exit 1
            ;;
    esac
fi

echo "=== Done: ${TIMESTAMP} ==="
