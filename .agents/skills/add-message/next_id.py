#!/usr/bin/env python3
"""Print the next free HEAD-pool (4-digit) message number for a prefix.

Usage: next_id.py <PREFIX>        e.g. next_id.py AMK

Counts every number that has ever appeared in the bundle for that prefix,
including commented-out / "unused" entries, so retired numbers are never
handed out again. Exits 1 for an unknown prefix (and for AEI/AED, whose
numbers are derived, not allocated), 2 for a usage error.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
MSG_DIR = os.path.join(ROOT, "messages")


def main():
    if len(sys.argv) != 2 or not re.fullmatch(r"A[A-Z]{2}", sys.argv[1]):
        print(__doc__, file=sys.stderr)
        return 2
    prefix = sys.argv[1]
    if prefix in ("AEI", "AED"):
        print(f"{prefix}: numbers are derived from LTFS_*/EDEV_* constants in "
              "src/libltfs/ltfs_error.h, not allocated consecutively.", file=sys.stderr)
        return 1

    id_re = re.compile(rf"\b{prefix}(\d{{4}})[EIWD]\b")
    numbers = set()
    files = []
    for dirpath, _, names in os.walk(MSG_DIR):
        for n in names:
            if not n.endswith("root.txt"):
                continue
            path = os.path.join(dirpath, n)
            with open(path, encoding="utf-8") as fd:
                text = fd.read()
            if f'prefix:string {{ "{prefix}" }}' not in text:
                continue
            files.append(os.path.relpath(path, ROOT))
            for m in id_re.finditer(text):
                numbers.add(int(m.group(1)))
    if not files:
        print(f"{prefix}: no bundle declares this prefix under messages/", file=sys.stderr)
        return 1

    nxt = (max(numbers) + 1) if numbers else 1
    print(f"prefix:   {prefix}")
    print(f"bundle:   {', '.join(files)}")
    print(f"max used: {max(numbers):04d}" if numbers else "max used: (none)")
    print(f"next id:  {prefix}{nxt:04d}<E|W|I|D>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
