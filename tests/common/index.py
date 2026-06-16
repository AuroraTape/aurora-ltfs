"""Independent inspection of LTFS index XML records on the file backend.

These helpers parse the XML with Python's stdlib (xml.etree), which
shares no code with altfs's libxml2-based parser. A structural bug
that altfs's writer + reader both round-trip cleanly can still be
caught here.
"""

import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path

_IP_RECORD_RE = re.compile(r"^0_(\d+)_R$")


def find_latest_index_record(tape_dir):
    """Path to the highest-numbered IP record file whose content begins
    with an <ltfsindex> element (skips the VOL1 label and <ltfslabel>)."""
    candidates = []
    for name in os.listdir(tape_dir):
        m = _IP_RECORD_RE.match(name)
        if not m:
            continue
        path = Path(tape_dir) / name
        if b"<ltfsindex" in path.read_bytes()[:64]:
            candidates.append((int(m.group(1)), path))
    if not candidates:
        raise RuntimeError(f"no ltfsindex record found in {tape_dir}")
    candidates.sort()
    return candidates[-1][1]


def parse_latest_index(tape_dir):
    """Parse the latest IP index XML and return the root element."""
    return ET.parse(find_latest_index_record(tape_dir)).getroot()


def find_entries_by_name(root, names):
    """Walk all <file> and <directory> entries and return a dict mapping
    each matched name → element. Unmatched names are simply absent."""
    found = {}
    target = set(names)
    for elem in root.iter():
        if elem.tag in ("file", "directory"):
            name_el = elem.find("name")
            if name_el is not None and name_el.text in target:
                found[name_el.text] = elem
    return found
