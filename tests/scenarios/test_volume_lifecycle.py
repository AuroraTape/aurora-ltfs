"""Volume lifecycle & index management on the file backend (issue #42).

Covers the high-risk index-management paths the harness did not
exercise before:

- **Rollback mount**: ``altfs -o rollback_mount=<gen|index_file>``
  presents an older index generation read-only, without touching
  the tape. The generation-number form regressed once (altfs
  routed every rollback string through the index-file loader), so
  both forms are pinned here.

- **Unformat** (``mkaltfs --wipe``): destroys the LTFS structure;
  the tape must stop being mountable or checkable, and a fresh
  format must bring it back empty.

- **Out-of-band state change** (``altfsck --rollback``): the tape
  content is rewritten while no daemon is running; the next mount
  has to pick up the rolled-back state, not any cached view.
  (True in-session revalidation — ltfs_revalidate() after a bus
  reset or medium change — needs a device error the file backend
  cannot inject, so mount-time re-reading is what is verifiable
  here.)

The generation history used throughout is built the same way:
gen 1 is the format-time index, "point-one" tags the generation
holding only first.txt, "point-two" the one holding both files.
"""

import errno
import os
import re
import subprocess
import xml.etree.ElementTree as ET

import pytest

from common.altfs import (
    LTFSCK_CORRECTED,
    LTFSCK_NO_ERRORS,
    LTFSCK_OPERATIONAL_ERROR,
    LTFSCK_UNCORRECTED,
    MKLTFS_UNFORMATTED,
    format_tape,
    mount_tape,
    run_altfsck,
    try_mount_tape,
    umount_tape,
)
from common.helpers import list_records, set_xattr


_FIRST_CONTENT = "written before point-one\n"
_SECOND_CONTENT = "written before point-two\n"

_RUN_TIMEOUT = 30

# `altfsck -l` prints, per index: a "<gen>: <local date> ..." header,
# a "(<UTC date> ...)" line, then the commit message line.
_LISTING_GEN_RE = re.compile(r"^\s*(\d+): \d{4}-\d{2}-\d{2} ")


def _make_history_tape(tmp_path_factory, name, serial, label):
    """Format a tape and leave it with three index generations:
    1 (format), "point-one" (first.txt only), "point-two" (both
    files)."""
    base = tmp_path_factory.mktemp(name)
    tape_dir = base / "tape"
    mnt = base / "mnt"
    tape_dir.mkdir()
    mnt.mkdir()

    format_tape(tape_dir, serial=serial, label=label)
    mount_tape(tape_dir, mnt)
    try:
        (mnt / "first.txt").write_text(_FIRST_CONTENT)
        set_xattr(mnt, "ltfs.sync", "point-one")
        (mnt / "second.txt").write_text(_SECOND_CONTENT)
        set_xattr(mnt, "ltfs.sync", "point-two")
    finally:
        umount_tape(mnt)
    return tape_dir, mnt


def _generation_of(tape_dir, tag):
    """Map a commit-message tag to its generation number via the
    rollback-point listing."""
    listing = run_altfsck("-l", tape_dir=tape_dir)
    assert listing.returncode == LTFSCK_NO_ERRORS, listing.stderr
    lines = (listing.stdout + listing.stderr).splitlines()
    gen = None
    for line in lines:
        m = _LISTING_GEN_RE.match(line)
        if m:
            gen = int(m.group(1))
        elif gen is not None and line.strip() == tag:
            return gen
    raise AssertionError(f"tag {tag!r} not found in rollback-point listing")


def _capture_index_file(tape_dir, dest, gen):
    """Extract every DP index with altfsindextool and return the
    path of the one whose <generationnumber> is `gen`."""
    subprocess.run(
        ["altfsindextool", "-e", "file", "-d", str(tape_dir),
         "--partition=1", f"--output-dir={dest}", "--quiet"],
        check=True,
        capture_output=True,
        timeout=_RUN_TIMEOUT,
    )
    for path in dest.glob("ltfs-index-1-*.xml"):
        root = ET.parse(path).getroot()
        if int(root.findtext("generationnumber")) == gen:
            return path
    raise AssertionError(f"no captured index has generation {gen}")


