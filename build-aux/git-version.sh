#!/bin/sh
# Print a version string for AC_INIT, used via m4_esyscmd_s in configure.ac.
#
# Priority:
#   1. .tarball-version (written by release CI before autoreconf)
#   2. git describe (when invoked from a git checkout)
#   3. "0.0.0-manual" fallback (tarball without .tarball-version)

set -e

if [ -f .tarball-version ]; then
    cat .tarball-version
    exit 0
fi

if git rev-parse --git-dir >/dev/null 2>&1; then
    sha=$(git rev-parse --short=7 HEAD 2>/dev/null || echo unknown)
    if git diff --quiet HEAD -- 2>/dev/null; then
        printf '0.0.0-git-%s' "$sha"
    else
        printf '0.0.0-git-%s-dirty' "$sha"
    fi
    exit 0
fi

printf '0.0.0-manual'
