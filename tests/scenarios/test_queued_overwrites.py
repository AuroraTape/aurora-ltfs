"""One write covering several separated requests still queued in the
I/O scheduler (#183).

Linux FUSE without writeback_cache forwards every pwrite() as is, so
small writes with holes between them stay in the queue as separate
requests until the file is flushed. A later write that covers more than
one of them must replace all of their bytes, not only the first one's.
macFUSE coalesces such writes in the page cache, so there these tests
do not reach the path they are written for; the byte check still holds.

The data is compared only after a remount: read back on the same mount,
the kernel may serve it from its own cache without asking altfs.
"""
import os
import subprocess

import pytest

from common.altfs import mount_tape, umount_tape

_BLOCKSIZE = 65536


def _format(tape_dir, rules=None):
    cmd = ["mkaltfs", "-e", "file", "-d", str(tape_dir), "-s", "QOVR00",
           "-n", "overwrite", "-b", str(_BLOCKSIZE), "-f"]
    if rules:
        cmd.append(f"--rules={rules}")
    subprocess.run(cmd, check=True, capture_output=True, timeout=60)


_WRITES = {
    # The example in #183
    "two": [(100, 100), (300, 100), (0, 1000)],
    # Covers the second request only partly
    "partly": [(100, 100), (300, 100), (0, 350)],
    # Many small requests under one write
    "many": [(i * 100 + 10, 20) for i in range(50)] + [(0, 5000)],
    # Starts inside a queued request, which the write extends over the others
    "extends": [(0, 10), (100, 10), (300, 10), (0, 1000)],
    # Two requests in a later cache block, under a write spanning blocks
    "across_blocks": [(_BLOCKSIZE + 100, 10), (_BLOCKSIZE + 300, 10),
                      (0, _BLOCKSIZE + 1000)],
}


@pytest.mark.parametrize("rules", [
    None,
    # Small files go to the index partition, so the queued requests target
    # the IP; a covering write that grows the file past 4K ("many",
    # "across_blocks") sends the file to the data partition
    "size=4K",
], ids=["dp", "ip"])
@pytest.mark.parametrize("name", list(_WRITES))
def test_write_over_separated_requests_replaces_them(tmp_path, name, rules):
    writes = _WRITES[name]
    tape_dir = tmp_path / "tape"
    mnt = tmp_path / "mnt"
    tape_dir.mkdir()
    mnt.mkdir()
    _format(tape_dir, rules)
    expected = bytearray()

    mount_tape(tape_dir, mnt)
    try:
        fd = os.open(mnt / "data.bin", os.O_WRONLY | os.O_CREAT, 0o644)
        try:
            for n, (offset, size) in enumerate(writes):
                chunk = bytes([ord("A") + n % 26]) * size
                assert os.pwrite(fd, chunk, offset) == size
                if len(expected) < offset + size:
                    expected.extend(bytes(offset + size - len(expected)))
                expected[offset:offset + size] = chunk
        finally:
            os.close(fd)
    finally:
        umount_tape(mnt)

    mount_tape(tape_dir, mnt)
    try:
        data = (mnt / "data.bin").read_bytes()
    finally:
        umount_tape(mnt)
    assert len(data) == len(expected)
    bad = [i for i in range(len(data)) if data[i] != expected[i]]
    assert not bad, (f"{len(bad)} bytes differ, first at {bad[0]}: "
                     f"{data[bad[0]:bad[0] + 1]!r} instead of "
                     f"{expected[bad[0]:bad[0] + 1]!r}")
