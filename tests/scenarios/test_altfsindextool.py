"""Integration coverage for altfsindextool capture mode.

altfsindextool walks the tape and writes one
`ltfs-index-<partition>-<block>.xml` file per index record it
finds. These tests run capture against tapes built with the
file backend and verify the output via stdlib XML parsing —
they do not assume anything about the file backend's on-disk
record naming, so the same assertions exercise the tool's
public output contract end-to-end.

A regression of the strstr/strncpy scan window bug (Issue #38)
would manifest here as an empty output directory despite
exit-zero, which is exactly what every assertion below catches.
"""

import subprocess
import xml.etree.ElementTree as ET

from common.altfs import format_tape, mount_tape, umount_tape


_RUN_TIMEOUT = 30


def _indextool(tape_dir, output_dir, *extra_args):
    return subprocess.run(
        ["altfsindextool", "-e", "file", "-d", str(tape_dir),
         f"--output-dir={output_dir}", *extra_args],
        capture_output=True,
        text=True,
        timeout=_RUN_TIMEOUT,
    )


def test_capture_clean_tape_writes_initial_index_on_both_partitions(tmp_path_factory):
    """A freshly formatted tape carries the initial index at block 5
    on both partitions. Default capture (no --partition) must
    produce exactly those two files and nothing else."""
    base = tmp_path_factory.mktemp("indextool-clean")
    tape_dir = base / "tape"
    out = base / "out"
    tape_dir.mkdir()
    out.mkdir()
    format_tape(tape_dir, serial="IDXCL0", label="indextool-clean")

    r = _indextool(tape_dir, out)
    assert r.returncode == 0, r.stderr

    names = sorted(p.name for p in out.iterdir())
    assert names == ["ltfs-index-0-5.xml", "ltfs-index-1-5.xml"], names

    for p in out.iterdir():
        root = ET.parse(p).getroot()
        assert root.tag == "ltfsindex"
        # Every index carries the volume UUID; presence confirms
        # we captured a full index record, not a truncated fragment.
        assert root.find("volumeuuid") is not None


def test_capture_partition_override_restricts_output(tmp_path_factory):
    """`--partition=0 --start-pos=5` should produce only the IP
    index, not the DP copy."""
    base = tmp_path_factory.mktemp("indextool-ip")
    tape_dir = base / "tape"
    out = base / "out"
    tape_dir.mkdir()
    out.mkdir()
    format_tape(tape_dir, serial="IDXIP0", label="indextool-ip")

    r = _indextool(tape_dir, out, "--partition=0", "--start-pos=5")
    assert r.returncode == 0, r.stderr

    names = sorted(p.name for p in out.iterdir())
    assert names == ["ltfs-index-0-5.xml"], names


def test_capture_after_writes_picks_up_new_dp_index(tmp_path_factory):
    """Mount → write → unmount (sync_type=unmount) appends new
    DP indexes past block 5. Capture on partition 1 must therefore
    produce more than one file, and the latest one must reflect
    the new file we wrote."""
    base = tmp_path_factory.mktemp("indextool-write")
    tape_dir = base / "tape"
    mnt = base / "mnt"
    out = base / "out"
    tape_dir.mkdir()
    mnt.mkdir()
    out.mkdir()

    format_tape(tape_dir, serial="IDXWR0", label="indextool-write")
    mount_tape(tape_dir, mnt)
    try:
        (mnt / "hello.txt").write_text("indextool test")
    finally:
        umount_tape(mnt)

    r = _indextool(tape_dir, out, "--partition=1")
    assert r.returncode == 0, r.stderr

    dp_files = list(out.iterdir())
    assert len(dp_files) >= 2, [p.name for p in dp_files]

    latest = max(dp_files, key=lambda p: int(p.stem.rsplit("-", 1)[-1]))
    root = ET.parse(latest).getroot()
    names = {e.text for e in root.iter("name")}
    assert "hello.txt" in names, names


def test_capture_quiet_still_writes_files(tmp_path_factory):
    """--quiet suppresses LTFSAIX info messages but the captured
    files must still appear."""
    base = tmp_path_factory.mktemp("indextool-quiet")
    tape_dir = base / "tape"
    out = base / "out"
    tape_dir.mkdir()
    out.mkdir()
    format_tape(tape_dir, serial="IDXQT0", label="indextool-quiet")

    r = _indextool(tape_dir, out, "--quiet")
    assert r.returncode == 0, r.stderr
    # Quiet should silence the AIX0030I "Reading an index" lines.
    assert "LTFSAIX0030I" not in (r.stdout + r.stderr)
    assert list(out.iterdir())