def _assert_point_one_view_read_only(mnt):
    """The mounted tree must be exactly the point-one state and must
    reject every mutation with EROFS."""
    assert sorted(os.listdir(mnt)) == ["first.txt"]
    assert (mnt / "first.txt").read_text() == _FIRST_CONTENT

    with pytest.raises(OSError) as exc:
        (mnt / "new.txt").write_text("rollback mounts must be read-only")
    assert exc.value.errno == errno.EROFS

    with pytest.raises(OSError) as exc:
        os.unlink(mnt / "first.txt")
    assert exc.value.errno == errno.EROFS


def _assert_latest_view(mnt):
    assert sorted(os.listdir(mnt)) == ["first.txt", "second.txt"]
    assert (mnt / "first.txt").read_text() == _FIRST_CONTENT
    assert (mnt / "second.txt").read_text() == _SECOND_CONTENT


def test_rollback_mount_by_generation(tmp_path_factory):
    """`-o rollback_mount=<gen>` must present exactly that
    generation's tree, read-only, and must not disturb the volume:
    a plain mount afterwards sees the latest state again.

    This is the regression test for the dispatch bug where a
    numeric rollback target was fed to the index-file loader and
    the mount failed."""
    tape_dir, mnt = _make_history_tape(
        tmp_path_factory, "rollback-gen", serial="ROLLBG", label="rollbg")
    gen = _generation_of(tape_dir, "point-one")

    mount_tape(tape_dir, mnt, extra_opts=[f"rollback_mount={gen}"])
    try:
        _assert_point_one_view_read_only(mnt)
    finally:
        umount_tape(mnt)

    # The rollback mount is a view, not a state change.
    mount_tape(tape_dir, mnt)
    try:
        _assert_latest_view(mnt)
    finally:
        umount_tape(mnt)


def test_rollback_mount_by_index_file(tmp_path_factory):
    """`-o rollback_mount=<captured index file>` (with a device
    attached) must mount the generation stored in that file,
    read-only."""
    tape_dir, mnt = _make_history_tape(
        tmp_path_factory, "rollback-file", serial="ROLLBF", label="rollbf")
    gen = _generation_of(tape_dir, "point-one")

    dest = tape_dir.parent / "captured"
    dest.mkdir()
    index_file = _capture_index_file(tape_dir, dest, gen)

    mount_tape(tape_dir, mnt, extra_opts=[f"rollback_mount={index_file}"])
    try:
        _assert_point_one_view_read_only(mnt)
    finally:
        umount_tape(mnt)


def test_rollback_mount_foreign_index_file_rejected(tmp_path_factory):
    """An index file captured from a *different* volume must be
    rejected at mount time: ltfs_mount_indexfile() compares the
    index's volume UUID against the label on the loaded tape
    (ALB0280E) instead of presenting another volume's tree. The
    volume itself must stay intact and mountable."""
    tape_dir, mnt = _make_history_tape(
        tmp_path_factory, "rollback-foreign", serial="ROLLBU", label="rollbu")

    foreign_base = tmp_path_factory.mktemp("rollback-foreign-donor")
    foreign_tape = foreign_base / "tape"
    foreign_tape.mkdir()
    format_tape(foreign_tape, serial="FOREGN", label="foreign")
    dest = foreign_base / "captured"
    dest.mkdir()
    # Generation 1 is the format-time index; it is the only one on
    # the donor tape.
    foreign_index = _capture_index_file(foreign_tape, dest, 1)

    denied = try_mount_tape(
        tape_dir, mnt, extra_opts=[f"rollback_mount={foreign_index}"])
    assert denied.returncode != 0, \
        "mount must reject an index file from a different volume"
    assert not os.path.ismount(mnt)
    assert "ALB0280E" in denied.stdout + denied.stderr, \
        "rejection must be the UUID-mismatch diagnostic"

    # The failed rollback mount must not have damaged the volume.
    mount_tape(tape_dir, mnt)
    try:
        _assert_latest_view(mnt)
    finally:
        umount_tape(mnt)


def test_rollback_mount_nonexistent_generation_rejected(tmp_path_factory):
    """A rollback target that never existed on the tape must fail
    the mount instead of silently presenting some other state."""
    tape_dir, mnt = _make_history_tape(
        tmp_path_factory, "rollback-missing", serial="ROLLBX", label="rollbx")

    denied = try_mount_tape(tape_dir, mnt, extra_opts=["rollback_mount=99"])
    assert denied.returncode != 0, \
        "mount must reject a generation that is not on the tape"
    assert not os.path.ismount(mnt)


