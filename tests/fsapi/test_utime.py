import os

import pytest


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
