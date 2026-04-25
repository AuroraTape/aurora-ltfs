#!/usr/bin/env python3

"""
Validate message IDs between source code and message bundle definitions.

Scans src/**/*.{c,h} for message IDs matching A[A-Z]{2}\\d{4}[EIWD],
and messages/**/*.txt for the same pattern in :string lines.
Reports unused (defined but not referenced in source) and
undefined (referenced in source but not defined) message IDs.
"""

import os
import re
import sys

# Pattern for new-format message IDs: e.g. ALC0002E, ALG0001W
re_msgid_source = re.compile(r'(A[A-Z]{2}\d{4}[EIWD])')
re_msgid_bundle = re.compile(r'(A[A-Z]{2}\d{4}[EIWD]):string')

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
                    for line in fd:
                        # Strip comments
                        comment_pos = line.find('//')
                        if comment_pos >= 0:
                            line = line[:comment_pos]
                        for m in re_msgid_bundle.finditer(line):
                            module_ids.add(m.group(1))
        if module_ids:
            msg_defined[os.path.basename(dirpath)] = module_ids


def main():
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

    return exit_code


if __name__ == '__main__':
    sys.exit(main())
