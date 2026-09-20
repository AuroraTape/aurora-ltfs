"""Format spec 2.5 behavior of the default build (issues #64, #78).

Format spec 2.5 support is always compiled in (#78); there is no
spec 2.4 build any more. Spec 2.5 changes nothing in the full-index
format; its only on-tape addition is the incremental index. What this
module pins down:

- A freshly formatted volume carries labels and indexes stamped 2.5.0.

- A cleanly-closed volume written by a spec 2.4 implementation mounts
  and its contents are readable. ALX0074W announces that the index is
  upgraded when the volume is modified, and a modification indeed
  writes the next index at 2.5.0: the historical "write the newest
  version you support" policy. Issue #66 (version-preserving index
  writes) is going to replace that policy; the expectation here has to
  change together with it.

- An incremental index left behind by a crashed session is never
  truncated as stray data. Mount refuses the volume (ALB0108E) and
  leaves it untouched; altfsck — with or without --deep-recovery —
  replays the incremental index on top of the last full index
  (ltfs_incindex_recovery) and writes a new full index, after which
  the volume mounts with the changes that were only recorded in the
  incremental index.

The 2.4-stamped volume is produced by re-stamping the label and index
records of a 2.5 volume in place — ``version="2.5.0"`` and
``version="2.4.0"`` have the same byte length, so the file-backend
record sizes stay valid. The crashed volume is a snapshot of the tape directory taken
right after an incremental index was written through the
``ltfs.vendor.Aurora.IncrementalSync`` extended attribute (the file
backend stores block B of partition P as ``<P>_<B>_R``, a filemark as
``<P>_<B>_F`` and EOD as ``<P>_<B>_E``). The MAM attribute files
(``attr_*``) are not part of the snapshot, so mount performs the full
medium consistency check instead of trusting MAM.
"""

import os
import shutil

import pytest

from common.altfs import (
    LTFSCK_CORRECTED,
    format_tape,
    mount_tape,
    mount_tape_foreground,
    run_altfsck,
    try_mount_tape,
    umount_tape,
    umount_tape_foreground,
)
from common.helpers import full_sync, incremental_sync
from common.index import parse_latest_index


_KEEP_CONTENT = "data written before the last full index\n"
_LATE_CONTENT = "data recorded only in the incremental index\n"


def _make_populated_tape(tmp_path_factory, name, serial, label):
    """Format a tape, write one file, and unmount cleanly so both
    partitions carry a matching final index."""
    base = tmp_path_factory.mktemp(name)
    tape_dir = base / "tape"
    mnt = base / "mnt"
    tape_dir.mkdir()
    mnt.mkdir()

    format_tape(tape_dir, serial=serial, label=label)
    mount_tape(tape_dir, mnt)
    try:
        (mnt / "keep.txt").write_text(_KEEP_CONTENT)
    finally:
        umount_tape(mnt)
    return tape_dir, mnt


def _restamp(tape_dir, tag, old="2.5.0", new="2.4.0"):
    """Re-stamp every record whose top-level element is `tag` in place,
    returning how many records were changed. Old and new version must
    have the same byte length so the record size stays consistent."""
    assert len(old) == len(new)
    old_stamp = f'<{tag} version="{old}"'.encode()
    new_stamp = f'<{tag} version="{new}"'.encode()
    changed = 0
    for record in tape_dir.glob("*_R"):
        data = record.read_bytes()
        if old_stamp in data:
            record.write_bytes(data.replace(old_stamp, new_stamp))
            changed += 1
    return changed


def _snapshot_tape(tape_dir, dest):
    """Copy the block files of a mounted tape: the state a crash at this
    very moment would leave behind. The MAM attribute files are left
    out so the next mount cannot take the volume coherency shortcut."""
    shutil.copytree(tape_dir, dest,
                    ignore=shutil.ignore_patterns("attr_*"))
    return dest


def test_formatted_volume_is_stamped_25(tmp_path_factory):
    """mkaltfs writes 2.5.0 labels and altfs writes 2.5.0 indexes."""
    tape_dir, _ = _make_populated_tape(
        tmp_path_factory, "spec25-format", serial="SPEC25", label="spec25")

    labels = [r for r in tape_dir.glob("*_R")
              if b"<ltfslabel " in r.read_bytes()]
    assert len(labels) == 2, "expected one LTFS label per partition"
    for label in labels:
        assert b'<ltfslabel version="2.5.0"' in label.read_bytes()

    for partition in (0, 1):
        root = parse_latest_index(tape_dir, partition=partition)
        assert root.get("version") == "2.5.0"


