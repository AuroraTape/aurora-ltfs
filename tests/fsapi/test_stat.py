import os
import stat
import time

import pytest


def test_stat_regular_file(mounted_tape):
    p = mounted_tape / "stat_reg.txt"
    p.write_text("hello")
    st = p.stat()
    assert stat.S_ISREG(st.st_mode)
    assert st.st_size == 5
    assert st.st_ino != 0


def test_stat_directory(mounted_tape):
    d = mounted_tape / "stat_dir"
    d.mkdir()
    st = d.stat()
    assert stat.S_ISDIR(st.st_mode)


def test_stat_missing_raises(mounted_tape):
    with pytest.raises(FileNotFoundError):
        (mounted_tape / "stat_missing").stat()


def test_fstat_open_file(mounted_tape):
    p = mounted_tape / "fstat.txt"
    p.write_text("payload")
    with open(p, "rb") as f:
        st = os.fstat(f.fileno())
    assert stat.S_ISREG(st.st_mode)
    assert st.st_size == 7


def test_stat_size_reflects_appends(mounted_tape):
    p = mounted_tape / "grow_size.txt"
    p.write_bytes(b"abc")
    assert p.stat().st_size == 3
    with open(p, "ab") as f:
        f.write(b"defgh")
    assert p.stat().st_size == 8


def test_stat_mtime_updates_on_write(mounted_tape):
    p = mounted_tape / "mtime.txt"
    p.write_text("v1")
    t0 = p.stat().st_mtime_ns
    time.sleep(0.02)
    p.write_text("v2")
    t1 = p.stat().st_mtime_ns
    assert t1 > t0
