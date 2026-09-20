"""Which kind of index a sync writes (issue #134).

Syncs that promise nothing about the state of the files write
incremental indexes (``LTFS_INDEX_AUTO``: periodic sync, sync on close,
volume sync). Explicit requests write full indexes: unmount and the sync
extended attributes, except ``ltfs.vendor.Aurora.IncrementalSync``.

The file backend stores block B of partition P as ``<P>_<B>_R``; the
data partition is partition 1.
"""

import shutil
import time

from common.altfs import (
    LTFSCK_CORRECTED,
    format_tape,
    mount_tape,
    run_altfsck,
    umount_tape,
)
from common.helpers import set_xattr
from common.index import parse_latest_index


def _dp_records(tape_dir, top_tag):
    stamp = f"<{top_tag} ".encode()
    return sorted((p for p in tape_dir.glob("1_*_R")
                   if stamp in p.read_bytes()[:512]),
                  key=lambda p: int(p.name.split("_")[1]))


def _wait_for_inc_indexes(tape_dir, count, timeout=10.0):
    """Sync on close runs in the FUSE release handler, which the kernel
    calls after close() has already returned to the application."""
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


def test_sync_on_close_writes_incremental_indexes(tmp_path):
    tape_dir, mnt = _new_tape(tmp_path, "POLCLS")

    mount_tape(tape_dir, mnt, sync_type="close")
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
        def counts():
            return (len(_dp_records(tape_dir, "ltfsindex")),
                    len(_dp_records(tape_dir, "ltfsincrementalindex")))

        full, inc = counts()

        (mnt / "one.txt").write_text("1\n")
        set_xattr(mnt, "ltfs.sync", "standard sync")
        assert counts() == (full + 1, inc)

        (mnt / "two.txt").write_text("2\n")
        set_xattr(mnt, "ltfs.vendor.Aurora.IncrementalSync", "inc")
        assert counts() == (full + 1, inc + 1)

        (mnt / "three.txt").write_text("3\n")
        set_xattr(mnt, "ltfs.vendor.Aurora.FullSync", "full")
        assert counts() == (full + 2, inc + 1)
    finally:
        umount_tape(mnt)
