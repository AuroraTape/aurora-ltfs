"""Write requests larger than a tape block.

The I/O scheduler caches writes one tape block at a time, so a single
FUSE write request that is longer than the volume block size has to be
split across several cache blocks. Which request sizes reach altfs
depends on the FUSE implementation: Linux sends up to 128 KiB
(big_writes), macFUSE's kext no more than the block size, and macFUSE's
FSKit backend 1 MiB. A volume formatted with a block size below those
request sizes makes every write span blocks.

The data is compared only after a remount: read back on the same mount,
the kernel may serve it from its own cache without asking altfs.
"""
import os
import subprocess

import pytest

from common.altfs import mount_tape, umount_tape
from common.helpers import get_xattr

pytestmark = pytest.mark.mount  # every test here goes through a FUSE mount

_BLOCKSIZE = 65536


@pytest.fixture
def small_block_tape(tmp_path):
    tape_dir = tmp_path / "tape"
    mnt = tmp_path / "mnt"
    tape_dir.mkdir()
    mnt.mkdir()
    subprocess.run(
        ["mkaltfs", "-e", "file", "-d", str(tape_dir), "-s", "LWRT00",
         "-n", "largewrite", "-b", str(_BLOCKSIZE), "-f"],
        check=True, capture_output=True, timeout=60)
    return tape_dir, mnt


def test_write_requests_larger_than_a_block_keep_every_byte(small_block_tape):
    tape_dir, mnt = small_block_tape
    # Many blocks, ending mid-block; then an unaligned second write that
    # appends across further block boundaries.
    first = os.urandom(16 * _BLOCKSIZE + 1234)
    second = os.urandom(8 * _BLOCKSIZE + 4321)

    mount_tape(tape_dir, mnt)
    try:
        assert get_xattr(mnt, "ltfs.volumeBlocksize") == str(_BLOCKSIZE)
        fd = os.open(mnt / "data.bin", os.O_WRONLY | os.O_CREAT, 0o644)
        try:
            assert os.write(fd, first) == len(first)
            assert os.write(fd, second) == len(second)
        finally:
            os.close(fd)
    finally:
        umount_tape(mnt)

    mount_tape(tape_dir, mnt)
    try:
        data = (mnt / "data.bin").read_bytes()
    finally:
        umount_tape(mnt)
    assert len(data) == len(first) + len(second)
    # Compare block by block so a failure names the first bad block
    # instead of dumping megabytes.
    expected = first + second
    bad = [n for n in range(0, len(data), _BLOCKSIZE)
           if data[n:n + _BLOCKSIZE] != expected[n:n + _BLOCKSIZE]]
    assert not bad, f"{len(bad)} blocks differ, first at offset {bad[0]}"
