"""Tape write-error scenarios on the filedebug backend (issue #41).

The generic/file backend can inject tape-level write errors without
real hardware:

- ``emulate_readonly`` in ``<tape_dir>/filedebug_tc_conf.xml`` (the
  file is auto-written with defaults when the cartridge is first
  loaded) emulates a physically write-protected cartridge.

- The vendor xattr ``ltfs.vendor.Aurora.forceErrorWrite = N`` arms a
  pseudo WRITE PERM: tape writes 1..N after arming are silently
  dropped (emulating a drive buffer that never reaches tape) and
  write N+1 fails with EDEV_WRITE_PERM. The sign of N selects the
  blast radius (filedebug's ``clear_by_pc`` flag):

  * negative N — the error state clears on a partition change, so
    only the data partition is hit and LTFS can still save the
    recovery index on the index partition (single WRITE PERM, MAM
    volume-lock state PWE_MAM_DP).
  * positive N — the error persists across the partition change, so
    the recovery index write fails too (DOUBLE WRITE PERM,
    PWE_MAM_BOTH).

In both cases LTFS records the PWE state in the cartridge MAM and
later mounts come up read-only with the newest surviving index.
"""

import errno
import os

import pytest

from common.altfs import (
    LTFSCK_CORRECTED,
    format_tape,
    mount_tape,
    run_altfsck,
    umount_tape,
)
from common.helpers import set_xattr


_CHUNK = 512 * 1024
# Enough chunks to guarantee tape writes happen while we are still
# writing: the unified scheduler flushes in 512KB blocks.
_CHUNKS = 40

_FORCE_ERROR_WRITE = "ltfs.vendor.Aurora.forceErrorWrite"


def _make_mounted_tape(tmp_path_factory, name, serial, label):
    base = tmp_path_factory.mktemp(name)
    tape_dir = base / "tape"
    mnt = base / "mnt"
    tape_dir.mkdir()
    mnt.mkdir()
    format_tape(tape_dir, serial=serial, label=label)
    mount_tape(tape_dir, mnt)
    return tape_dir, mnt


def _write_until_error(mnt, name):
    """Write data until the injected WRITE PERM surfaces.

    The error may surface at write(2) (scheduler already stuck), at
    flush/close (final push into FUSE) or at the explicit index sync.
    The errno depends on timing: the write call whose flush hits the
    tape error gets EIO, but once the volume has been flagged
    write-error later writes fail with EROFS — whichever our writing
    loop meets first. Returns the OSError that surfaced, or None if
    everything unexpectedly succeeded.
    """
    err = None
    try:
        # Buffered I/O so short writes are absorbed internally; the
        # per-chunk flush pushes each chunk into FUSE promptly.
        with open(mnt / name, "wb") as f:
            for _ in range(_CHUNKS):
                f.write(b"\xb5" * _CHUNK)
                f.flush()
    except OSError as e:
        err = e
    if err is None:
        try:
            set_xattr(mnt, "ltfs.vendor.Aurora.FullSync", "flush after injection")
        except OSError as e:
            err = e
    return err


def test_write_protected_tape_rejects_writes_and_stays_consistent(tmp_path_factory):
    """A write-protected cartridge (emulate_readonly) must mount
    read-only: every mutation fails with EROFS and the volume is
    still consistent afterwards."""
    base = tmp_path_factory.mktemp("write-protect")
    tape_dir = base / "tape"
    mnt = base / "mnt"
    tape_dir.mkdir()
    mnt.mkdir()
    format_tape(tape_dir, serial="WPROT0", label="wprot")

    # mkaltfs leaves a default config behind; flip the cartridge to
    # write-protected before the next load.
    conf = tape_dir / "filedebug_tc_conf.xml"
    text = conf.read_text()
    assert "<emulate_readonly>false</emulate_readonly>" in text
    conf.write_text(text.replace(
        "<emulate_readonly>false</emulate_readonly>",
        "<emulate_readonly>true</emulate_readonly>",
    ))

    mount_tape(tape_dir, mnt)
    try:
        with pytest.raises(OSError) as exc:
            (mnt / "denied.txt").write_text("must not land on tape")
        assert exc.value.errno == errno.EROFS

        with pytest.raises(OSError) as exc:
            os.mkdir(mnt / "denied-dir")
        assert exc.value.errno == errno.EROFS

        # Reading still works.
        assert os.listdir(mnt) == []
    finally:
        umount_tape(mnt)

    check = run_altfsck(tape_dir=tape_dir)
    assert check.returncode == LTFSCK_CORRECTED, check.stderr
    # "volume is consistent", not the bare word: "inconsistent"
    # would match "consistent" too.
    assert "volume is consistent" in (check.stdout + check.stderr).lower()


