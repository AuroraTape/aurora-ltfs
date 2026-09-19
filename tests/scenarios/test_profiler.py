"""Request / I/O scheduler / driver profiler (issue #76).

The profiler is driven through the vendor virtual xattr
``ltfs.vendor.Aurora.profiler``. Writing a bitmask (PROF_REQ 0x1,
PROF_IOSCHED 0x2, PROF_DRIVER 0x4, ``ltfstrace.h``) starts the selected
sources, each of which writes a binary ``prof_*.dat`` file into the work
directory; writing 0 stops them. Reading the xattr returns the trace
time offset.

The files are written through stdio, so their content only reaches the
disk when profiling is stopped: every size check below happens after the
stop.
"""
import csv
import errno
import io
import json
import os
import re
import struct
import subprocess
import sys
from pathlib import Path

import pytest

from common.altfs import format_tape, mount_tape, umount_tape
from common.helpers import get_xattr, set_xattr

_PROFILER = "ltfs.vendor.Aurora.profiler"

PROF_REQ = 0x1
PROF_IOSCHED = 0x2
PROF_DRIVER = 0x4
PROF_ALL = PROF_REQ | PROF_IOSCHED | PROF_DRIVER

# File name pattern of each source (REQ_PROFILER_FILE, IOSCHED_PROFILER_BASE
# + volume UUID, DRIVER_PROFILER_BASE + drive serial in ltfstrace.h).
_GLOBS = {
    PROF_REQ: "prof_request.dat",
    PROF_IOSCHED: "prof_iosched_*.dat",
    PROF_DRIVER: "prof_driver_*.dat",
}

# REQ_SOURCE_MASK field of req_num for each source (REQ_FUSE / REQ_IOS /
# REQ_DRV in ltfstrace.h).
_SOURCE_CODE = {
    PROF_REQ: 0x000,
    PROF_IOSCHED: 0x111,
    PROF_DRIVER: 0x222,
}

# struct timer_info { uint64_t type; uint64_t base; } followed by packed
# struct profiler_entry { uint64_t time; uint32_t req_num; uint32_t tid; }.
_HEADER = struct.Struct("<QQ")
_RECORD = struct.Struct("<QII")

_PROF2TRACE = (Path(__file__).resolve().parents[2]
               / "contrib" / "prof2trace" / "prof2trace.py")


@pytest.fixture(scope="module")
def profiled_mount(tmp_path_factory):
    """A mounted volume whose work directory is known to the test."""
    base = tmp_path_factory.mktemp("profiler")
    tape_dir = base / "tape"
    mnt = base / "mnt"
    work = base / "work"
    for d in (tape_dir, mnt, work):
        d.mkdir()

    format_tape(tape_dir, serial="PROF00", label="profiler")
    mount_tape(tape_dir, mnt, extra_opts=[f"work_directory={work}"])
    try:
        yield mnt, work
    finally:
        umount_tape(mnt)


@pytest.fixture
def clean_profiler(profiled_mount):
    """Profiler stopped and no profiler files, before and after the test."""
    mnt, work = profiled_mount

    def reset():
        set_xattr(mnt, _PROFILER, "0")
        for p in work.glob("prof_*.dat"):
            p.unlink()

    reset()
    try:
        yield mnt, work
    finally:
        reset()


def _do_io(mnt, name, size=700_000):
    """Write and read back more than one 512 KiB tape block."""
    p = mnt / name
    payload = os.urandom(size)
    p.write_bytes(payload)
    assert p.read_bytes() == payload


def _profile(mnt, mask, name):
    set_xattr(mnt, _PROFILER, hex(mask))
    _do_io(mnt, name)
    set_xattr(mnt, _PROFILER, "0")


def _files(work, source):
    return sorted(work.glob(_GLOBS[source]))


def _records(path):
    data = path.read_bytes()
    assert len(data) >= _HEADER.size, f"{path.name}: no timer_info header"
    body = data[_HEADER.size:]
    assert len(body) % _RECORD.size == 0, \
        f"{path.name}: {len(body)} bytes is not a whole number of records"
    return list(_RECORD.iter_unpack(body))


def test_all_sources_write_nonempty_files(clean_profiler):
    mnt, work = clean_profiler
    _profile(mnt, PROF_ALL, "all_sources.bin")

    for source in (PROF_REQ, PROF_IOSCHED, PROF_DRIVER):
        files = _files(work, source)
        assert len(files) == 1, (hex(source), [p.name for p in work.iterdir()])
        assert files[0].stat().st_size > _HEADER.size, files[0].name


@pytest.mark.parametrize("source", [PROF_REQ, PROF_IOSCHED, PROF_DRIVER],
                         ids=["request", "iosched", "driver"])
def test_single_source_creates_only_its_file(clean_profiler, source):
    mnt, work = clean_profiler
    _profile(mnt, source, f"single_{source}.bin")

    created = sorted(p.name for p in work.glob("prof_*.dat"))
    expected = [p.name for p in _files(work, source)]
    assert len(expected) == 1, created
    assert created == expected


