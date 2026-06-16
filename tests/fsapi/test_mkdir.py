import os
import stat

import pytest


def test_mkdir_creates_directory(mounted_tape):
    d = mounted_tape / "newdir"
    d.mkdir()
    assert stat.S_ISDIR(d.stat().st_mode)


def test_mkdir_existing_raises(mounted_tape):
    d = mounted_tape / "dup"
    d.mkdir()
    with pytest.raises(FileExistsError):
        d.mkdir()


def test_rmdir_empty_directory(mounted_tape):
    d = mounted_tape / "empty_dir"
    d.mkdir()
    d.rmdir()
    assert not d.exists()


def test_rmdir_nonempty_raises(mounted_tape):
    d = mounted_tape / "nonempty"
    d.mkdir()
    (d / "file.txt").write_text("x")
    with pytest.raises(OSError):
        d.rmdir()


def test_rmdir_missing_raises(mounted_tape):
    with pytest.raises(FileNotFoundError):
        (mounted_tape / "does_not_exist").rmdir()


def test_listdir_empty_after_mkdir(mounted_tape):
    d = mounted_tape / "ls_empty"
    d.mkdir()
    assert os.listdir(d) == []


def test_listdir_returns_all_entries(mounted_tape):
    d = mounted_tape / "ls_entries"
    d.mkdir()
    (d / "a.txt").write_text("a")
    (d / "b.txt").write_text("b")
    (d / "sub").mkdir()
    assert set(os.listdir(d)) == {"a.txt", "b.txt", "sub"}


def test_nested_mkdir(mounted_tape):
    a = mounted_tape / "nested_a"
    a.mkdir()
    b = a / "b"
    b.mkdir()
    c = b / "c"
    c.mkdir()
    assert c.is_dir()
    assert os.listdir(a) == ["b"]
    assert os.listdir(b) == ["c"]
