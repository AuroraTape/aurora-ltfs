"""Which kind of index a sync writes (issues #134, #158).

The syncs that promise nothing about the state of the files (periodic
sync, sync on close, volume sync) pass ``LTFS_INDEX_AUTO`` and follow
``-o full_index_interval``: negative (the default) writes incremental
indexes only, 0 full indexes only, N writes N incremental indexes and
then a full one. Explicit requests write what they name whatever the
setting: unmount and the sync extended attributes write full indexes,
``ltfs.vendor.Aurora.IncrementalSync`` an incremental one.

The file backend stores block B of partition P as ``<P>_<B>_R``; the
data partition is partition 1.
"""

import shutil
import time

import pytest

from common.altfs import (
    LTFSCK_CORRECTED,
    format_tape,
    mount_tape,
    run_altfsck,
    try_mount_tape,
    umount_tape,
)
from common.helpers import set_xattr
from common.index import parse_latest_index

INC_SYNC = "ltfs.vendor.Aurora.IncrementalSync"


def _dp_records(tape_dir, top_tag):
    stamp = f"<{top_tag} ".encode()
    return sorted((p for p in tape_dir.glob("1_*_R")
                   if stamp in p.read_bytes()[:512]),
                  key=lambda p: int(p.name.split("_")[1]))


def _counts(tape_dir):
    """(full, incremental) indexes on the data partition."""
    return (len(_dp_records(tape_dir, "ltfsindex")),
            len(_dp_records(tape_dir, "ltfsincrementalindex")))


