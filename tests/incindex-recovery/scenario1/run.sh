#!/bin/bash
#
# run.sh - Run recovery test for Scenario 1 and verify the result
#
# Usage:
#   bash run.sh            # Run test (requires pre-generated test data)
#   bash run.sh --gen      # Generate test data first, then run
#   bash run.sh --clean    # Remove all generated test data
#
# Exit codes:
#   0  PASS
#   1  FAIL
#   2  Setup error (missing test data, missing binaries, etc.)
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TAPE_DIR="${SCRIPT_DIR}/tape"
CRASHED_DIR="${SCRIPT_DIR}/tape-crashed"
EXPECTED_DIR="${SCRIPT_DIR}/expected"

INSTALL_PREFIX="/workspaces/altfs"
export PATH="${INSTALL_PREFIX}/bin:${PATH}"
export LD_LIBRARY_PATH="${INSTALL_PREFIX}/lib:${LD_LIBRARY_PATH:-}"

log()  { echo "[scenario1/run] $*"; }
pass() { echo "[scenario1/run] PASS: $*"; }
fail() { echo "[scenario1/run] FAIL: $*" >&2; exit 1; }
die()  { echo "[scenario1/run] ERROR: $*" >&2; exit 2; }

# ---------------------------------------------------------------------------
# Option handling
# ---------------------------------------------------------------------------

case "${1:-}" in
    --clean)
        log "Cleaning generated test data..."
        rm -rf "${TAPE_DIR}" "${CRASHED_DIR}" "${EXPECTED_DIR}"
        log "Clean complete."
        exit 0
        ;;
    --gen)
        bash "${SCRIPT_DIR}/gen.sh"
        ;;
    "")
        ;;
    *)
        echo "Usage: $0 [--gen | --clean]" >&2
        exit 2
        ;;
esac

# ---------------------------------------------------------------------------
# Prerequisite checks
# ---------------------------------------------------------------------------

[ -d "${CRASHED_DIR}" ] \
    || die "Crash-state tape not found: ${CRASHED_DIR}  (run with --gen first)"
[ -d "${TAPE_DIR}" ] \
    || die "Ground-truth tape not found: ${TAPE_DIR}  (run with --gen first)"
[ -f "${CRASHED_DIR}/.manifest" ] \
    || die "Crash-state manifest not found  (re-run gen.sh)"

command -v altfsck >/dev/null 2>&1 \
    || die "altfsck not found — run 'make install' in the repo root"

# ---------------------------------------------------------------------------
# Reset crash-state tape
#
# gen.sh wrote tape-crashed/.manifest listing the files present at crash time.
# Restore that exact state: remove anything added by a previous recovery run,
# and restore any empty marker files (F/E) that altfsck removed.
# ---------------------------------------------------------------------------
log "Resetting crash-state tape..."

# Remove files not present at crash time (e.g. recovery output blocks, attr_*)
for f in "${CRASHED_DIR}"/*; do
    [ -e "$f" ] || continue
    fname=$(basename "$f")
    [ "${fname}" = ".manifest" ] && continue
    grep -qxF "${fname}" "${CRASHED_DIR}/.manifest" || rm -f "$f"
done

# Restore empty marker files (F/E) that may have been removed by altfsck
while IFS= read -r fname; do
    [ -e "${CRASHED_DIR}/${fname}" ] || touch "${CRASHED_DIR}/${fname}"
done < "${CRASHED_DIR}/.manifest"

log "  Reset complete ($(wc -l < "${CRASHED_DIR}/.manifest") files restored)"

# ---------------------------------------------------------------------------
# Run recovery
# ---------------------------------------------------------------------------
log "Running altfsck -x ..."

ALTFSCK_LOG="${SCRIPT_DIR}/altfsck.log"
set +o pipefail
altfsck -e file -x "${CRASHED_DIR}" 2>&1 | tee "${ALTFSCK_LOG}"
ALTFSCK_RC=${PIPESTATUS[0]}
set -o pipefail
log "altfsck exit code: ${ALTFSCK_RC}"

# ---------------------------------------------------------------------------
# Verify: recovered full index exists in IP
# ---------------------------------------------------------------------------
RECOVERED=$(ls "${CRASHED_DIR}"/0_*_R 2>/dev/null \
    | sort -t_ -k2 -n | tail -1 || true)
[ -n "${RECOVERED}" ] \
    || fail "No full index written to IP after recovery"

log "Recovered full index: ${RECOVERED}"

# ---------------------------------------------------------------------------
# Verify: log messages
# ---------------------------------------------------------------------------
check_msg() {
    local id="$1" desc="$2"
    grep -q "${id}" "${ALTFSCK_LOG}" \
        || fail "Expected log message ${id} (${desc}) not found"
}

check_msg "11361I" "MODIFY modify_me.txt"
check_msg "11358I" "CREATE child.txt / new_dir"
check_msg "11365I" "DELETE delete_me.txt / old_dir"
check_msg "11373I" "Applied successfully"
check_msg "11379I" "Recovery complete"

# ---------------------------------------------------------------------------
# Verify: file metadata matches ground truth
# ---------------------------------------------------------------------------
GROUND_TRUTH_INDEX=$(ls "${TAPE_DIR}"/0_*_R 2>/dev/null \
    | sort -t_ -k2 -n | tail -1)

extract_key_fields() {
    grep -E "<(name|length|fileuid|startblock|bytecount|partition)>" "$1" | sort
}

DIFF=$(diff \
    <(extract_key_fields "${RECOVERED}") \
    <(extract_key_fields "${GROUND_TRUTH_INDEX}") || true)

# The only expected difference is <startblock> for the index block itself
# (recovered index lands at a different tape block than clean unmount).
NON_STARTBLOCK_DIFF=$(echo "${DIFF}" \
    | grep -v "^[0-9]" \
    | grep -v "^---$" \
    | grep -v "startblock" \
    || true)

if [ -n "${NON_STARTBLOCK_DIFF}" ]; then
    echo "--- recovered ---"
    extract_key_fields "${RECOVERED}"
    echo "--- ground truth ---"
    extract_key_fields "${GROUND_TRUTH_INDEX}"
    fail "Recovered index differs from ground truth (see above)"
fi

# ---------------------------------------------------------------------------
# Verify: deleted files are absent, expected files are present
# ---------------------------------------------------------------------------
check_absent() {
    grep -q "<name>$1</name>" "${RECOVERED}" \
        && { fail "Deleted entry '$1' still present in recovered index"; } || true
}
check_present() {
    grep -q "<name>$1</name>" "${RECOVERED}" \
        || fail "Expected entry '$1' missing from recovered index"
}

check_present "baseline.txt"
check_present "modify_me.txt"
check_present "new_dir"
check_present "child.txt"
check_absent  "delete_me.txt"
check_absent  "old_dir"

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
log "altfsck log: ${ALTFSCK_LOG}"
pass "Scenario 1 recovery test passed."
