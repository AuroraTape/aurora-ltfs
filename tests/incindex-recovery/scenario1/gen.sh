#!/bin/bash
#
# gen.sh - Generate test data for Scenario 1: Foundation
#
# Covers: L01 (file unchanged), L02 (file modified), L03 (file deleted),
#         L06 (new file created), D02 (new dir created), D03 (dir deleted)
#
# Prerequisites:
#   - FUSE available (/dev/fuse)
#   - `attr` package installed  (sudo apt-get install attr)
#   - Project installed (make install) to /workspaces/ltfs-oss
#
# Procedure:
#   Phase 1: Create ground truth
#     1. Format virtual tape with mkltfs
#     2. Mount
#     3. Create initial data (L01-L03, D03 setup)
#     4. Write full index  (ltfs.vendor.IBM.FullSync)
#     5. Perform incremental operations (L02 modify, L03 delete, L06+D02 create, D03 delete)
#     6. Write incremental index  (ltfs.vendor.IBM.IncrementalSync)
#     7. Snapshot tape dir   -> crash-state tape (before unmount full index)
#     8. Unmount             -> final full index written to DP and IP
#
#   Phase 2: Extract artifacts
#     9. Copy IP's last record (= final full index) as expected answer
#
# Output files (generated; all gitignored):
#   tape/              Tape dir after clean unmount (ground truth for verification)
#   tape-crashed/      Simulated crash-state tape (input to ltfsck -x)
#   expected/
#     full_index.xml   Expected full index XML after recovery
#

set -euo pipefail

# ---------------------------------------------------------------------------
# Resolve paths
# ---------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TAPE_DIR="${SCRIPT_DIR}/tape"
CRASHED_DIR="${SCRIPT_DIR}/tape-crashed"
EXPECTED_DIR="${SCRIPT_DIR}/expected"
MNT_DIR="/tmp/ltfs-mnt-scenario1"

# Use installed binaries and libraries under /workspaces/ltfs-oss
INSTALL_PREFIX="/workspaces/ltfs-oss"
export PATH="${INSTALL_PREFIX}/bin:${PATH}"
export LD_LIBRARY_PATH="${INSTALL_PREFIX}/lib:${LD_LIBRARY_PATH:-}"

# ---------------------------------------------------------------------------
# Prerequisite checks
# ---------------------------------------------------------------------------

log()  { echo "[scenario1/gen] $*"; }
die()  { echo "[scenario1/gen] ERROR: $*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1  (hint: $2)"; }

need mkltfs     "run 'make install' in the repo root"
need ltfs       "run 'make install' in the repo root"
need attr       "sudo apt-get install attr"
need fusermount "sudo apt-get install fuse"

[ -e /dev/fuse ] || die "/dev/fuse not found — FUSE is not available in this environment"

# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

write_full_index() {
    attr -s ltfs.vendor.IBM.FullSync -V "$1" "${MNT_DIR}" > /dev/null \
        || die "FullSync xattr failed"
    log "Full index written (reason: $1)"
}

write_inc_index() {
    attr -s ltfs.vendor.IBM.IncrementalSync -V "$1" "${MNT_DIR}" > /dev/null \
        || die "IncrementalSync xattr failed"
    log "Incremental index written (reason: $1)"
}

do_umount() {
    fusermount -u "${MNT_DIR}" 2>/dev/null \
        || sudo umount "${MNT_DIR}" \
        || die "umount failed"
    if [ -n "${LTFS_PID:-}" ]; then
        wait "${LTFS_PID}" 2>/dev/null || true
    fi
}

# ---------------------------------------------------------------------------
# Cleanup & setup
# ---------------------------------------------------------------------------

log "=== Scenario 1: Foundation ==="

rm -rf "${TAPE_DIR}" "${CRASHED_DIR}" "${EXPECTED_DIR}"
mkdir -p "${MNT_DIR}"

# ---------------------------------------------------------------------------
# Phase 1-1: Format virtual tape
# ---------------------------------------------------------------------------
log "Formatting virtual tape..."
mkdir -p "${TAPE_DIR}"
mkltfs -e file -d "${TAPE_DIR}" -s "SCN001" -n "Scenario1" -f \
    || die "mkltfs failed"

