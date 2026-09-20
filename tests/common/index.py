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


# accesstime is left out: reading a file moves it without making the
# index dirty, so it is no part of what an index has to reproduce.
_TIME_TAGS = ("creationtime", "changetime", "modifytime", "backuptime")


def index_records(root):
    """Flatten an index into a dict: path -> what the index records
    about the object (kind, UID, read-only flag, time stamps, extended
    attributes, and for a file its length, symlink target and extents).
    The root directory is recorded under the path "" (its name is the
    volume name and is left out).

    Two indexes that describe the same file system state produce equal
    dicts, wherever they sit on the tape and whatever their generation
    is; this is what a recovered index is compared against."""
    records = {}

    def text(elem, tag):
        child = elem.find(tag)
        return None if child is None else (child.text or "")

    def describe(elem):
        return {
            "kind": elem.tag,
            "fileuid": text(elem, "fileuid"),
            "readonly": text(elem, "readonly"),
            "times": {t: text(elem, t) for t in _TIME_TAGS},
            "xattrs": sorted(
                (text(x, "key"), text(x, "value"))
                for x in elem.iterfind("extendedattributes/xattr")),
        }

    def walk(directory, prefix):
        contents = directory.find("contents")
        for elem in (contents if contents is not None else ()):
            if elem.tag not in ("file", "directory"):
                continue
            path = prefix + text(elem, "name")
            record = describe(elem)
            if elem.tag == "file":
                record["length"] = text(elem, "length")
                record["symlink"] = text(elem, "symlink")
                record["extents"] = [
                    tuple(text(x, t) for t in
                          ("fileoffset", "partition", "startblock",
                           "byteoffset", "bytecount"))
                    for x in elem.iterfind("extentinfo/extent")]
            records[path] = record
            if elem.tag == "directory":
                walk(elem, path + "/")

    root_dir = root.find("directory")
    records[""] = describe(root_dir)
    walk(root_dir, "")
    return records
