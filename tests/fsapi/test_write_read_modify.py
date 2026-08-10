"""write → read → modify → read data-integrity cycle.

test_io_block_boundary.py covers single-pass write-then-read; here a
file is re-opened after the fact and modified — in-place overwrite of
a region, append, partial pwrite — and re-read to confirm the merged
content, both within the same mount and across a remount (which
proves the change reached the index / data partition). Sizes are
chosen so each pattern runs once inside a single 512 KiB block and
once crossing the block boundary.
"""

import os

import pytest

from common.altfs import format_tape, mount_tape, umount_tape


_BLOCK = 524288


def _payload(n, seed):
    return bytes((seed + i * 131) % 256 for i in range(n))


def _overwrite(path, offset, data):
    with open(path, "r+b") as f:
        f.seek(offset)
        f.write(data)


@pytest.mark.parametrize(
    "size,offset,patch_len",
    [
        # stays within the first 512 KiB block
        (200_000, 50_000, 10_000),
        # patch crosses the block boundary
        (2 * _BLOCK, _BLOCK - 5_000, 10_000),
    ],
    ids=["in_block", "cross_block"],
)
def test_overwrite_region_and_reread(mounted_tape, size, offset, patch_len):
    p = mounted_tape / f"wrm_over_{size}_{offset}.bin"
    base = _payload(size, 1)
    p.write_bytes(base)
    assert p.read_bytes() == base

    patch = _payload(patch_len, 77)
    _overwrite(p, offset, patch)

    expected = base[:offset] + patch + base[offset + patch_len:]
    assert p.stat().st_size == size
    assert p.read_bytes() == expected


@pytest.mark.parametrize(
    "size,tail_len",
    [
        # total stays within one block
        (100_000, 50_000),
        # append pushes the file across the block boundary
        (_BLOCK - 10_000, 20_000),
    ],
    ids=["in_block", "cross_block"],
)
def test_append_after_reopen_and_reread(mounted_tape, size, tail_len):
    p = mounted_tape / f"wrm_app_{size}.bin"
    base = _payload(size, 2)
    p.write_bytes(base)
    assert p.read_bytes() == base

    tail = _payload(tail_len, 99)
    with open(p, "ab") as f:
        f.write(tail)

    assert p.stat().st_size == size + tail_len
    assert p.read_bytes() == base + tail


def test_multiple_modify_cycles_same_mount(mounted_tape):
    """Several modify → read cycles on one file: each read must see
    exactly the accumulated state, not a stale cache or lost update."""
    p = mounted_tape / "wrm_cycles.bin"
    state = bytearray(_payload(300_000, 3))
    p.write_bytes(state)

    for round_, (offset, length, seed) in enumerate(
        [(0, 1_000, 10), (150_000, 30_000, 20), (299_000, 1_000, 30)]
    ):
        patch = _payload(length, seed)
        _overwrite(p, offset, patch)
        state[offset:offset + length] = patch
        assert p.read_bytes() == bytes(state), f"mismatch after round {round_}"


def test_partial_pwrite_does_not_disturb_neighbors(mounted_tape):
    p = mounted_tape / "wrm_pwrite.bin"
    base = _payload(_BLOCK + 100_000, 4)
    p.write_bytes(base)

    patch = _payload(4096, 55)
    offset = _BLOCK - 2048  # straddles the block boundary
    with open(p, "r+b") as f:
        assert os.pwrite(f.fileno(), patch, offset) == len(patch)

    with open(p, "rb") as f:
        assert os.pread(f.fileno(), 2048, offset - 2048) == \
            base[offset - 2048:offset]
        assert os.pread(f.fileno(), 4096, offset) == patch
        end = offset + 4096
        assert os.pread(f.fileno(), 2048, end) == base[end:end + 2048]


def test_modify_persists_across_remount(tmp_path_factory):
    """Re-open, modify, and re-read across remounts: every modification
    made in mount #2 must be visible in mount #3, proving the new
    extents and index state were committed to tape."""
    base_dir = tmp_path_factory.mktemp("altfs-wrm")
    tape = base_dir / "tape"
    mnt = base_dir / "mnt"
    tape.mkdir()
    mnt.mkdir()
    format_tape(tape, serial="WRMOD0", label="wrm")

    small = _payload(120_000, 5)            # single block
    big = _payload(2 * _BLOCK + 50_000, 6)  # spans 3 blocks

    # Mount 1: create the files.
    mount_tape(tape, mnt)
    try:
        (mnt / "small.bin").write_bytes(small)
        (mnt / "big.bin").write_bytes(big)
    finally:
        umount_tape(mnt)

    small_patch = _payload(5_000, 60)
    big_patch = _payload(20_000, 61)
    tail = _payload(30_000, 62)

    # Mount 2: re-open the existing files and modify them.
    mount_tape(tape, mnt)
    try:
        assert (mnt / "small.bin").read_bytes() == small
        assert (mnt / "big.bin").read_bytes() == big

        _overwrite(mnt / "small.bin", 100_000, small_patch)     # in-block
        _overwrite(mnt / "big.bin", _BLOCK - 10_000, big_patch)  # cross-block
        with open(mnt / "big.bin", "ab") as f:                   # append
            f.write(tail)

        small = small[:100_000] + small_patch + small[105_000:]
        big = (big[:_BLOCK - 10_000] + big_patch
               + big[_BLOCK + 10_000:] + tail)

        assert (mnt / "small.bin").read_bytes() == small
        assert (mnt / "big.bin").read_bytes() == big
    finally:
        umount_tape(mnt)

    # Mount 3: modified content must have been persisted.
    mount_tape(tape, mnt)
    try:
        assert (mnt / "small.bin").stat().st_size == len(small)
        assert (mnt / "small.bin").read_bytes() == small
        assert (mnt / "big.bin").stat().st_size == len(big)
        assert (mnt / "big.bin").read_bytes() == big
    finally:
        umount_tape(mnt)
