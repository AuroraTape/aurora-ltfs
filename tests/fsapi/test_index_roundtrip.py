"""Round-trip + independent index validation.

The module-scoped mounted_tape fixture only exercises altfs's
read/write of the index once per test file. This test cycles
format → mount → write → umount → independent XML inspection →
re-mount → verify → umount, so it covers both that the on-tape
index reconstructs into the same view AND that the XML matches
what we wrote, verified by a parser (stdlib xml.etree) that
shares no code with altfs.
"""

import pytest

from common.altfs import format_tape, mount_tape, umount_tape
from common.helpers import get_xattr, set_xattr
from common.index import find_entries_by_name, parse_latest_index


_BIG_LEN = 700 * 1024  # > 1 × 512 KiB block, exercises multi-extent
_BIG_BYTE = b"X"


def test_index_roundtrip(tmp_path_factory):
    base = tmp_path_factory.mktemp("altfs-roundtrip")
    tape_dir = base / "tape"
    mnt = base / "mnt"
    tape_dir.mkdir()
    mnt.mkdir()

    format_tape(tape_dir, serial="ROUND0", label="roundtrip")

    # Round 1: populate with diverse content
    mount_tape(tape_dir, mnt)
    try:
        (mnt / "regular.txt").write_text("payload-A")
        (mnt / "subdir").mkdir()
        (mnt / "subdir" / "inner.txt").write_text("inside")
        set_xattr(mnt / "regular.txt", "test.tag", "v1")
        (mnt / "ro.txt").write_text("ro content")
        (mnt / "ro.txt").chmod(0o444)
        (mnt / "big.bin").write_bytes(_BIG_BYTE * _BIG_LEN)
        (mnt / "link").symlink_to(mnt / "regular.txt")
    finally:
        umount_tape(mnt)

    # Independent inspection of what altfs wrote to tape.
    root = parse_latest_index(tape_dir)
    assert root.tag == "ltfsindex"
    assert int(root.find("generationnumber").text) >= 2

    entries = find_entries_by_name(
        root,
        {"regular.txt", "subdir", "inner.txt", "ro.txt", "big.bin", "link"},
    )
    assert set(entries) == {"regular.txt", "subdir", "inner.txt", "ro.txt", "big.bin", "link"}

    assert int(entries["regular.txt"].find("length").text) == len("payload-A")
    assert int(entries["big.bin"].find("length").text) == _BIG_LEN
    assert entries["ro.txt"].find("readonly").text == "true"
    assert entries["link"].find("symlink") is not None

    xattrs = {
        x.find("key").text: x.find("value").text
        for x in entries["regular.txt"].iter("xattr")
    }
    assert xattrs.get("test.tag") == "v1"

    # Round 2: re-mount and verify everything reads back through altfs.
    mount_tape(tape_dir, mnt)
    try:
        assert (mnt / "regular.txt").read_text() == "payload-A"
        assert (mnt / "subdir" / "inner.txt").read_text() == "inside"
        assert (mnt / "ro.txt").read_text() == "ro content"
        assert (mnt / "big.bin").stat().st_size == _BIG_LEN
        assert (mnt / "big.bin").read_bytes() == _BIG_BYTE * _BIG_LEN
        assert (mnt / "link").read_text() == "payload-A"
        assert get_xattr(mnt / "regular.txt", "test.tag") == "v1"
        with pytest.raises(PermissionError):
            open(mnt / "ro.txt", "w")
    finally:
        umount_tape(mnt)
