"""Round-trip for file and directory names that require percent
encoding in the on-tape XML index.

LTFS reserves a small set of code points that must not appear
literally in <name> elements: the ASCII colon (`:`, 0x3A) and the
C0 control characters except TAB/LF/CR. When a name contains any
of them, libltfs writes the name with `percentencoded="true"` and
escapes the disallowed bytes as `%XX`. The reader does the inverse.

Without this test the encoder and decoder are exercised only when
some other test happens to use a control character — currently
none do, so both code paths were entirely unwalked by CI.

Pattern follows test_index_roundtrip.py: format → mount → write →
umount → inspect the IP record with the stdlib XML parser → re-mount
→ verify names come back identical and content is intact.
"""

import xml.etree.ElementTree as ET

from common.altfs import format_tape, mount_tape, umount_tape
from common.index import find_latest_index_record


FILE_NAME = "log:2026-06-16.txt"        # `:` triggers percent encoding
DIR_NAME = "session:01"                 # same trigger on a directory
INNER_NAME = "plain.txt"                # nested non-encoded name
FILE_BODY = "payload-with-colon"
INNER_BODY = "inside the percent-encoded directory"


def _walk_named_entries(root):
    """Yield (tag, name_element) for every <file>/<directory> in the index."""
    for elem in root.iter():
        if elem.tag in ("file", "directory"):
            name_el = elem.find("name")
            if name_el is not None:
                yield elem.tag, name_el


def test_percent_encoded_names_round_trip(tmp_path_factory):
    base = tmp_path_factory.mktemp("altfs-percent")
    tape_dir = base / "tape"
    mnt = base / "mnt"
    tape_dir.mkdir()
    mnt.mkdir()

    format_tape(tape_dir, serial="PCTENC", label="percent")

    mount_tape(tape_dir, mnt)
    try:
        (mnt / FILE_NAME).write_text(FILE_BODY)
        (mnt / DIR_NAME).mkdir()
        (mnt / DIR_NAME / INNER_NAME).write_text(INNER_BODY)
    finally:
        umount_tape(mnt)

    # Inspect the raw XML: the writer should have emitted the colon
    # as %3A and tagged the element percentencoded="true".
    index_path = find_latest_index_record(tape_dir)
    tree = ET.parse(index_path)
    root = tree.getroot()

    by_encoded_name = {}
    for tag, name_el in _walk_named_entries(root):
        by_encoded_name[name_el.text] = (tag, name_el)

    encoded_file = FILE_NAME.replace(":", "%3A")
    encoded_dir = DIR_NAME.replace(":", "%3A")

    assert encoded_file in by_encoded_name, sorted(by_encoded_name)
    assert encoded_dir in by_encoded_name, sorted(by_encoded_name)

    file_tag, file_name_el = by_encoded_name[encoded_file]
    dir_tag, dir_name_el = by_encoded_name[encoded_dir]
    assert file_tag == "file"
    assert dir_tag == "directory"
    assert file_name_el.attrib.get("percentencoded") == "true"
    assert dir_name_el.attrib.get("percentencoded") == "true"

    # A plain-ASCII sibling should NOT be flagged — verifies the
    # writer only sets the attribute when actually needed.
    assert INNER_NAME in by_encoded_name
    _, inner_name_el = by_encoded_name[INNER_NAME]
    assert inner_name_el.attrib.get("percentencoded") in (None, "false")

    # Re-mount: the reader must decode %3A back to ':' so the name
    # is visible through FUSE under its original spelling.
    mount_tape(tape_dir, mnt)
    try:
        assert (mnt / FILE_NAME).read_text() == FILE_BODY
        assert (mnt / DIR_NAME / INNER_NAME).read_text() == INNER_BODY

        listing = {p.name for p in mnt.iterdir()}
        assert FILE_NAME in listing
        assert DIR_NAME in listing
    finally:
        umount_tape(mnt)
