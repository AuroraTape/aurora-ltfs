"""Format spec 2.5 boundary behavior of the default (spec 2.4) build (issue #64).

Spec 2.5 changes nothing in the full-index format; its only on-tape
addition is the incremental index. The boundary the default build has
to respect is therefore (see the design notes on issue #64):

- A cleanly-closed volume whose latest index is stamped 2.5.0 is fully
  understandable content: it must mount, with warning ALX0075W telling
  the user the version is newer and that a modification downgrades the
  stamp to 2.4.0 (xml_reader_libltfs.c accepts the whole 2.x range).

- An incremental index left behind by a crashed spec 2.5 session is a
  construct this build cannot parse. Recovery must refuse to touch the
  volume (ALB0283E, altfsck exits uncorrected): truncating the inc
  index as stray data would destroy changes that a spec 2.5 capable
  build can still recover (ltfs_incindex_recovery).

The 2.5-stamped volume is produced by re-stamping the index records of
a 2.4 volume in place — ``version="2.4.0"`` and ``version="2.5.0"``
have the same byte length, so the file-backend record sizes stay
valid. The crashed volume is produced by appending a hand-written
incremental index record after the data partition's last full index
(the file backend stores block B of partition P as ``<P>_<B>_R``, a
filemark as ``<P>_<B>_F`` and EOD as ``<P>_<B>_E``). The MAM volume
coherency attributes (``attr_<P>_80c``) are dropped so mount performs
the full medium consistency check instead of trusting MAM.
"""

import os

from common.altfs import (
    LTFSCK_UNCORRECTED,
    format_tape,
    mount_tape,
    mount_tape_foreground,
    run_altfsck,
    try_mount_tape,
    umount_tape,
    umount_tape_foreground,
)
from common.index import parse_latest_index


_KEEP_CONTENT = "data written by the spec 2.4 build\n"

# A plausible minimal incremental index: the recovery guard and the
# index seek only look at the top-level tag, but keep the shape close
# to what a spec 2.5 build writes.
_INC_INDEX_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<ltfsincrementalindex version="2.5.0">
<creator>Aurora LTFS - test fixture</creator>
<generationnumber>3</generationnumber>
<highestfileuid>4</highestfileuid>
<directory><name></name><contents>
<file operation="create"><name>late.txt</name><length>5</length><fileuid>4</fileuid></file>
</contents></directory>
</ltfsincrementalindex>
"""


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


def _restamp_indexes(tape_dir, old=b'ltfsindex version="2.4.0"',
                     new=b'ltfsindex version="2.5.0"'):
    """Re-stamp every index record in place, returning how many records
    were changed. Old and new stamp must have the same byte length so
    the record size stays consistent."""
    assert len(old) == len(new)
    changed = 0
    for record in tape_dir.glob("*_R"):
        data = record.read_bytes()
        if old in data:
            record.write_bytes(data.replace(old, new))
            changed += 1
    return changed


def _fake_crashed_incindex(tape_dir):
    """Turn a cleanly-unmounted tape into the state left by a spec 2.5
    session that crashed right after writing an incremental index on
    the data partition: (last full index | FM | inc index | FM | EOD).
    Returns the paths of the fabricated block files."""
    (eod,) = tape_dir.glob("1_*_E")
    block = int(eod.name.split("_")[1])
    eod.unlink()

    inc_record = tape_dir / f"1_{block}_R"
    inc_record.write_bytes(_INC_INDEX_XML)
    fm = tape_dir / f"1_{block + 1}_F"
    fm.touch()
    new_eod = tape_dir / f"1_{block + 2}_E"
    new_eod.touch()

    # Invalidate the MAM shortcut so mount runs the full medium
    # consistency check that inspects the blocks after the index.
    coherency = list(tape_dir.glob("attr_*_80c"))
    assert len(coherency) == 2, "expected one VCI attribute per partition"
    for attr in coherency:
        attr.unlink()

    return inc_record, fm, new_eod


def test_25_stamped_volume_mounts_with_version_warning(tmp_path_factory):
    """A cleanly-closed volume whose indexes are stamped 2.5.0 mounts
    on the default build and its contents are readable; ALX0075W tells
    the user the found version is newer than the supported 2.4.0.
    A modification then re-stamps the index 2.4.0 — the downgrade the
    warning announces — which parse_latest_index() verifies through
    the independent altfsindextool capture path."""
    tape_dir, mnt = _make_populated_tape(
        tmp_path_factory, "spec25-stamp", serial="SPEC25", label="spec25")

    assert _restamp_indexes(tape_dir) > 0, "no index records found to re-stamp"

    proc = mount_tape_foreground(tape_dir, mnt)
    try:
        assert (mnt / "keep.txt").read_text() == _KEEP_CONTENT
        (mnt / "new.txt").write_text("written on the 2.5 volume\n")
    finally:
        assert umount_tape_foreground(proc, mnt) == 0

    log = (mnt.parent / "altfs-foreground.log").read_text(errors="replace")
    assert "ALX0075W" in log, "mount must warn about the newer index version"

    root = parse_latest_index(tape_dir)
    assert root.get("version") == "2.4.0", \
        "index written by the 2.4 build must be stamped 2.4.0"


def test_crashed_incindex_volume_is_refused_untouched(tmp_path_factory):
    """A volume that a spec 2.5 session left with a trailing incremental
    index is beyond this build: mount is rejected (extra blocks after
    the last index, ALB0108E), and altfsck — including --deep-recovery —
    refuses with ALB0283E instead of "recovering" by truncating the inc
    index, which would destroy the changes it holds. The volume must be
    byte-for-byte untouched afterwards so a spec 2.5 capable build can
    still recover it."""
    tape_dir, mnt = _make_populated_tape(
        tmp_path_factory, "spec25-crash", serial="SPEC26", label="spec26")

    inc_record, fm, eod = _fake_crashed_incindex(tape_dir)

    denied = try_mount_tape(tape_dir, mnt)
    assert denied.returncode != 0, "mount must reject the crashed volume"
    assert not os.path.ismount(mnt)
    assert "ALB0108E" in denied.stderr + denied.stdout

    check = run_altfsck(tape_dir=tape_dir)
    check_out = check.stdout + check.stderr
    assert check.returncode == LTFSCK_UNCORRECTED, check_out
    assert "ALB0283E" in check_out, \
        "altfsck must name the incremental index as the reason"

    deep = run_altfsck("--deep-recovery", tape_dir=tape_dir)
    deep_out = deep.stdout + deep.stderr
    assert deep.returncode == LTFSCK_UNCORRECTED, deep_out
    assert "ALB0283E" in deep_out

    # The failed recoveries must not have consumed the volume: the
    # incremental index and its trailing filemark/EOD are still there.
    assert inc_record.read_bytes() == _INC_INDEX_XML
    assert fm.exists() and eod.exists()

    still_denied = try_mount_tape(tape_dir, mnt)
    assert still_denied.returncode != 0
    assert not os.path.ismount(mnt)
