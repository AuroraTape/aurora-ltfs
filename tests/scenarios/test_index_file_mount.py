"""Mounting an index file without the tape: altfs -o index_file=<file> (#84).

The index is captured with -o capture_index while the tape is mounted.
The mount from that file must show the same tree as the tape: names,
sizes, timestamps, user xattrs and the virtual xattrs that come from
the index. Everything that needs the tape fails cleanly: reading file
contents and the virtual xattrs of the label, the cartridge memory and
the drive fail with ENODATA, changes with EROFS.
"""
import errno
import os
import shutil
import subprocess
import time

import pytest

from common.altfs import (
    env_mount_opts,
    format_tape,
    mount_tape,
    try_mount_tape,
    umount_tape,
)
from common.helpers import get_xattr, set_xattr
from common.index import records_with_tag

pytestmark = pytest.mark.mount  # every test here goes through a FUSE mount

_SERIAL = "IDXF01"
# A file over several blocks of LTFS_DEFAULT_BLOCKSIZE (src/libltfs/ltfs.h)
_BLOCK = 512 * 1024
_FILES = {
    "small.txt": b"small file\n",
    "dir/big.bin": bytes(range(256)) * (3 * _BLOCK // 256),
    "dir/sub/empty": b"",
}
_USER_XATTR = ("dir/big.bin", "test.color", "blue")

# Virtual xattrs served from the index, on the root and on a file
_ROOT_FROM_INDEX = ["ltfs.volumeUUID", "ltfs.volumeName", "ltfs.indexGeneration",
                    "ltfs.indexTime", "ltfs.indexLocation", "ltfs.indexPrevious",
                    "ltfs.indexCreator", "ltfs.indexVersion", "ltfs.commitMessage",
                    "ltfs.policyExists", "ltfs.policyAllowUpdate", "ltfs.softwareVendor"]
_FILE_FROM_INDEX = ["ltfs.createTime", "ltfs.modifyTime", "ltfs.accessTime",
                    "ltfs.changeTime", "ltfs.backupTime", "ltfs.fileUID",
                    "ltfs.partition", "ltfs.startblock"]
# Virtual xattrs of the label, the cartridge memory and the drive
_ROOT_FROM_TAPE = ["ltfs.volumeSerial", "ltfs.volumeFormatTime", "ltfs.volumeBlocksize",
                   "ltfs.labelVersion", "ltfs.partitionMap", "ltfs.mamBarcode",
                   "ltfs.mediaStorageAlert", "ltfs.mediaLoads",
                   "ltfs.mediaDataPartitionTotalCapacity", "ltfs.volumeLockState",
                   "ltfs.vendor.Aurora.totalBlocks",
                   # Counted in blocks of the size in the label
                   "ltfs.vendor.Aurora.referencedBlocks"]


@pytest.fixture(scope="module")
def captured(tmp_path_factory):
    """A tape with a few files, the index captured at unmount, and the
    view of a plain read-only mount of the tape to compare with."""
    base = tmp_path_factory.mktemp("index-file")
    tape_dir, mnt, cap = base / "tape", base / "mnt", base / "captured"
    for d in (tape_dir, mnt, cap):
        d.mkdir()
    format_tape(tape_dir, serial=_SERIAL, label="indexfile")

    mount_tape(tape_dir, mnt, extra_opts=[f"capture_index={cap}"])
    try:
        for rel, data in _FILES.items():
            (mnt / rel).parent.mkdir(parents=True, exist_ok=True)
            (mnt / rel).write_bytes(data)
        set_xattr(mnt / _USER_XATTR[0], _USER_XATTR[1], _USER_XATTR[2])
    finally:
        umount_tape(mnt)

    index_file = cap / f"{_SERIAL}.schema"
    assert index_file.is_file()

    mount_tape(tape_dir, mnt, extra_opts=["ro"])
    try:
        view = _view(mnt)
        root_xattrs = {n: get_xattr(mnt, n) for n in _ROOT_FROM_INDEX}
        file_xattrs = {n: get_xattr(mnt / "dir/big.bin", n) for n in _FILE_FROM_INDEX}
    finally:
        umount_tape(mnt)

    return {"base": base, "tape_dir": tape_dir, "mnt": mnt, "index_file": index_file,
            "view": view, "root_xattrs": root_xattrs, "file_xattrs": file_xattrs}


def _view(mnt):
    """Every entry under mnt with its type, size and timestamps"""
    view = {}
    for top, dirs, files in os.walk(mnt):
        for name in dirs + files:
            path = os.path.join(top, name)
            st = os.stat(path)
            view[os.path.relpath(path, mnt)] = (
                name in dirs, st.st_size, st.st_mtime_ns, st.st_ctime_ns)
    return view


def _mount_index_file(index_file, mnt, extra=()):
    """altfs -o index_file, run as a daemon"""
    subprocess.run(
        ["altfs", "-o", f"index_file={index_file}"] + list(extra) + env_mount_opts() + [str(mnt)],
        check=True, timeout=30)
    deadline = time.monotonic() + 5
    while not os.path.ismount(mnt) and time.monotonic() < deadline:
        time.sleep(0.1)
    if not os.path.ismount(mnt):
        # Do not leave a daemon behind for the next test on this mount point
        subprocess.run(["pkill", "-f", f"altfs.*{mnt}$"], check=False)
        pytest.fail("index file mount did not come up")


@pytest.fixture
def index_mnt(captured):
    mnt = captured["mnt"]
    _mount_index_file(captured["index_file"], mnt)
    try:
        yield mnt
    finally:
        umount_tape(mnt)


def _errno(fn):
    with pytest.raises(OSError) as e:
        fn()
    return e.value.errno


def test_tree_matches_the_tape(captured, index_mnt):
    mnt = index_mnt
    assert _view(mnt) == captured["view"]
    assert get_xattr(mnt / _USER_XATTR[0], _USER_XATTR[1]) == _USER_XATTR[2]


def test_no_tape_backend_is_needed(captured):
    # A backend that does not exist would fail the mount if it were loaded
    mnt = captured["mnt"]
    _mount_index_file(captured["index_file"], mnt, ["-o", "tape_backend=no-such-backend"])
    try:
        assert sorted(os.listdir(mnt)) == ["dir", "small.txt"]
    finally:
        umount_tape(mnt)


def test_virtual_xattrs_from_the_index(captured, index_mnt):
    mnt = index_mnt
    assert {n: get_xattr(mnt, n) for n in _ROOT_FROM_INDEX} == captured["root_xattrs"]
    assert {n: get_xattr(mnt / "dir/big.bin", n)
            for n in _FILE_FROM_INDEX} == captured["file_xattrs"]


@pytest.mark.parametrize("name", _ROOT_FROM_TAPE)
def test_virtual_xattrs_from_the_tape_fail(index_mnt, name):
    mnt = index_mnt
    assert _errno(lambda: get_xattr(mnt, name)) == errno.ENODATA


def test_file_contents_cannot_be_read(index_mnt):
    mnt = index_mnt
    for rel in ("small.txt", "dir/big.bin"):
        fd = os.open(mnt / rel, os.O_RDONLY)
        try:
            assert _errno(lambda: os.read(fd, 4096)) == errno.ENODATA
        finally:
            os.close(fd)
    # Nothing to read: the end of the file is in the index
    assert (mnt / "dir/sub/empty").read_bytes() == b""


def test_changes_are_refused(index_mnt):
    mnt = index_mnt
    for mutate in (
            lambda: (mnt / "new.txt").write_bytes(b"x"),
            lambda: os.mkdir(mnt / "newdir"),
            lambda: os.unlink(mnt / "small.txt"),
            lambda: os.rename(mnt / "small.txt", mnt / "renamed.txt"),
            lambda: set_xattr(mnt / "small.txt", "test.attr", "x")):
        assert _errno(mutate) == errno.EROFS


def test_statfs_reports_no_capacity(index_mnt):
    st = os.statvfs(index_mnt)
    assert st.f_blocks == 0 and st.f_bfree == 0 and st.f_bavail == 0


def _refused(captured, opts):
    mnt = captured["mnt"]
    try:
        # In the foreground: a mount that comes up after all blocks until the timeout
        out = subprocess.run(["altfs", "-f"] + opts + env_mount_opts() + [str(mnt)],
                             capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        umount_tape(mnt)
        raise
    assert out.returncode != 0
    assert not os.path.ismount(mnt)
    return out.stdout + out.stderr


def test_rollback_mount_and_index_file_together_are_refused(captured):
    log = _refused(captured, ["-o", "rollback_mount=1",
                              "-o", f"index_file={captured['index_file']}"])
    assert "AFS0159E" in log


def test_missing_index_file_is_refused(captured):
    log = _refused(captured, ["-o", f"index_file={captured['base'] / 'no-such-index'}"])
    assert "AFS0160E" in log


def test_corrupt_index_file_is_refused(captured):
    bad = captured["base"] / "corrupt.schema"
    data = captured["index_file"].read_bytes()
    bad.write_bytes(data[:len(data) // 2])
    log = _refused(captured, ["-o", f"index_file={bad}"])
    assert "AFS0013E" in log


def test_incremental_index_is_refused(tmp_path):
    tape_dir, mnt = tmp_path / "tape", tmp_path / "mnt"
    tape_dir.mkdir()
    mnt.mkdir()
    format_tape(tape_dir, serial="IDXF02", label="incremental")
    mount_tape(tape_dir, mnt)
    try:
        (mnt / "file").write_bytes(b"data")
        set_xattr(mnt, "ltfs.vendor.Aurora.IncrementalSync", "inc")
    finally:
        umount_tape(mnt)
    (record,) = records_with_tag(tape_dir, "ltfsincrementalindex", partition=1)
    inc = tmp_path / "incremental.schema"
    shutil.copyfile(record, inc)

    # Without the tape, and with it
    for tape in (None, tape_dir):
        out = try_mount_tape(tape, mnt, extra_opts=[f"index_file={inc}"])
        assert out.returncode != 0
        assert not os.path.ismount(mnt)
        # LTFS_XML_INC_INDEX, not a label mismatch
        log = out.stdout + out.stderr
        assert "(-5052)" in log
        assert "ALB0280E" not in log
