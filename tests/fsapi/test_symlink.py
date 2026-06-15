import os
import stat

import pytest


def test_symlink_to_existing_file_resolves(mounted_tape):
    target = mounted_tape / "sl_target.txt"
    target.write_text("payload")
    link = mounted_tape / "sl_link"
    link.symlink_to(target)
    assert link.read_text() == "payload"


def test_readlink_returns_stored_target(mounted_tape):
    target = mounted_tape / "sl_readlink_target.txt"
    target.write_text("x")
    link = mounted_tape / "sl_readlink"
    link.symlink_to(target)
    assert os.readlink(link) == str(target)


def test_lstat_reports_symlink_stat_follows(mounted_tape):
    target = mounted_tape / "sl_stat_target.txt"
    target.write_text("x")
    link = mounted_tape / "sl_stat_link"
    link.symlink_to(target)
    assert stat.S_ISLNK(link.lstat().st_mode)
    assert stat.S_ISREG(link.stat().st_mode)


def test_dangling_symlink(mounted_tape):
    link = mounted_tape / "sl_dangling"
    link.symlink_to(mounted_tape / "no_such_target")
    assert stat.S_ISLNK(link.lstat().st_mode)
    with pytest.raises(FileNotFoundError):
        link.stat()


def test_readlink_on_regular_file_raises(mounted_tape):
    p = mounted_tape / "sl_regular.txt"
    p.write_text("x")
    with pytest.raises(OSError):
        os.readlink(p)
