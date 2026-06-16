#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

: "${ALTFS_PREFIX:=/workspaces/altfs}"
export PATH="${ALTFS_PREFIX}/bin:${PATH}"
export LD_LIBRARY_PATH="${ALTFS_PREFIX}/lib:${LD_LIBRARY_PATH:-}"

exec pytest "${SCRIPT_DIR}" "$@"