def test_stop_closes_files(clean_profiler):
    mnt, work = clean_profiler
    _profile(mnt, PROF_ALL, "before_stop.bin")
    sizes = {p.name: p.stat().st_size for p in work.glob("prof_*.dat")}
    assert len(sizes) == 3, sizes

    # Stopping again is harmless, and I/O after the stop is not recorded.
    set_xattr(mnt, _PROFILER, "0")
    _do_io(mnt, "after_stop.bin")
    assert {p.name: p.stat().st_size for p in work.glob("prof_*.dat")} == sizes


def test_getxattr_returns_trace_offset(profiled_mount):
    mnt, _ = profiled_mount
    # ltfs_trace_get_offset(): "<sec>.<nsec, 9 digits>" on Linux.
    value = get_xattr(mnt, _PROFILER)
    assert re.fullmatch(r"\d+\.\d{9}", value), value
    # The offset is fixed when tracing starts; it does not move with use.
    set_xattr(mnt, _PROFILER, hex(PROF_REQ))
    set_xattr(mnt, _PROFILER, "0")
    assert get_xattr(mnt, _PROFILER) == value


# An empty value is not in this list: strtoull() parses it as 0, so it is
# accepted and stops the profiler.
@pytest.mark.parametrize("bad", ["abc", "0x7z", "1 2"])
def test_invalid_value_is_rejected(clean_profiler, bad):
    mnt, work = clean_profiler
    with pytest.raises(OSError) as exc:
        set_xattr(mnt, _PROFILER, bad)
    assert exc.value.errno == errno.EINVAL
    assert list(work.glob("prof_*.dat")) == []


def test_request_profiler_start_failure_is_reported(clean_profiler):
    """Issue #117: the result of starting the request profiler was
    overwritten by the result of the other sources, so the failure was
    reported as success."""
    mnt, work = clean_profiler

    # fopen() cannot open a directory for writing, whoever runs the test.
    blocker = work / "prof_request.dat"
    blocker.mkdir()
    try:
        with pytest.raises(OSError) as exc:
            set_xattr(mnt, _PROFILER, hex(PROF_REQ))
        assert exc.value.errno == errno.EIO      # -LTFS_FILE_ERR

        # The other sources are still started, and the error still wins.
        with pytest.raises(OSError):
            set_xattr(mnt, _PROFILER, hex(PROF_ALL))
        set_xattr(mnt, _PROFILER, "0")
        assert len(_files(work, PROF_IOSCHED)) == 1
        assert len(_files(work, PROF_DRIVER)) == 1
    finally:
        set_xattr(mnt, _PROFILER, "0")
        blocker.rmdir()

    # Once the file can be created again, the request profiler works.
    _profile(mnt, PROF_REQ, "after_failure.bin")
    (path,) = _files(work, PROF_REQ)
    assert path.stat().st_size > _HEADER.size


def test_records_decode(clean_profiler):
    mnt, work = clean_profiler
    _profile(mnt, PROF_ALL, "decode.bin")

    for source in (PROF_REQ, PROF_IOSCHED, PROF_DRIVER):
        (path,) = _files(work, source)
        records = _records(path)
        assert records, path.name

        last_time = {}
        for time, req_num, tid in records:
            # 0xASSSTTTT: A = status (enter 0, event 1, exit 8), SSS = source.
            assert req_num >> 28 in (0x0, 0x1, 0x8), (path.name, hex(req_num))
            assert (req_num >> 16) & 0xFFF == _SOURCE_CODE[source], \
                (path.name, hex(req_num))
            # Records of one thread are in time order. Different threads
            # take the timestamp before they take the file lock, so the
            # file as a whole is only approximately ordered.
            assert time >= last_time.get(tid, 0), (path.name, tid)
            last_time[tid] = time


def _prof2trace(*args):
    return subprocess.run([sys.executable, str(_PROF2TRACE), *map(str, args)],
                          capture_output=True, text=True, timeout=60)


def test_prof2trace_consumes_the_output(clean_profiler):
    """contrib/prof2trace (#40) parses what the profiler writes."""
    mnt, work = clean_profiler
    _profile(mnt, PROF_ALL, "prof2trace.bin")
    files = sorted(work.glob("prof_*.dat"))
    assert len(files) == 3

    # Chrome Trace Event JSON: one process track per input file, and at
    # least one slice or instant event on each of them.
    r = _prof2trace(work)
    assert r.returncode == 0, r.stderr
    events = json.loads(r.stdout)["traceEvents"]
    tracks = {e["pid"] for e in events if e.get("name") == "process_name"}
    assert len(tracks) == 3, events[:5]
    with_data = {e["pid"] for e in events if e.get("ph") in ("X", "i", "I")}
    assert with_data == tracks

    # CSV: every record of every file, nothing skipped.
    r = _prof2trace(work, "--csv")
    assert r.returncode == 0, r.stderr
    rows = list(csv.DictReader(io.StringIO(r.stdout)))
    per_file = {p.name: 0 for p in files}
    for row in rows:
        per_file[row["file"]] += 1
    assert per_file == {p.name: len(_records(p)) for p in files}

    # Summary: one table that mentions all three layers.
    r = _prof2trace(work, "--summary")
    assert r.returncode == 0, r.stderr
    for layer in ("request", "iosched", "driver"):
        assert layer in r.stdout, r.stdout