def test_wipe_unformats_and_reformat_restores(tmp_path_factory):
    """`mkaltfs --wipe` must remove the LTFS structure: afterwards
    the tape neither mounts nor checks as an LTFS volume and the
    old data records are gone. A subsequent format must yield a
    mountable, empty volume again."""
    tape_dir, mnt = _make_history_tape(
        tmp_path_factory, "wipe", serial="WIPE00", label="wipe")

    wipe = subprocess.run(
        ["mkaltfs", "-e", "file", "-d", str(tape_dir), "-w"],
        capture_output=True, text=True, timeout=_RUN_TIMEOUT,
    )
    assert wipe.returncode == MKLTFS_UNFORMATTED, wipe.stderr

    # All LTFS records (labels, data, indexes) are erased; what
    # remains on each partition is at most the block-0 EOD marker.
    ip_records, dp_records = list_records(tape_dir)
    assert ip_records == [] and dp_records == [], \
        "wipe must erase every record file"

    denied = try_mount_tape(tape_dir, mnt)
    assert denied.returncode != 0, "a wiped tape must not mount"
    assert not os.path.ismount(mnt)

    check = run_altfsck(tape_dir=tape_dir)
    assert check.returncode == LTFSCK_UNCORRECTED, check.stdout + check.stderr

    listing = run_altfsck("-l", tape_dir=tape_dir)
    assert listing.returncode == LTFSCK_OPERATIONAL_ERROR, \
        "no rollback points must be listable on a wiped tape"

    # The lifecycle closes: a fresh format brings back an empty,
    # mountable volume.
    format_tape(tape_dir, serial="WIPE01", label="wiped")
    mount_tape(tape_dir, mnt)
    try:
        assert os.listdir(mnt) == []
    finally:
        umount_tape(mnt)


def test_altfsck_rollback_changes_state_seen_by_next_mount(tmp_path_factory):
    """`altfsck --rollback -g <gen>` rewrites the volume while no
    daemon is attached; the next mount must reflect the rolled-back
    state (out-of-band change picked up at mount time), stay
    writable, and — with the default keep-history — the overwritten
    generations must remain listed as rollback points."""
    tape_dir, mnt = _make_history_tape(
        tmp_path_factory, "fsck-rollback", serial="ROLLCK", label="rollck")
    gen_one = _generation_of(tape_dir, "point-one")
    gen_two = _generation_of(tape_dir, "point-two")

    # Rolling back to the generation that is already current is a
    # no-op and must not report a modification.
    noop = run_altfsck("-r", "-g", str(gen_two), tape_dir=tape_dir)
    assert noop.returncode == LTFSCK_NO_ERRORS, noop.stdout + noop.stderr

    # A target that does not exist must fail without changing state.
    missing = run_altfsck("-r", "-g", "99", tape_dir=tape_dir)
    assert missing.returncode == LTFSCK_OPERATIONAL_ERROR, \
        missing.stdout + missing.stderr

    rolled = run_altfsck("-r", "-g", str(gen_one), tape_dir=tape_dir)
    assert rolled.returncode == LTFSCK_CORRECTED, rolled.stdout + rolled.stderr

    # The next mount sees the point-one tree, and the volume is a
    # normal read-write volume (rollback via altfsck is a state
    # change, unlike the read-only rollback mount).
    mount_tape(tape_dir, mnt)
    try:
        assert sorted(os.listdir(mnt)) == ["first.txt"]
        assert (mnt / "first.txt").read_text() == _FIRST_CONTENT
        (mnt / "third.txt").write_text("appended after the rollback\n")
    finally:
        umount_tape(mnt)

    mount_tape(tape_dir, mnt)
    try:
        assert sorted(os.listdir(mnt)) == ["first.txt", "third.txt"]
    finally:
        umount_tape(mnt)

    # keep-history (the default) appends the rolled-back index
    # instead of erasing the newer ones: every original tag is
    # still a listed rollback point.
    listing = run_altfsck("-l", tape_dir=tape_dir)
    assert listing.returncode == LTFSCK_NO_ERRORS, listing.stderr
    listing_out = listing.stdout + listing.stderr
    assert "point-one" in listing_out
    assert "point-two" in listing_out
    assert "Initial Index" in listing_out
