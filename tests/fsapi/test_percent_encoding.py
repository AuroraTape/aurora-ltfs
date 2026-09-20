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

from common.altfs import format_tape, mount_tape, umount_tape
from common.index import parse_latest_index


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
    root = parse_latest_index(tape_dir)

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


# US (Unit Separator, 0x1f) used to be refused in names and mangled by
# the index reader (issue #83). It is a control character like the
# others: legal in a name, percent encoded in the index.
US_FILE_NAME = "unit\x1fseparated.txt"
US_DIR_NAME = "dir\x1fwith\x1fus"
US_BODY = "payload-with-us"


def test_unit_separator_in_names_round_trip(tmp_path_factory):
    base = tmp_path_factory.mktemp("altfs-us")
    tape_dir = base / "tape"
    mnt = base / "mnt"
    tape_dir.mkdir()
    mnt.mkdir()

    format_tape(tape_dir, serial="USNAME", label="us")

    mount_tape(tape_dir, mnt)
    try:
        (mnt / US_FILE_NAME).write_text(US_BODY)
        (mnt / US_DIR_NAME).mkdir()
        (mnt / US_DIR_NAME / INNER_NAME).write_text(INNER_BODY)
        assert US_FILE_NAME in {p.name for p in mnt.iterdir()}
    finally:
        umount_tape(mnt)

    # The raw control character must not reach the XML: %1F and the
    # percentencoded attribute instead.
    root = parse_latest_index(tape_dir)
    by_encoded_name = {name_el.text: name_el
                       for _, name_el in _walk_named_entries(root)}
    for name in (US_FILE_NAME, US_DIR_NAME):
        encoded = name.replace("\x1f", "%1F")
        assert encoded in by_encoded_name, sorted(by_encoded_name)
        assert by_encoded_name[encoded].attrib.get("percentencoded") == "true"

    mount_tape(tape_dir, mnt)
    try:
        assert (mnt / US_FILE_NAME).read_text() == US_BODY
        assert (mnt / US_DIR_NAME / INNER_NAME).read_text() == INNER_BODY
        listing = {p.name for p in mnt.iterdir()}
        assert {US_FILE_NAME, US_DIR_NAME} <= listing, sorted(listing)

        # The name keeps working for the operations that look it up.
        (mnt / US_FILE_NAME).rename(mnt / US_DIR_NAME / US_FILE_NAME)
        assert (mnt / US_DIR_NAME / US_FILE_NAME).read_text() == US_BODY
    finally:
        umount_tape(mnt)


def test_index_with_percent_encoded_us_is_read_as_us(tmp_path_factory):
    """An index written by another implementation that holds %1F in a
    percent encoded name: the reader must give the US back instead of
    keeping the literal "%1F" or turning it into "_".

    The index is produced by writing a name with a colon and changing
    %3A into %1F in every index record in place (same length, so the
    record sizes of the file backend stay valid). The MAM attribute
    files do not hold names, the volume stays consistent."""
    base = tmp_path_factory.mktemp("altfs-us-foreign")
    tape_dir = base / "tape"
    mnt = base / "mnt"
    tape_dir.mkdir()
    mnt.mkdir()

    format_tape(tape_dir, serial="USREAD", label="usread")

    mount_tape(tape_dir, mnt)
    try:
        (mnt / "foreign:name.txt").write_text(US_BODY)
    finally:
        umount_tape(mnt)

    patched = 0
    for record in tape_dir.glob("*_R"):
        data = record.read_bytes()
        if b"foreign%3Aname.txt" in data:
            record.write_bytes(data.replace(b"foreign%3Aname.txt",
                                            b"foreign%1Fname.txt"))
            patched += 1
    assert patched >= 2, "expected the name in the index of both partitions"

    mount_tape(tape_dir, mnt)
    try:
        listing = {p.name for p in mnt.iterdir()}
        assert listing == {"foreign\x1fname.txt"}, sorted(listing)
        assert (mnt / "foreign\x1fname.txt").read_text() == US_BODY
    finally:
        umount_tape(mnt)
