"""Incremental index round trip: write, crash, recover (issue #133).

Every case builds a small tree, writes a full index, applies changes
and writes them as one or more incremental indexes through the
``ltfs.vendor.Aurora.IncrementalSync`` extended attribute. A copy of
the tape directory taken at that moment is the state a crash would
leave behind (the MAM ``attr_*`` files are left out so the volume
coherency shortcut cannot hide the incremental indexes). ``altfsck``
has to replay the incremental indexes on top of the last full index,
and the recovered volume must show exactly the tree that was mounted
when the last incremental index was written: names, file contents,
link targets, the read-only flag and the extended attributes
(issue #136).

The recovered full index is also compared with the full index that
the clean unmount of the original volume wrote (the ground truth): same
objects, UIDs, time stamps, flags, extended attributes and extents.

This module replaces the shell harness ``tests/incindex-recovery``
(issue #79); its scenario 1 is the case ``foundation``.

The cases themselves live in tests/common/incindex_cases.py; the
cross-platform volume check (tests/xplat) builds the same crash states.
"""

import shutil

import pytest

from common.altfs import (
    LTFSCK_CORRECTED,
    format_tape,
    mount_tape,
    run_altfsck,
    umount_tape,
)
from common.helpers import full_sync, incremental_sync
from common.incindex_cases import CASES, setup_base
from common.recovery import crash_and_recover

pytestmark = pytest.mark.mount  # every test here goes through a FUSE mount


@pytest.mark.parametrize("steps", [c[1] for c in CASES],
                         ids=[c[0] for c in CASES])
def test_recovered_tree_matches_mounted_tree(tmp_path, steps):
    tape_dir = tmp_path / "tape"
    crashed_dir = tmp_path / "tape-crashed"
    mnt = tmp_path / "mnt"
    tape_dir.mkdir()
    mnt.mkdir()

    format_tape(tape_dir, serial="INCIDX", label="incidx")
    mount_tape(tape_dir, mnt)
    try:
        setup_base(mnt)
        full_sync(mnt, "base")
        for number, step in enumerate(steps, 1):
            step(mnt)
            incremental_sync(mnt, f"inc {number}")
    except BaseException:
        umount_tape(mnt)
        raise

    crash_and_recover(tape_dir, mnt, crashed_dir)


def _inc_index_records(tape_dir):
    records = [p for p in tape_dir.glob("1_*_R")
               if b"<ltfsincrementalindex" in p.read_bytes()[:512]]
    return sorted(records, key=lambda p: int(p.name.split("_")[1]))


def _crashed_volume(tmp_path):
    """A crash state whose only incremental index modifies d/c.txt and
    creates d/e.txt."""
    tape_dir = tmp_path / "tape"
    crashed_dir = tmp_path / "tape-crashed"
    mnt = tmp_path / "mnt"
    tape_dir.mkdir()
    mnt.mkdir()

    format_tape(tape_dir, serial="INCBAD", label="incbad")
    mount_tape(tape_dir, mnt)
    try:
        setup_base(mnt)
        full_sync(mnt, "base")
        (mnt / "d" / "c.txt").write_text("c changed\n")
        (mnt / "d" / "e.txt").write_text("e\n")
        incremental_sync(mnt, "inc")
        shutil.copytree(tape_dir, crashed_dir,
                        ignore=shutil.ignore_patterns("attr_*"))
    finally:
        umount_tape(mnt)
    return crashed_dir


@pytest.mark.parametrize("old,new,message", [
    # Not well-formed any more: the parser fails inside the entry.
    (b"<file>", b"<fiel>", "ALB0284E"),
    # Well-formed, but an element that cannot live in <contents>.
    (b"<file>", b"<flie>", "ALX0119E"),
    # The existing d/c.txt under another UID.
    (None, None, "ALX0121E"),
], ids=["not-well-formed", "unexpected-tag", "uid-conflict"])
def test_bad_incremental_index_leaves_volume_untouched(tmp_path, old, new,
                                                       message):
    """Recovery is all or nothing: when an incremental index cannot be
    applied, altfsck writes nothing and the volume keeps its last full
    index."""
    crashed_dir = _crashed_volume(tmp_path)

    (record,) = _inc_index_records(crashed_dir)
    data = record.read_bytes()
    if old is None:
        # <file><name>c.txt</name> ... <fileuid>N</fileuid>: bump N of
        # the first file entry by replacing its single digit.
        start = data.index(b"<name>c.txt</name>")
        uid_at = data.index(b"<fileuid>", start) + len(b"<fileuid>")
        digit = data[uid_at:uid_at + 1]
        assert digit.isdigit() and data[uid_at + 1:uid_at + 2] == b"<"
        patched = data[:uid_at] + (b"9" if digit != b"9" else b"8") \
            + data[uid_at + 1:]
    elif new == b"<flie>":
        patched = data.replace(b"<file>", b"<flie>", 1) \
                      .replace(b"</file>", b"</flie>", 1)
    else:
        patched = data.replace(old, new, 1)
    assert patched != data and len(patched) == len(data)
    record.write_bytes(patched)

    def blocks():
        # The MAM attribute files are no part of the medium contents;
        # altfsck may create them.
        return {p.name: p.read_bytes() for p in crashed_dir.iterdir()
                if not p.name.startswith("attr_")}

    before = blocks()

    check = run_altfsck(tape_dir=crashed_dir)
    check_out = check.stdout + check.stderr
    assert check.returncode not in (0, LTFSCK_CORRECTED), check_out
    assert message in check_out, check_out
    assert "ALB0189I" not in check_out

    assert blocks() == before, \
        "a failed recovery must not write to the volume"


def test_clean_recovery_is_quiet(tmp_path):
    """The recovery does not hand the data blocks between the indexes
    to the XML parser, so it logs no libxml errors and no read failure
    when nothing is wrong. (The backward search for the last full index
    that runs before it still probes every section, ALX0023E / ALB0084W
    from there are expected.)"""
    crashed_dir = _crashed_volume(tmp_path)

    check = run_altfsck(tape_dir=crashed_dir)
    check_out = check.stdout + check.stderr
    assert check.returncode == LTFSCK_CORRECTED, check_out
    for noise in ("parser error", "ALB0180E"):
        assert noise not in check_out, check_out
