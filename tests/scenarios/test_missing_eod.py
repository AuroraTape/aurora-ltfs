"""Missing-EOD scenarios on the filedebug backend (issue #41).

The file backend stores one file per tape block; the EOD marker of
partition P at block B is the empty file ``<P>_<B>_E``. Deleting
those files reproduces a cartridge whose EOD is unreadable — the
state LTFS reports as LTFS_EOD_MISSING_MEDIUM (one partition) or
LTFS_BOTH_EOD_MISSING (both partitions).

Expected behavior, verified against src/libltfs/ltfs.c
(ltfs_check_eod_status / ltfs_recover_eod):

- mounting is rejected in both cases, pointing the user at
  ``altfsck --deep-recovery``;
- deep recovery reconstructs the missing EOD when the other
  partition still has a good EOD, using it as reference;
- with BOTH EODs missing there is no reference left and
  ltfs_recover_eod() refuses (-LTFS_UNSUPPORTED) — but the
  rollback-point listing still works, so data can be located for
  salvage;
- ``--salvage-rollback-points`` is WORM-only by design and is
  rejected on a normal cartridge.
"""

import os

from common.altfs import (
    format_tape,
    mount_tape,
    run_altfsck,
    try_mount_tape,
    umount_tape,
)
from common.helpers import set_xattr


LTFSCK_CORRECTED = 0x01
LTFSCK_UNCORRECTED = 0x04
LTFSCK_USAGE_SYNTAX_ERROR = 0x10

_KEEP_CONTENT = "data written before the EOD was lost\n"


def _make_populated_tape(tmp_path_factory, name, serial, label):
    """Format a tape, write one file plus a tagged index generation,
    and unmount so both partitions carry data and an EOD marker."""
    base = tmp_path_factory.mktemp(name)
    tape_dir = base / "tape"
    mnt = base / "mnt"
    tape_dir.mkdir()
    mnt.mkdir()

    format_tape(tape_dir, serial=serial, label=label)
    mount_tape(tape_dir, mnt)
    try:
        (mnt / "keep.txt").write_text(_KEEP_CONTENT)
        set_xattr(mnt, "ltfs.sync", "generation before damage")
    finally:
        umount_tape(mnt)
    return tape_dir, mnt


def _drop_eod(tape_dir, partition):
    """Remove partition's EOD marker file, returning how many were
    deleted (a healthy partition has exactly one)."""
    markers = list(tape_dir.glob(f"{partition}_*_E"))
    for marker in markers:
        marker.unlink()
    return len(markers)


def test_dp_eod_missing_recovered_by_deep_recovery(tmp_path_factory):
    """EOD lost on the data partition only: mount is rejected,
    altfsck --deep-recovery rebuilds the EOD from the intact index
    partition, and the volume mounts again with its contents."""
    tape_dir, mnt = _make_populated_tape(
        tmp_path_factory, "eod-dp", serial="NOEOD1", label="noeod1")

    assert _drop_eod(tape_dir, partition=1) == 1

    denied = try_mount_tape(tape_dir, mnt)
    assert denied.returncode != 0, "mount must reject a no-EOD cartridge"
    assert not os.path.ismount(mnt)

    deep = run_altfsck("--deep-recovery", tape_dir=tape_dir)
    assert deep.returncode == LTFSCK_CORRECTED, deep.stderr
    assert list(tape_dir.glob("1_*_E")), "deep recovery must rewrite the DP EOD"

    mount_tape(tape_dir, mnt)
    try:
        assert (mnt / "keep.txt").read_text() == _KEEP_CONTENT
    finally:
        umount_tape(mnt)


def test_both_eod_missing_listing_works_but_unrecoverable(tmp_path_factory):
    """Both EODs lost (LTFS_BOTH_EOD_MISSING): mount and the default
    check are rejected. The rollback-point listing must still work so
    the indexes remain reachable, while deep recovery reports the
    volume unrecoverable — with no good EOD left there is no
    reference to rebuild from (ltfs_recover_eod returns
    -LTFS_UNSUPPORTED)."""
    tape_dir, mnt = _make_populated_tape(
        tmp_path_factory, "eod-both", serial="NOEOD2", label="noeod2")

    assert _drop_eod(tape_dir, partition=0) == 1
    assert _drop_eod(tape_dir, partition=1) == 1

    denied = try_mount_tape(tape_dir, mnt)
    assert denied.returncode != 0, "mount must reject a no-EOD cartridge"
    assert not os.path.ismount(mnt)

    # Default check cannot correct this volume.
    check = run_altfsck(tape_dir=tape_dir)
    assert check.returncode == LTFSCK_UNCORRECTED, check.stdout + check.stderr

    # The rollback-point listing keeps working on the no-EOD
    # cartridge: every index generation is still reachable.
    listing = run_altfsck("-l", tape_dir=tape_dir)
    assert listing.returncode == 0, listing.stderr
    listing_out = listing.stdout + listing.stderr
    assert "Initial Index" in listing_out
    assert "generation before damage" in listing_out

    # Deep recovery must fail cleanly (no reference EOD to copy
    # from), not corrupt the volume further: the listing still works
    # afterwards.
    deep = run_altfsck("--deep-recovery", tape_dir=tape_dir)
    assert deep.returncode == LTFSCK_UNCORRECTED, deep.stdout + deep.stderr

    relisting = run_altfsck("-l", tape_dir=tape_dir)
    assert relisting.returncode == 0, relisting.stderr
    assert "Initial Index" in relisting.stdout + relisting.stderr


def test_salvage_rollback_points_rejected_on_non_worm(tmp_path_factory):
    """--salvage-rollback-points is restricted to WORM cartridges;
    on a normal no-EOD cartridge it must be rejected as a usage
    error (the normal -l listing is the supported path there)."""
    tape_dir, _mnt = _make_populated_tape(
        tmp_path_factory, "eod-salvage", serial="NOEOD3", label="noeod3")

    _drop_eod(tape_dir, partition=0)
    _drop_eod(tape_dir, partition=1)

    salvage = run_altfsck("--salvage-rollback-points", tape_dir=tape_dir)
    assert salvage.returncode == LTFSCK_USAGE_SYNTAX_ERROR, \
        salvage.stdout + salvage.stderr
