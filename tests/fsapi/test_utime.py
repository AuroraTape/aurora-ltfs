import ctypes
import ctypes.util
import os
import time

import pytest

from common.altfs import format_tape, mount_tape, umount_tape
from common.index import find_entries_by_name, parse_latest_index

# utimensat(2) special tv_nsec values (linux/stat.h), exposed to tests as
# string sentinels so they cannot collide with a genuine nanosecond value.
_NOW = "now"
_OMIT = "omit"
_SPECIAL_NSEC = {_NOW: (1 << 30) - 1, _OMIT: (1 << 30) - 2}
_AT_FDCWD = -100


class _Timespec(ctypes.Structure):
    _fields_ = [("tv_sec", ctypes.c_long), ("tv_nsec", ctypes.c_long)]


_libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
_libc.utimensat.argtypes = [ctypes.c_int, ctypes.c_char_p,
                            ctypes.POINTER(_Timespec), ctypes.c_int]
_libc.utimensat.restype = ctypes.c_int


def _utimensat(path, atime, mtime):
    """Call utimensat(2) directly: os.utime() cannot express the
    UTIME_NOW / UTIME_OMIT special values. atime/mtime are nanosecond
    timestamps, or the _NOW / _OMIT sentinels."""
    times = (_Timespec * 2)()
    for i, val in enumerate((atime, mtime)):
        if val in _SPECIAL_NSEC:
            times[i].tv_sec = 0
            times[i].tv_nsec = _SPECIAL_NSEC[val]
        else:
            times[i].tv_sec = val // 1_000_000_000
            times[i].tv_nsec = val % 1_000_000_000
    ret = _libc.utimensat(_AT_FDCWD, os.fsencode(os.fspath(path)), times, 0)
    if ret != 0:
        errno = ctypes.get_errno()
        raise OSError(errno, os.strerror(errno), str(path))


def test_utime_sets_mtime_and_atime(mounted_tape):
    p = mounted_tape / "ut_basic.txt"
    p.write_text("payload")
    target_atime = 1_600_000_000.5
    target_mtime = 1_600_000_100.25
    os.utime(p, (target_atime, target_mtime))
    st = p.stat()
    assert st.st_atime == target_atime
    assert st.st_mtime == target_mtime


def test_utime_with_none_advances_to_now(mounted_tape):
    p = mounted_tape / "ut_now.txt"
    p.write_text("payload")
    os.utime(p, (1_500_000_000.0, 1_500_000_000.0))
    old = p.stat().st_mtime
    os.utime(p, None)
    new = p.stat().st_mtime
    assert new > old


def test_utime_preserves_size_and_content(mounted_tape):
    p = mounted_tape / "ut_preserve.txt"
    p.write_text("payload")
    os.utime(p, (1_600_000_000.0, 1_600_000_100.0))
    assert p.read_text() == "payload"
    assert p.stat().st_size == len("payload")


def test_utime_missing_raises(mounted_tape):
    with pytest.raises(FileNotFoundError):
        os.utime(mounted_tape / "ut_missing.txt", (1_600_000_000.0, 1_600_000_000.0))


def test_utime_nanosecond_precision(mounted_tape):
    """LTFS stores timestamps as full timespecs, so nanoseconds must
    round-trip exactly through utimens → stat."""
    p = mounted_tape / "ut_ns.txt"
    p.write_text("payload")
    atime_ns = 1_600_000_000_123_456_789
    mtime_ns = 1_600_000_100_987_654_321
    os.utime(p, ns=(atime_ns, mtime_ns))
    st = p.stat()
    assert st.st_atime_ns == atime_ns
    assert st.st_mtime_ns == mtime_ns


def test_utime_on_directory(mounted_tape):
    d = mounted_tape / "ut_dir"
    d.mkdir()
    (d / "inner.txt").write_text("x")
    os.utime(d, ns=(1_600_000_000_000_000_001, 1_600_000_100_000_000_002))
    st = d.stat()
    assert st.st_atime_ns == 1_600_000_000_000_000_001
    assert st.st_mtime_ns == 1_600_000_100_000_000_002


def test_utimensat_omit_atime_keeps_it(mounted_tape):
    p = mounted_tape / "ut_omit_a.txt"
    p.write_text("payload")
    base_ns = 1_500_000_000_000_000_000
    os.utime(p, ns=(base_ns, base_ns))
    new_mtime_ns = 1_600_000_200_111_222_333
    _utimensat(p, _OMIT, new_mtime_ns)
    st = p.stat()
    assert st.st_atime_ns == base_ns
    assert st.st_mtime_ns == new_mtime_ns


def test_utimensat_omit_mtime_keeps_it(mounted_tape):
    p = mounted_tape / "ut_omit_m.txt"
    p.write_text("payload")
    base_ns = 1_500_000_000_000_000_000
    os.utime(p, ns=(base_ns, base_ns))
    new_atime_ns = 1_600_000_300_444_555_666
    _utimensat(p, new_atime_ns, _OMIT)
    st = p.stat()
    assert st.st_atime_ns == new_atime_ns
    assert st.st_mtime_ns == base_ns


def test_utimensat_now_sets_current_time(mounted_tape):
    p = mounted_tape / "ut_now2.txt"
    p.write_text("payload")
    os.utime(p, ns=(1_500_000_000_000_000_000, 1_500_000_000_000_000_000))
    before = time.time()
    _utimensat(p, _NOW, _NOW)
    after = time.time()
    st = p.stat()
    assert before - 1 <= st.st_atime <= after + 1
    assert before - 1 <= st.st_mtime <= after + 1


def test_utime_persists_across_remount(tmp_path_factory):
    """utimens must dirty the index: explicit timestamps survive an
    unmount/remount and land in the on-tape index XML."""
    base = tmp_path_factory.mktemp("altfs-utime")
    tape = base / "tape"
    mnt = base / "mnt"
    tape.mkdir()
    mnt.mkdir()
    format_tape(tape, serial="UTIME0", label="utime")

    atime_ns = 1_600_000_000_123_456_789
    mtime_ns = 1_600_000_100_987_654_321

    mount_tape(tape, mnt)
    try:
        f = mnt / "stamped.txt"
        f.write_text("payload")
        d = mnt / "stamped_dir"
        d.mkdir()
        os.utime(f, ns=(atime_ns, mtime_ns))
        os.utime(d, ns=(atime_ns, mtime_ns))
    finally:
        umount_tape(mnt)

    # Independent check: the timestamps are in the committed index.
    root = parse_latest_index(tape)
    entries = find_entries_by_name(root, {"stamped.txt", "stamped_dir"})
    for name in ("stamped.txt", "stamped_dir"):
        assert entries[name].find("modifytime").text == \
            "2020-09-13T12:28:20.987654321Z"
        assert entries[name].find("accesstime").text == \
            "2020-09-13T12:26:40.123456789Z"

    mount_tape(tape, mnt)
    try:
        for path in (mnt / "stamped.txt", mnt / "stamped_dir"):
            st = path.stat()
            assert st.st_atime_ns == atime_ns
            assert st.st_mtime_ns == mtime_ns
    finally:
        umount_tape(mnt)
