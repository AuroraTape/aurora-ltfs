"""Independent inspection of LTFS index XML records.

These helpers capture the on-tape index with `altfsindextool`
and parse the resulting XML with Python's stdlib (xml.etree),
which shares no code with altfs's libxml2-based parser. A
structural bug that altfs's writer + reader both round-trip
cleanly can still be caught here.

The capture step (`altfsindextool ... --output-dir=...`) is the
public extraction path, so it works regardless of which tape
backend wrote the index — tests do not need to know how the
file backend names its on-disk records.
"""

import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path


_RUN_TIMEOUT = 30


def _capture_indexes(tape_dir, partition, dest):
    subprocess.run(
        ["altfsindextool",
         "-e", "file",
         "-d", str(tape_dir),
         f"--partition={partition}",
         f"--output-dir={dest}",
         "--quiet"],
        check=True,
        capture_output=True,
        timeout=_RUN_TIMEOUT,
    )


def _latest_captured(dest, partition):
    files = list(Path(dest).glob(f"ltfs-index-{partition}-*.xml"))
    if not files:
        raise RuntimeError(
            f"altfsindextool captured no index for partition {partition} "
            f"under {dest}"
        )
    return max(files, key=lambda p: int(p.stem.rsplit("-", 1)[-1]))


def parse_latest_index(tape_dir, partition=0):
    """Capture every index on `partition` and parse the highest-block
    one. Returns the parsed XML root element.

    Defaults to partition 0 (index partition): the IP carries the
    most recent index after `sync_type=unmount` finishes, so a
    single capture there yields the latest committed state."""
    with tempfile.TemporaryDirectory(prefix="altfs-idxcap-") as dest:
        _capture_indexes(tape_dir, partition, dest)
        return ET.parse(_latest_captured(dest, partition)).getroot()


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
