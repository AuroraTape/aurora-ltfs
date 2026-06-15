import errno

import pytest


def _sentinel(parent, tag):
    """Prove the FS is still responsive on `parent` after an expected
    failure. Catches the symptom that uncovered the unlink bug fixed
    in 0338bbc: a stuck rwlock that deadlocks the next op on the same
    parent."""
    d = parent / f"_sentinel_{tag}"
    d.mkdir()
    assert d.is_dir()


def test_rename_source_missing(mounted_tape):
    with pytest.raises(FileNotFoundError):
        (mounted_tape / "miss_src").rename(mounted_tape / "miss_dst")
    _sentinel(mounted_tape, "src_missing")


def test_rename_dir_onto_nonempty_dir(mounted_tape):
    src = mounted_tape / "ne_src_dir"
    src.mkdir()
    dst = mounted_tape / "ne_dst_dir"
    dst.mkdir()
    (dst / "occupant.txt").write_text("x")
    with pytest.raises(OSError) as ei:
        src.rename(dst)
    assert ei.value.errno in (errno.ENOTEMPTY, errno.EEXIST)
    _sentinel(mounted_tape, "ne_dir")


def test_rename_dir_onto_file(mounted_tape):
    src = mounted_tape / "tm_dir"
    src.mkdir()
    dst = mounted_tape / "tm_file"
    dst.write_text("payload")
    with pytest.raises(OSError):
        src.rename(dst)
    _sentinel(mounted_tape, "dir_over_file")


def test_rename_file_onto_dir(mounted_tape):
    src = mounted_tape / "tm_src_file"
    src.write_text("payload")
    dst = mounted_tape / "tm_dir2"
    dst.mkdir()
    with pytest.raises(OSError):
        src.rename(dst)
    _sentinel(mounted_tape, "file_over_dir")


def test_rename_into_own_subdirectory(mounted_tape):
    parent = mounted_tape / "loop_a"
    parent.mkdir()
    child = parent / "b"
    with pytest.raises(OSError):
        parent.rename(child)
    _sentinel(mounted_tape, "loop")


def test_rename_to_self_is_noop(mounted_tape):
    p = mounted_tape / "self_rename.txt"
    p.write_text("payload")
    p.rename(p)
    assert p.read_text() == "payload"
    _sentinel(mounted_tape, "self")
