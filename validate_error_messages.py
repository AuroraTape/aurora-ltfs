#!/usr/bin/env python3

"""
Validate message IDs between source code and message bundle definitions.

Scans src/**/*.{c,h} for message IDs and messages/**/*.txt for the same
pattern in :string lines. Reports unused (defined but not referenced in
source) and undefined (referenced in source but not defined) message IDs.

The 4-character number field is either four digits (added on HEAD) or one
of the letter-bearing release-branch shapes (e.g. AFSA001E for 1.0.x,
AFSAA01E for 1.1.x) - see "Release-branch ID shapes" in messages/README.

With --target-branch release/X.Y and --base REF, additionally checks that
every message ID added relative to REF either uses the shape of the X.Y.x
pool or is a backport (already defined on the trunk given by --trunk).
"""

import argparse
import os
import re
import subprocess
import sys

# Message ID: e.g. ALC0002E, ALG0001W (HEAD), AFSA001E, AFSAA01E (release
# branches). The \b anchors keep the letter-bearing shapes from matching
# inside longer identifiers.
MSGID = r'A[A-Z]{2}(?:\d{4}|[A-Z]\d{3}|[A-Z]{2}\d{2})[EIWD]'
re_msgid_source = re.compile(r'\b(' + MSGID + r')\b')
re_msgid_bundle = re.compile(r'\b(' + MSGID + r'):string')
re_release_branch = re.compile(r'^release/(\d+)\.(\d+)$')

# Prefixes to exclude from unused checks.
# Internal error messages (AEI/AED) serve as an error code registry —
# they must have definitions even when not directly referenced as message strings.
# Individual IDs to exclude from unused checks (with reason).
# Remove entries as they get resolved.
UNUSED_EXEMPT_IDS = {
    "AFS0101I",  # default device display — see GitHub issue #21
}

msg_used = set()
msg_defined = dict()  # module -> set of IDs


def scan_source():
    """Scan source files for message ID references."""
    for dirpath, dirs, files in os.walk('src'):
        for f in files:
            if re.search(r'\.[ch]$', f):
                filepath = os.path.join(dirpath, f)
                with open(filepath, 'r') as fd:
                    for line in fd:
                        for m in re_msgid_source.finditer(line):
                            msg_used.add(m.group(1))


def bundle_ids(lines):
    """Return the message IDs defined by the lines of a bundle .txt file."""
    ids = set()
    for line in lines:
        # Strip comments
        comment_pos = line.find('//')
        if comment_pos >= 0:
            line = line[:comment_pos]
        for m in re_msgid_bundle.finditer(line):
            ids.add(m.group(1))
    return ids


def scan_messages():
    """Scan message bundle .txt files for message ID definitions."""
    for dirpath, dirs, files in os.walk('messages'):
        if dirpath == 'messages':
            continue
        module_ids = set()
        for f in files:
            if f.endswith('.txt'):
                filepath = os.path.join(dirpath, f)
                with open(filepath, 'r') as fd:
                    module_ids |= bundle_ids(fd)
        if module_ids:
            msg_defined[os.path.basename(dirpath)] = module_ids


def git_output(*args):
    return subprocess.run(('git',) + args, check=True, text=True,
                          stdout=subprocess.PIPE).stdout


def defined_ids_at(ref):
    """Return the message IDs defined in the bundles of a git revision."""
    ids = set()
    for path in git_output('ls-tree', '-r', '--name-only', ref,
                           'messages/').splitlines():
        if path.endswith('.txt') and path.count('/') >= 2:
            ids |= bundle_ids(git_output('show', f'{ref}:{path}').splitlines())
    return ids


def pool_shape(major, minor):
    """Return (regex, example) of the number field for the M.m.x pool."""
    if not (1 <= major <= 26 and 0 <= minor <= 26):
        raise ValueError(f"version {major}.{minor} is out of scope for ID pools")
    major_letter = chr(ord('A') + major - 1)
    if minor == 0:
        return re.compile(major_letter + r'\d{3}'), major_letter + '001'
    minor_letter = chr(ord('A') + minor - 1)
    return (re.compile(major_letter + minor_letter + r'\d{2}'),
            major_letter + minor_letter + '01')


def check_release_pool(all_defined, target_branch, base, trunk):
    """Check the shape of the IDs a change adds to a release branch.

    An added ID must come from the pool of the release line, or be a
    backport that keeps the ID it already has on the trunk. AEI/AED have
    no release-branch shape (their numbers are derived from the error
    constants), so they can only be backports.
    """
    m = re_release_branch.match(target_branch)
    if not m:
        return 0

    shape, example = pool_shape(int(m.group(1)), int(m.group(2)))
    added = all_defined - defined_ids_at(base)
    trunk_ids = defined_ids_at(trunk) if added else set()

    bad = []
    for mid in sorted(added):
        in_pool = (mid[:3] not in ('AEI', 'AED')
                   and shape.fullmatch(mid[3:7]))
        if not in_pool and mid not in trunk_ids:
            bad.append(mid)

    if bad:
        print(f"Found {len(bad)} message IDs added to {target_branch} that are "
              f"neither in its pool (e.g. AFS{example}E) nor backported from "
              f"{trunk} (see \"Release-branch ID shapes\" in messages/README):")
        for mid in bad:
            print(f"\t{mid}")
        return 1

    print(f"{len(added)} message IDs added relative to {base}; "
          f"all fit {target_branch}.")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument('--target-branch', default='',
                        help="branch the change is going into; the pool check "
                             "runs only for release/X.Y")
    parser.add_argument('--base', help="git revision the change is based on "
                                       "(required for the pool check)")
    parser.add_argument('--trunk', default='origin/main',
                        help="git revision of the trunk, used to recognize "
                             "backports (default: %(default)s)")
    args = parser.parse_args()
    if re_release_branch.match(args.target_branch) and not args.base:
        parser.error("--base is required when --target-branch is release/X.Y")

    scan_source()
    scan_messages()

    all_defined = set()
    for module, ids in msg_defined.items():
        all_defined |= ids

    # Unused: defined in messages but not referenced in source
    # Exclude prefixes that serve as registries (e.g., internal error codes)
    unused = {mid for mid in (all_defined - msg_used)
              if mid not in UNUSED_EXEMPT_IDS}
    # Undefined: referenced in source but not defined in messages
    undefined = msg_used - all_defined

    exit_code = 0

    if unused:
        print(f"Found {len(unused)} unused message IDs (defined but not in source):")
        for mid in sorted(unused):
            print(f"\t{mid}")
        exit_code = 1

    if undefined:
        print(f"Found {len(undefined)} undefined message IDs (in source but not defined):")
        for mid in sorted(undefined):
            print(f"\t{mid}")
        exit_code = 1

    if exit_code == 0:
        print("All message IDs are consistent.")

    if check_release_pool(all_defined, args.target_branch, args.base,
                          args.trunk):
        exit_code = 1

    return exit_code


if __name__ == '__main__':
    sys.exit(main())
