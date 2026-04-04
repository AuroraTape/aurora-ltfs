#!/bin/bash
#
# run_all.sh - Run all incremental index recovery scenario tests
#
# Usage:
#   bash run_all.sh            # Run all scenarios in parallel
#   bash run_all.sh --gen      # Generate test data for all scenarios, then run
#   bash run_all.sh --clean    # Clean all generated test data
#   bash run_all.sh --seq      # Run sequentially (easier to read logs)
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Discover all scenario directories (any subdir containing run.sh)
SCENARIOS=()
for d in "${SCRIPT_DIR}"/scenario*/; do
    [ -f "${d}run.sh" ] && SCENARIOS+=("${d}")
done

if [ ${#SCENARIOS[@]} -eq 0 ]; then
    echo "[run_all] No scenarios found under ${SCRIPT_DIR}/scenario*/" >&2
    exit 2
fi

MODE="${1:-}"

# ---------------------------------------------------------------------------
# Clean
# ---------------------------------------------------------------------------
if [ "${MODE}" = "--clean" ]; then
    for s in "${SCENARIOS[@]}"; do
        bash "${s}clean.sh"
    done
    exit 0
fi

# ---------------------------------------------------------------------------
# Generate (optional)
# ---------------------------------------------------------------------------
if [ "${MODE}" = "--gen" ]; then
    echo "[run_all] Generating test data for all scenarios..."
    for s in "${SCENARIOS[@]}"; do
        bash "${s}gen.sh"
    done
fi

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
PIDS=()
LOGS=()
NAMES=()

run_scenario() {
    local dir="$1"
    local name
    name=$(basename "${dir}")
    local log
    log=$(mktemp "/tmp/altfs-incindex-${name}.XXXXXX")
    bash "${dir}run.sh" >"${log}" 2>&1
    echo "${log}"
}

if [ "${MODE}" = "--seq" ]; then
    # Sequential run
    PASS=0
    FAIL=0
    for s in "${SCENARIOS[@]}"; do
        name=$(basename "${s}")
        if bash "${s}run.sh"; then
            PASS=$(( PASS + 1 ))
        else
            FAIL=$(( FAIL + 1 ))
            echo "[run_all] FAIL: ${name}" >&2
        fi
    done
else
    # Parallel run
    for s in "${SCENARIOS[@]}"; do
        name=$(basename "${s}")
        log=$(mktemp "/tmp/altfs-incindex-${name}.XXXXXX")
        bash "${s}run.sh" >"${log}" 2>&1 &
        PIDS+=($!)
        LOGS+=("${log}")
        NAMES+=("${name}")
    done

    PASS=0
    FAIL=0
    for i in "${!PIDS[@]}"; do
        if wait "${PIDS[$i]}"; then
            PASS=$(( PASS + 1 ))
            echo "[run_all] PASS: ${NAMES[$i]}"
        else
            FAIL=$(( FAIL + 1 ))
            echo "[run_all] FAIL: ${NAMES[$i]}" >&2
            cat "${LOGS[$i]}" >&2
        fi
        rm -f "${LOGS[$i]}"
    done
fi

echo ""
echo "[run_all] Results: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ]
