#!/bin/bash
#
# Render the formula of the Homebrew tap (#131) from .github/homebrew/aurora-ltfs.rb.in.
#
# Usage: render-homebrew-formula.sh [--rebuild <n> <root url>] <url> <sha256> [<bottle json>...]
#
#   --rebuild      without bottle files: a bottle block holding only the root_url and
#                  "rebuild <n>", from which "brew bottle --keep-old" takes the rebuild
#                  number of the bottle it writes
#   <url>          the source tarball
#   <sha256>       its checksum
#   <bottle json>  the files written by "brew bottle --json", one per bottle; without
#                  them (and without --rebuild) the formula has no bottle block and
#                  builds from source
#
# The formula is written to the standard output.

set -euo pipefail

usage() {
	echo "Usage: $0 [--rebuild <n> <root url>] <url> <sha256> [<bottle json>...]" >&2
	exit 2
}

REBUILD=0
if [ "${1:-}" = "--rebuild" ]; then
	[ $# -ge 3 ] || usage
	REBUILD=$2
	ROOT_URL=$3
	shift 3
fi
[ $# -ge 2 ] || usage

URL=$1
SHA256=$2
shift 2
TEMPLATE=$(dirname "$0")/../homebrew/aurora-ltfs.rb.in

bottle=""
if [ $# -gt 0 ]; then
	# One root_url and rebuild for all bottles. "brew bottle --json" writes the cellar
	# as a string: any or any_skip_relocation (symbols in the formula), or a path.
	bottle=$(jq -rs '
		[.[] | to_entries[] | .value.bottle] as $b
		| ($b | map(.root_url) | unique) as $roots
		| ($b | map(.rebuild // 0) | unique) as $rebuilds
		| if ($roots | length) != 1 or ($rebuilds | length) != 1
		  then error("bottles with different root_url or rebuild: \($roots) \($rebuilds)") else . end
		| "\n  bottle do\n    root_url \"\($roots[0])\"\n"
		  + (if $rebuilds[0] > 0 then "    rebuild \($rebuilds[0])\n" else "" end)
		  + ([$b[] | (.cellar | ltrimstr(":")) as $c | .tags | to_entries[]
		      | "    sha256 cellar: \(if $c == "any" or $c == "any_skip_relocation" then ":" + $c else "\"" + $c + "\"" end), \(.key): \"\(.value.sha256)\"\n"]
		     | sort | join(""))
		  + "  end"
	' "$@")
elif [ "$REBUILD" -gt 0 ]; then
	bottle=$(printf '\n  bottle do\n    root_url "%s"\n    rebuild %d\n  end' "$ROOT_URL" "$REBUILD")
fi

# awk, not sed: the bottle block spans lines and the URL holds slashes
awk -v url="$URL" -v sha="$SHA256" -v bottle="$bottle" '
	{ gsub(/@URL@/, url); gsub(/@SHA256@/, sha) }
	# A blank line, or the bottle block between blank lines
	/^@BOTTLE@$/ { print bottle; if (bottle != "") print ""; next }
	{ print }
' "$TEMPLATE"