# ---------------------------------------------------------------------------
# Phase 1-2: Mount (sync_type=unmount: explicit sync via xattr, final sync on unmount)
# ---------------------------------------------------------------------------
log "Mounting tape at ${MNT_DIR}..."
ltfs -o tape_backend=file \
     -o devname="${TAPE_DIR}" \
     -o sync_type=unmount \
     "${MNT_DIR}" \
    || die "ltfs mount failed"

LTFS_PID=$(pgrep -n -f "devname=${TAPE_DIR}" 2>/dev/null || true)
log "ltfs PID: ${LTFS_PID:-unknown}"

# ---------------------------------------------------------------------------
# Phase 1-3: Create initial data
# ---------------------------------------------------------------------------
log "Creating initial data..."

# L01: file that will NOT be touched (should remain unchanged)
echo "baseline content" > "${MNT_DIR}/baseline.txt"

# L02: file that will be modified in the incremental step
echo "original content" > "${MNT_DIR}/modify_me.txt"

# L03: file that will be deleted in the incremental step
echo "will be deleted" > "${MNT_DIR}/delete_me.txt"

# D03: directory (with child) that will be fully deleted
mkdir "${MNT_DIR}/old_dir"
echo "orphan" > "${MNT_DIR}/old_dir/orphan.txt"

# ---------------------------------------------------------------------------
# Phase 1-4: Write full index
# ---------------------------------------------------------------------------
write_full_index "scenario1_initial"

# ---------------------------------------------------------------------------
# Phase 1-5: Incremental operations
# ---------------------------------------------------------------------------
log "Performing incremental operations..."

# L02: modify
echo "changed" >> "${MNT_DIR}/modify_me.txt"

# L03: delete
rm "${MNT_DIR}/delete_me.txt"

# L06 + D02: create new directory with a child file
mkdir "${MNT_DIR}/new_dir"
echo "hello" > "${MNT_DIR}/new_dir/child.txt"

# D03: delete directory and its child
rm "${MNT_DIR}/old_dir/orphan.txt"
rmdir "${MNT_DIR}/old_dir"

# ---------------------------------------------------------------------------
# Phase 1-6: Write incremental index
# ---------------------------------------------------------------------------
write_inc_index "scenario1_inc1"

# ---------------------------------------------------------------------------
# Phase 1-7: Snapshot = simulated crash state
#
#   At this point the tape contains:
#     DP: label + initial_full_index + file_data + full_index(step4)
#         + inc_index(step6) + EOD
#     IP: label + initial_full_index + full_index(step4) + EOD
#
#   The final full index (unmount) has NOT been written yet.
# ---------------------------------------------------------------------------
log "Snapshotting tape dir as crash state..."
cp -r "${TAPE_DIR}" "${CRASHED_DIR}"
rm -f "${CRASHED_DIR}"/attr_*
# Write manifest: list of files that exist at crash time (used by run.sh to reset)
ls "${CRASHED_DIR}" | sort > "${CRASHED_DIR}/.manifest"
log "  -> ${CRASHED_DIR}"

# ---------------------------------------------------------------------------
# Phase 1-8: Unmount (writes final full index to DP then updates IP)
# ---------------------------------------------------------------------------
log "Unmounting tape..."
do_umount

# ---------------------------------------------------------------------------
# Phase 2-9: Extract expected answer
# ---------------------------------------------------------------------------
log "Extracting expected full index from IP..."
mkdir -p "${EXPECTED_DIR}"

LAST_IP_INDEX=$(ls "${TAPE_DIR}"/0_*_R 2>/dev/null \
    | sort -t_ -k2 -n \
    | tail -1)

[ -n "${LAST_IP_INDEX}" ] \
    || die "No record blocks found in IP (partition 0) of ${TAPE_DIR}"

cp "${LAST_IP_INDEX}" "${EXPECTED_DIR}/full_index.xml"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
log ""
log "=== Generation complete ==="
log "Crash-state tape:    ${CRASHED_DIR}"
log "Expected full index: ${EXPECTED_DIR}/full_index.xml"
log "  (source: ${LAST_IP_INDEX})"
log ""
log "Expected final filesystem state:"
log "  /baseline.txt      present, unchanged   (L01)"
log "  /modify_me.txt     present, modified    (L02)"
log "  /delete_me.txt     GONE                 (L03)"
log "  /new_dir/          present              (D02)"
log "  /new_dir/child.txt present              (L06)"
log "  /old_dir/          GONE                 (D03)"