def _wait_for_counts(tape_dir, full, inc, timeout=10.0):
    """Sync on close runs in the FUSE release handler, which the kernel
    calls after close() has already returned to the application."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _counts(tape_dir) == (full, inc):
            break
        time.sleep(0.05)
    return _counts(tape_dir)


def _last_index_kinds(tape_dir, n):
    """Kinds ('full' / 'inc') of the last n indexes on the data partition,
    in tape order."""
    records = [(p, "full") for p in _dp_records(tape_dir, "ltfsindex")] + \
              [(p, "inc") for p in _dp_records(tape_dir, "ltfsincrementalindex")]
    records.sort(key=lambda r: int(r[0].name.split("_")[1]))
    return [kind for _, kind in records[-n:]]


def _wait_for_inc_indexes(tape_dir, count, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if len(_dp_records(tape_dir, "ltfsincrementalindex")) >= count:
            break
        time.sleep(0.05)
    return len(_dp_records(tape_dir, "ltfsincrementalindex"))


def _new_tape(tmp_path, serial):
    tape_dir = tmp_path / "tape"
    mnt = tmp_path / "mnt"
    tape_dir.mkdir()
    mnt.mkdir()
    format_tape(tape_dir, serial=serial, label=serial.lower())
    return tape_dir, mnt


def _write_and_sync(mnt, name, xattr=INC_SYNC):
    """Create a file and ask for an index through `xattr` while the file
    is still open, so the request is ordered before the sync on close."""
    with open(mnt / name, "w") as f:
        f.write(name + "\n")
        f.flush()
        set_xattr(mnt, xattr, "requested")


def test_sync_on_close_writes_incremental_indexes(tmp_path):
    tape_dir, mnt = _new_tape(tmp_path, "POLCLS")

    # -1 is the default; given explicitly to pin the meaning of "negative".
    mount_tape(tape_dir, mnt, sync_type="close",
               extra_opts=("full_index_interval=-1",))
    try:
        full_before = len(_dp_records(tape_dir, "ltfsindex"))

        (mnt / "a.txt").write_text("a\n")
        assert _wait_for_inc_indexes(tape_dir, 1) == 1

        (mnt / "b.txt").write_text("b\n")
        assert _wait_for_inc_indexes(tape_dir, 2) == 2

        # Closing a file that was only read changes nothing: no index,
        # in particular no empty incremental index.
        assert (mnt / "a.txt").read_text() == "a\n"
        time.sleep(0.5)
        assert len(_dp_records(tape_dir, "ltfsincrementalindex")) == 2
        assert len(_dp_records(tape_dir, "ltfsindex")) == full_before
    finally:
        umount_tape(mnt)

    for record in _dp_records(tape_dir, "ltfsincrementalindex"):
        assert b"<contents/>" not in record.read_bytes()

    # Unmount ends with a full index on both partitions.
    assert len(_dp_records(tape_dir, "ltfsindex")) == full_before + 1
    for partition in (0, 1):
        names = {e.findtext("name")
                 for e in parse_latest_index(tape_dir, partition).iter("file")}
        assert names == {"a.txt", "b.txt"}

    # The incremental indexes on the data partition do not get in the
    # way of listing the rollback points.
    listing = run_altfsck("-l", tape_dir=tape_dir)
    assert listing.returncode == 0, listing.stdout + listing.stderr


def test_crash_after_sync_on_close_recovers_closed_files(tmp_path):
    tape_dir, mnt = _new_tape(tmp_path, "POLCRS")
    crashed_dir = tmp_path / "tape-crashed"

    mount_tape(tape_dir, mnt, sync_type="close")
    try:
        (mnt / "d").mkdir()
        (mnt / "d" / "closed.txt").write_text("closed before the crash\n")
        assert _wait_for_inc_indexes(tape_dir, 1) >= 1
        shutil.copytree(tape_dir, crashed_dir,
                        ignore=shutil.ignore_patterns("attr_*"))
    finally:
        umount_tape(mnt)

    check = run_altfsck(tape_dir=crashed_dir)
    assert check.returncode == LTFSCK_CORRECTED, check.stdout + check.stderr

    mount_tape(crashed_dir, mnt)
    try:
        assert (mnt / "d" / "closed.txt").read_text() == \
            "closed before the crash\n"
    finally:
        umount_tape(mnt)


def test_sync_extended_attributes_write_what_they_name(tmp_path):
    tape_dir, mnt = _new_tape(tmp_path, "POLXAT")

    mount_tape(tape_dir, mnt)
    try:
        full, inc = _counts(tape_dir)

        (mnt / "one.txt").write_text("1\n")
        set_xattr(mnt, "ltfs.sync", "standard sync")
        assert _counts(tape_dir) == (full + 1, inc)

        (mnt / "two.txt").write_text("2\n")
        set_xattr(mnt, INC_SYNC, "inc")
        assert _counts(tape_dir) == (full + 1, inc + 1)

        (mnt / "three.txt").write_text("3\n")
        set_xattr(mnt, "ltfs.vendor.Aurora.FullSync", "full")
        assert _counts(tape_dir) == (full + 2, inc + 1)
    finally:
        umount_tape(mnt)


def test_interval_zero_makes_the_automatic_syncs_full(tmp_path):
    tape_dir, mnt = _new_tape(tmp_path, "POLZER")

    mount_tape(tape_dir, mnt, sync_type="close",
               extra_opts=("full_index_interval=0",))
    try:
        full, inc = _counts(tape_dir)

        (mnt / "a.txt").write_text("a\n")
        assert _wait_for_counts(tape_dir, full + 1, inc) == (full + 1, inc)
        (mnt / "b.txt").write_text("b\n")
        assert _wait_for_counts(tape_dir, full + 2, inc) == (full + 2, inc)

        # 0 disables automatic incremental indexes, it does not forbid
        # them: an explicit request still writes one, and the sync on
        # close that follows closes the chain with a full index although
        # nothing changed since the incremental one.
        _write_and_sync(mnt, "c.txt")
        assert _wait_for_counts(tape_dir, full + 3, inc + 1) == \
            (full + 3, inc + 1)
        assert _last_index_kinds(tape_dir, 2) == ["inc", "full"]
    finally:
        umount_tape(mnt)

    # Nothing was pending at unmount: the volume ends as it was left.
    assert _counts(tape_dir) == (full + 3, inc + 1)
    names = {e.findtext("name")
             for e in parse_latest_index(tape_dir, 0).iter("file")}
    assert names == {"a.txt", "b.txt", "c.txt"}


def test_interval_n_writes_n_incremental_indexes_then_a_full_one(tmp_path):
    tape_dir, mnt = _new_tape(tmp_path, "POLINT")

    mount_tape(tape_dir, mnt, sync_type="close",
               extra_opts=("full_index_interval=2",))
    try:
        full, inc = _counts(tape_dir)

        def expect(name, full_delta, inc_delta):
            assert _wait_for_counts(tape_dir, full + full_delta,
                                    inc + inc_delta) == \
                (full + full_delta, inc + inc_delta), name

        # The index read at mount is the last full index: 2 incremental
        # indexes, then a full one, then the count starts again.
        (mnt / "a.txt").write_text("a\n")
        expect("a", 0, 1)
        (mnt / "b.txt").write_text("b\n")
        expect("b", 0, 2)
        (mnt / "c.txt").write_text("c\n")
        expect("c", 1, 2)
        (mnt / "d.txt").write_text("d\n")
        expect("d", 1, 3)
        (mnt / "e.txt").write_text("e\n")
        expect("e", 1, 4)

        # The full index is due. An explicit incremental request is
        # honoured and does not delay it: the sync on close that follows
        # writes the full index. (The sync on close may already have run
        # when the request returns, so the order is read from the tape.)
        _write_and_sync(mnt, "f.txt")
        expect("f", 2, 5)
        assert _last_index_kinds(tape_dir, 2) == ["inc", "full"]

        # An explicit incremental index counts against the interval:
        # explicit + automatic = 2, so the third change writes a full index.
        _write_and_sync(mnt, "g.txt")
        expect("g", 2, 7)
        assert _last_index_kinds(tape_dir, 3) == ["full", "inc", "inc"]
        (mnt / "h.txt").write_text("h\n")
        expect("h", 3, 7)

        # An explicit full index starts the count again: the sync on
        # close after it is the first of the next two incremental ones.
        (mnt / "i.txt").write_text("i\n")
        expect("i", 3, 8)
        _write_and_sync(mnt, "j.txt", "ltfs.vendor.Aurora.FullSync")
        expect("j", 4, 9)
        assert _last_index_kinds(tape_dir, 2) == ["full", "inc"]
        (mnt / "k.txt").write_text("k\n")
        expect("k", 4, 10)
        (mnt / "l.txt").write_text("l\n")
        expect("l", 5, 10)
    finally:
        umount_tape(mnt)

    names = {e.findtext("name")
             for e in parse_latest_index(tape_dir, 0).iter("file")}
    assert names == {f"{c}.txt" for c in "abcdefghijkl"}


@pytest.mark.parametrize("value", ["", "x", "1.5", "--1", "+1", " 1", "1 "])
def test_invalid_full_index_interval_is_rejected(tmp_path, value):
    tape_dir, mnt = _new_tape(tmp_path, "POLBAD")

    result = try_mount_tape(tape_dir, mnt,
                            extra_opts=(f"full_index_interval={value}",))
    assert result.returncode != 0
    assert "AFS0148E" in result.stdout + result.stderr
