#!/bin/bash
# Cross-platform volume check (issue #141). Needs ALTFS_IMAGE_DIR, the output
# of make_images.py; see test_images.py.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

: "${ALTFS_PREFIX:=/workspaces/altfs}"
export PATH="${ALTFS_PREFIX}/bin:${PATH}"
export LD_LIBRARY_PATH="${ALTFS_PREFIX}/lib:${LD_LIBRARY_PATH:-}"

exec pytest "${SCRIPT_DIR}" "$@"
