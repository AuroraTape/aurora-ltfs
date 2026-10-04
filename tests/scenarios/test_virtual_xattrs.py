"""Virtual extended attributes and statfs that ask the drive.

The attributes on the volume root that libltfs answers through the tape
backend: the TapeAlert flags, the append position and the number of
referenced blocks, the mount node and the vendor-unique attributes of
the backend. statfs reports the volume capacity and the number of
files.

The MAM and log page dumps are in test_vendor_page_xattrs.py, the
Recommended Access Order requests in test_rao_xattr.py.
"""
import errno
import os
import re

import pytest

from common.altfs import format_tape, mount_tape, umount_tape
from common.helpers import get_xattr, set_xattr

pytestmark = pytest.mark.mount  # every test here goes through a FUSE mount

_VENDOR = "ltfs.vendor.Aurora."
# ENOATTR on macOS and the BSDs
_NO_ATTR = getattr(errno, "ENOATTR", errno.ENODATA)
# LTFS_DEFAULT_BLOCKSIZE in src/libltfs/ltfs.h
_BLOCK = 512 * 1024


@pytest.fixture
def mnt(tmp_path):
    tape_dir = tmp_path / "tape"
    mnt = tmp_path / "mnt"
    tape_dir.mkdir()
    mnt.mkdir()
    format_tape(tape_dir)
    mount_tape(tape_dir, mnt)
    try:
        yield mnt
    finally:
        umount_tape(mnt)


def _errno_of(fn):
    with pytest.raises(OSError) as e:
        fn()
    return e.value.errno


def test_statfs_counts_files_and_reports_capacity(mnt):
    def used_inodes(st):
        # f_ffree is f_files minus the number of files on the volume
        # (directories are not counted)
        return st.f_files - st.f_ffree

    before = os.statvfs(mnt)
    assert before.f_blocks > 0
    assert 0 < before.f_bavail <= before.f_bfree <= before.f_blocks

    (mnt / "dir").mkdir()
    (mnt / "dir" / "a").write_bytes(b"a")
    (mnt / "b").write_bytes(b"b")
    assert used_inodes(os.statvfs(mnt)) == used_inodes(before) + 2

    (mnt / "b").unlink()
    assert used_inodes(os.statvfs(mnt)) == used_inodes(before) + 1


def test_capacity_attributes(mnt):
    total_dp = int(get_xattr(mnt, "ltfs.mediaDataPartitionTotalCapacity"))
    avail_dp = int(get_xattr(mnt, "ltfs.mediaDataPartitionAvailableSpace"))
    total_ip = int(get_xattr(mnt, "ltfs.mediaIndexPartitionTotalCapacity"))
    avail_ip = int(get_xattr(mnt, "ltfs.mediaIndexPartitionAvailableSpace"))
    assert 0 < avail_dp <= total_dp
    assert 0 < avail_ip <= total_ip


def test_tape_alert_reads_and_accepts_a_mask(mnt):
    assert get_xattr(mnt, "ltfs.mediaStorageAlert") == "0x0000000000000000"
    # Writing a hexadecimal mask clears those flags. The file backend never
    # raises a flag, so only the request is checked here, not its effect.
    set_xattr(mnt, "ltfs.mediaStorageAlert", "0x1")
    assert get_xattr(mnt, "ltfs.mediaStorageAlert") == "0x0000000000000000"
    assert _errno_of(lambda: set_xattr(
        mnt, "ltfs.mediaStorageAlert", "zz")) == errno.EINVAL


def test_block_counts_follow_a_sync(mnt):
    total = int(get_xattr(mnt, _VENDOR + "totalBlocks"))
    referenced = int(get_xattr(mnt, _VENDOR + "referencedBlocks"))
    assert total > 0 and referenced >= 0

    (mnt / "data.bin").write_bytes(os.urandom(3 * _BLOCK))
    set_xattr(mnt, "ltfs.sync", "1")

    assert int(get_xattr(mnt, _VENDOR + "totalBlocks")) > total
    assert int(get_xattr(mnt, _VENDOR + "referencedBlocks")) >= referenced + 3


def test_cartridge_mount_node(mnt):
    assert get_xattr(mnt, _VENDOR + "cartridgeMountNode") == "localhost"


def test_vendor_unique_attributes_go_to_the_backend(mnt):
    # The file backend answers seekLatency itself, and resets it on "0"
    assert re.fullmatch(r"\d+s\d+ns", get_xattr(mnt, _VENDOR + "seekLatency"))
    set_xattr(mnt, _VENDOR + "seekLatency", "0")
    assert _errno_of(lambda: set_xattr(
        mnt, _VENDOR + "seekLatency", "5")) == errno.EINVAL

    # Names the backend does not know
    assert _errno_of(lambda: get_xattr(
        mnt, _VENDOR + "noSuchAttribute")) == _NO_ATTR
    assert _errno_of(lambda: set_xattr(
        mnt, _VENDOR + "noSuchAttribute", "1")) == errno.EACCES
    assert _errno_of(lambda: get_xattr(
        mnt, "ltfs.vendor.OtherVendor.seekLatency")) == _NO_ATTR