def test_single_write_perm_preserves_synced_data(tmp_path_factory):
    """WRITE PERM on the data partition: the error must surface as
    EIO, the recovery index must land on the index partition, and a
    later mount must come up read-only with the previously synced
    file intact."""
    tape_dir, mnt = _make_mounted_tape(
        tmp_path_factory, "write-perm", serial="WPERM1", label="wperm1")
    try:
        (mnt / "survivor.txt").write_text("synced before the write error\n")
        set_xattr(mnt, "ltfs.vendor.Aurora.FullSync", "before injection")

        # Negative count: cleared on partition change (single perm).
        set_xattr(mnt, _FORCE_ERROR_WRITE, "-1")

        err = _write_until_error(mnt, "victim.bin")
        assert err is not None, "injected WRITE PERM never surfaced"
        assert err.errno in (errno.EIO, errno.EROFS)
    finally:
        umount_tape(mnt)
    assert not os.path.ismount(mnt)

    # The write-perm handling saved the index on the IP, tagged with
    # the "Write perm" commit reason.
    listing = run_altfsck("-l", tape_dir=tape_dir)
    assert listing.returncode == 0, listing.stderr
    assert "Write perm" in (listing.stdout + listing.stderr)

    # Remount: LTFS detects the PWE MAM state and mounts read-only.
    mount_tape(tape_dir, mnt)
    try:
        assert (mnt / "survivor.txt").read_text() == \
            "synced before the write error\n"
        with pytest.raises(OSError) as exc:
            (mnt / "more.txt").write_text("volume must be read-only")
        assert exc.value.errno == errno.EROFS
    finally:
        umount_tape(mnt)


def test_double_write_perm_no_crash_and_still_mountable(tmp_path_factory):
    """DOUBLE WRITE PERM: the recovery index write on the index
    partition fails as well. The daemon must survive, and the volume
    must still mount read-only from the newest index that made it to
    tape before the injection."""
    tape_dir, mnt = _make_mounted_tape(
        tmp_path_factory, "double-write-perm", serial="WPERM2", label="wperm2")
    try:
        (mnt / "survivor.txt").write_text("synced before the write error\n")
        set_xattr(mnt, "ltfs.vendor.Aurora.FullSync", "before injection")

        # Positive count: persists across partition changes, so the
        # recovery index write on the IP gets the same WRITE PERM.
        set_xattr(mnt, _FORCE_ERROR_WRITE, "1")

        err = _write_until_error(mnt, "victim.bin")
        assert err is not None, "injected WRITE PERM never surfaced"
        assert err.errno in (errno.EIO, errno.EROFS)
    finally:
        # umount_tape waits for the daemon to exit; a crash or hang
        # here would leave the mount point busy and fail the next
        # assertion.
        umount_tape(mnt)
    assert not os.path.ismount(mnt)

    mount_tape(tape_dir, mnt)
    try:
        assert (mnt / "survivor.txt").read_text() == \
            "synced before the write error\n"
        with pytest.raises(OSError) as exc:
            (mnt / "more.txt").write_text("volume must be read-only")
        assert exc.value.errno == errno.EROFS
    finally:
        umount_tape(mnt)

    check = run_altfsck(tape_dir=tape_dir)
    assert check.returncode == LTFSCK_CORRECTED, check.stderr
    assert "volume is consistent" in (check.stdout + check.stderr).lower()
