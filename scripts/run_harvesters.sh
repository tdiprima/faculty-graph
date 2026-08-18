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
VENV_PYTHON="${PROJECT_ROOT}/.venv/bin/python3"

# Fall back to the project virtualenv when one exists, so the script does not
# depend on the caller having activated it. An explicit PYTHON_BIN always wins.
if [[ -n "${PYTHON_BIN:-}" ]]; then
    : # caller chose the interpreter
elif [[ -x "${VENV_PYTHON}" ]]; then
    PYTHON_BIN="${VENV_PYTHON}"
else
    PYTHON_BIN="python3"
fi

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

SOURCE_ARGS=()
LOAD_STORE=""
GENERATE_PREVIEW=""

# Ensure an option that takes a value actually received one, so the script
# reports the problem instead of dying on an unbound variable under `set -u`.
require_value() {
    local option_name="$1"
    local remaining_args="$2"
    if [[ "${remaining_args}" -lt 2 ]]; then
        echo "ERROR: ${option_name} requires a value" >&2
        print_usage >&2
        exit 2
    fi
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --source)
            require_value "$1" "$#"
            SOURCE_ARGS+=(--source "$2")
            shift 2
            ;;
        --load)
            require_value "$1" "$#"
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
            print_usage >&2
            exit 1
            ;;
    esac
done

# Reject an unknown store before harvesting rather than after, so a typo does
# not cost a full harvest run.
if [[ -n "${LOAD_STORE}" && "${LOAD_STORE}" != "fuseki" && "${LOAD_STORE}" != "qlever" ]]; then
    echo "ERROR: unknown store '${LOAD_STORE}' (expected fuseki or qlever)" >&2
    exit 2
fi

mkdir -p "${LOG_DIR}"

echo "=== Faculty Graph Harvest: ${TIMESTAMP} ==="
echo "Logging to: ${LOG_FILE}"

cd "${PROJECT_ROOT}"

echo "Starting harvest..."
if "${PYTHON_BIN}" main.py "${SOURCE_ARGS[@]}" 2>&1 | tee "${LOG_FILE}"; then
    echo "Harvest completed successfully."
else
    echo "ERROR: Harvest failed. Check ${LOG_FILE}" >&2
    exit 1
fi

if [[ -n "${GENERATE_PREVIEW}" ]]; then
    echo "Generating previews..."
    if ! "${PYTHON_BIN}" main.py --preview 2>&1 | tee --append "${LOG_FILE}"; then
        echo "ERROR: Preview generation failed. Check ${LOG_FILE}" >&2
        exit 1
    fi
fi

if [[ -n "${LOAD_STORE}" ]]; then
    echo "Loading into ${LOAD_STORE}..."
    if ! "${SCRIPT_DIR}/load_graph_${LOAD_STORE}.sh" 2>&1 | tee --append "${LOG_FILE}"; then
        echo "ERROR: Loading into ${LOAD_STORE} failed. Check ${LOG_FILE}" >&2
        exit 1
    fi
fi

echo "=== Done: ${TIMESTAMP} ==="
