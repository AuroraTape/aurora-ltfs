#!/bin/sh
# Print a version string for AC_INIT, used via m4_esyscmd_s in configure.ac.
#
# Priority:
#   1. .tarball-version (written by release CI before autoreconf)
#   2. git describe against the release tags (vX.Y.Z, vX.Y.Z-rc.N):
#        on the tag         1.0.0
#        12 commits later   1.0.0-12-g<sha>   (sorts after the release)
#   3. "0.0.0-git-<sha>" when no release tag is reachable, e.g. in a
#      shallow clone such as the default actions/checkout
#   4. "0.0.0-manual" fallback (tarball without .tarball-version)
#
# A "-dirty" suffix marks a build from a modified working tree.

set -e

if [ -f .tarball-version ]; then
    cat .tarball-version
    exit 0
fi

if git rev-parse --git-dir >/dev/null 2>&1; then
    if desc=$(git describe --tags --match 'v[0-9]*' --abbrev=7 2>/dev/null); then
        version=${desc#v}
    else
        sha=$(git rev-parse --short=7 HEAD 2>/dev/null || echo unknown)
        version="0.0.0-git-$sha"
    fi
    if git diff --quiet HEAD -- 2>/dev/null; then
        printf '%s' "$version"
    else
        printf '%s-dirty' "$version"
    fi
    exit 0
fi

printf '0.0.0-manual'
