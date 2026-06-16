"""I/O at and across the 512 KiB block boundary.

The unified I/O scheduler aggregates FUSE-side requests into
512 KiB records on tape, so write/read patterns that hit, miss,
or cross that boundary exercise the stitching logic that pure
small-file tests don't.
"""

import os

import pytest


_BLOCK = 524288


def _payload(n):
    return os.urandom(n)


@pytest.mark.parametrize(
    "size",
    [
        1,
        4096,
        _BLOCK - 1,
        _BLOCK,
        _BLOCK + 1,
        _BLOCK + _BLOCK // 2,
        2 * _BLOCK,
        2 * _BLOCK + 100 * 1024,
        3 * _BLOCK + 1,
    ],
)
def test_write_then_read_roundtrip(mounted_tape, size):
    p = mounted_tape / f"io_{size}.bin"
    data = _payload(size)
    p.write_bytes(data)
    assert p.stat().st_size == size
    assert p.read_bytes() == data


def test_split_writes_cross_block_boundary(mounted_tape):
    p = mounted_tape / "io_split.bin"
    first = _payload(_BLOCK - 100)
    spanning = _payload(200)
    third = _payload(_BLOCK)

    with open(p, "wb") as f:
        f.write(first)
        f.write(spanning)
        f.write(third)

    expected = first + spanning + third
    assert p.stat().st_size == len(expected)
    assert p.read_bytes() == expected


def test_pwrite_pread_across_block_boundary(mounted_tape):
    p = mounted_tape / "io_pwrite.bin"
    p.write_bytes(b"\x00" * (2 * _BLOCK))
    payload = _payload(2000)
    offset = 512000

    with open(p, "r+b") as f:
        os.pwrite(f.fileno(), payload, offset)

    with open(p, "rb") as f:
        assert os.pread(f.fileno(), 2000, offset) == payload
        assert os.pread(f.fileno(), 100, offset - 100) == b"\x00" * 100
        assert os.pread(f.fileno(), 100, offset + 2000) == b"\x00" * 100


def test_pwrite_extending_creates_zero_gap(mounted_tape):
    p = mounted_tape / "io_pwrite_extend.bin"
    p.write_bytes(b"\x00" * 100)
    payload = _payload(_BLOCK)

    with open(p, "r+b") as f:
        os.pwrite(f.fileno(), payload, _BLOCK)

    assert p.stat().st_size == 2 * _BLOCK
    with open(p, "rb") as f:
        gap = os.pread(f.fileno(), _BLOCK - 100, 100)
        assert gap == b"\x00" * (_BLOCK - 100)
        assert os.pread(f.fileno(), _BLOCK, _BLOCK) == payload
