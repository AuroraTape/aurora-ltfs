import pytest


def test_rename_within_dir(mounted_tape):
    src = mounted_tape / "within_src.txt"
    dst = mounted_tape / "within_dst.txt"
    src.write_text("payload")
    src.rename(dst)
    assert not src.exists()
    assert dst.read_text() == "payload"


def test_rename_across_dirs(mounted_tape):
    sd = mounted_tape / "rn_from"
    td = mounted_tape / "rn_to"
    sd.mkdir()
    td.mkdir()
    src = sd / "f.txt"
    dst = td / "f.txt"
    src.write_text("hi")
    src.rename(dst)
    assert not src.exists()
    assert dst.read_text() == "hi"


def test_rename_directory_with_contents(mounted_tape):
    d = mounted_tape / "rn_dir"
    d.mkdir()
    (d / "inner.txt").write_text("inside")
    moved = mounted_tape / "rn_dir_moved"
    d.rename(moved)
    assert not d.exists()
    assert (moved / "inner.txt").read_text() == "inside"


def test_rename_overwrites_existing_file(mounted_tape):
    src = mounted_tape / "ow_src.txt"
    dst = mounted_tape / "ow_dst.txt"
    src.write_text("new")
    dst.write_text("old")
    src.rename(dst)
    assert not src.exists()
    assert dst.read_text() == "new"


def test_rename_to_missing_parent_raises(mounted_tape):
    src = mounted_tape / "missing_parent_src.txt"
    src.write_text("x")
    bad = mounted_tape / "no_such_dir" / "x.txt"
    with pytest.raises(FileNotFoundError):
        src.rename(bad)
