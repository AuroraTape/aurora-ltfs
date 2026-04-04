#!/bin/bash
#
# clean.sh - Remove all generated test data for Scenario 1
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "[scenario1/clean] Removing generated test data..."
rm -rf "${SCRIPT_DIR}/tape" \
       "${SCRIPT_DIR}/tape-crashed" \
       "${SCRIPT_DIR}/expected"
rm -f  "${SCRIPT_DIR}"/*.log
echo "[scenario1/clean] Done."