def test_24_stamped_volume_mounts_and_next_index_is_25(tmp_path_factory):
    """A cleanly-closed volume whose labels and indexes are stamped
    2.4.0 mounts and its contents are readable; ALX0074W announces the
    upgrade. A modification stamps the next index 2.5.0 (see the module
    docstring about issue #66), which parse_latest_index() verifies
    through the independent altfsindextool capture path."""
    tape_dir, mnt = _make_populated_tape(
        tmp_path_factory, "spec24-stamp", serial="SPEC24", label="spec24")

    assert _restamp(tape_dir, "ltfslabel") == 2, "expected one label per partition"
    assert _restamp(tape_dir, "ltfsindex") > 0, "no index records found to re-stamp"
    assert parse_latest_index(tape_dir).get("version") == "2.4.0"

    proc = mount_tape_foreground(tape_dir, mnt)
    try:
        assert (mnt / "keep.txt").read_text() == _KEEP_CONTENT
        (mnt / "new.txt").write_text("written on the 2.4 volume\n")
    finally:
        assert umount_tape_foreground(proc, mnt) == 0

    log = (mnt.parent / "altfs-foreground.log").read_text(errors="replace")
    assert "ALX0074W" in log, "mount must announce the index version upgrade"
    assert "ALX0075W" not in log, \
        "a 2.4 index is not newer than what this software supports"

    assert parse_latest_index(tape_dir).get("version") == "2.5.0"


@pytest.mark.parametrize("altfsck_args", [(), ("--deep-recovery",)],
                         ids=["altfsck", "deep-recovery"])
def test_crashed_incindex_volume_is_recovered_not_truncated(
        tmp_path_factory, altfsck_args):
    """A session crashes after writing an incremental index. Mount must
    refuse the volume without touching it (extra blocks after the last
    index, ALB0108E); altfsck must replay the incremental index instead
    of truncating it as stray data, so the changes it holds survive."""
    base = tmp_path_factory.mktemp("spec25-crash")
    tape_dir = base / "tape"
    mnt = base / "mnt"
    tape_dir.mkdir()
    mnt.mkdir()

    format_tape(tape_dir, serial="SPEC26", label="spec26")
    mount_tape(tape_dir, mnt)
    try:
        (mnt / "keep.txt").write_text(_KEEP_CONTENT)
        (mnt / "gone.txt").write_text("deleted after the full index\n")
        full_sync(mnt, "before the crash")

        (mnt / "late.txt").write_text(_LATE_CONTENT)
        (mnt / "gone.txt").unlink()
        incremental_sync(mnt, "last words")

        crashed_dir = _snapshot_tape(tape_dir, base / "tape-crashed")
    finally:
        umount_tape(mnt)

    before = {p.name: p.read_bytes() for p in crashed_dir.iterdir()}
    assert any(b"<ltfsincrementalindex" in data for data in before.values()), \
        "the snapshot must contain the incremental index"

    denied = try_mount_tape(crashed_dir, mnt)
    assert denied.returncode != 0, "mount must reject the crashed volume"
    assert not os.path.ismount(mnt)
    assert "ALB0108E" in denied.stderr + denied.stdout

    # The rejected mount must not have consumed the volume.
    after = {p.name: p.read_bytes() for p in crashed_dir.iterdir()
             if not p.name.startswith("attr_")}
    assert after == before

    check = run_altfsck(*altfsck_args, tape_dir=crashed_dir)
    check_out = check.stdout + check.stderr
    assert check.returncode == LTFSCK_CORRECTED, check_out
    assert "ALB0183I" in check_out, "the incremental index must be applied"
    assert "ALB0189I" in check_out, "recovery must complete"

    mount_tape(crashed_dir, mnt)
    try:
        assert (mnt / "keep.txt").read_text() == _KEEP_CONTENT
        assert (mnt / "late.txt").read_text() == _LATE_CONTENT
        assert not (mnt / "gone.txt").exists()
    finally:
        umount_tape(mnt)
