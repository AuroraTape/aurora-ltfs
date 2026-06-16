import os

import pytest


def test_truncate_to_zero(mounted_tape):
    p = mounted_tape / "t_zero.txt"
    p.write_bytes(b"abcdefghij")
    os.truncate(p, 0)
    assert p.stat().st_size == 0
    assert p.read_bytes() == b""


def test_truncate_shrink(mounted_tape):
    p = mounted_tape / "t_shrink.txt"
    p.write_bytes(b"abcdefghij")
    os.truncate(p, 5)
    assert p.stat().st_size == 5
    assert p.read_bytes() == b"abcde"


def test_truncate_grow_fills_with_zeros(mounted_tape):
    p = mounted_tape / "t_grow.txt"
    p.write_bytes(b"abcdefghij")
    os.truncate(p, 20)
    assert p.stat().st_size == 20
    assert p.read_bytes() == b"abcdefghij" + b"\x00" * 10


def test_truncate_same_size_is_noop(mounted_tape):
    p = mounted_tape / "t_same.txt"
    p.write_bytes(b"hello")
    os.truncate(p, 5)
    assert p.stat().st_size == 5
    assert p.read_bytes() == b"hello"


def test_ftruncate_via_fd(mounted_tape):
    p = mounted_tape / "t_ftrunc.txt"
    p.write_bytes(b"helloworld")
    with open(p, "r+b") as f:
        os.ftruncate(f.fileno(), 5)
    assert p.read_bytes() == b"hello"


def test_truncate_missing_raises(mounted_tape):
    with pytest.raises(FileNotFoundError):
        os.truncate(mounted_tape / "t_missing.txt", 10)


def test_truncate_directory_raises(mounted_tape):
    d = mounted_tape / "t_dir"
    d.mkdir()
    with pytest.raises(OSError):
        os.truncate(d, 0)
