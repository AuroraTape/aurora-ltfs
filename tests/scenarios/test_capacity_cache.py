"""The tape layer caches the remaining capacity (issue #232).

``statfs`` asks libltfs for the remaining capacity, which used to be a
LOG SENSE to the drive every time. macFUSE's FSKit backend asks after
almost every request, about two STATFS per WRITE, and the LOG SENSE
commands between the tape writes halved the write rate. The tape layer
now answers from the drive's last figure and asks again only when a
gibibyte has been written since, or when something has been written and
the figure is ten seconds old; filemarks, load, unload, format, erase
and a capacity reset drop it.

The drive requests are counted with the driver profiler
(``prof_driver_*.dat``, see ``test_profiler.py``): each request is one
ENTER record whose low 16 bits are the request code of ``tape_ops.h``.
"""
import os
import struct
from pathlib import Path

import pytest

from common.altfs import format_tape, mount_tape, umount_tape
from common.helpers import set_xattr

pytestmark = pytest.mark.mount

_PROFILER = "ltfs.vendor.Aurora.profiler"
PROF_DRIVER = 0x4

# Driver profiler record: struct timer_info header, then packed
# { uint64_t time; uint32_t req_num; uint32_t tid; } (ltfstrace.h).
_HEADER = struct.Struct("<QQ")
_RECORD = struct.Struct("<QII")
_REQ_STAT_ENTER = 0x0
_REQ_DRV = 0x222

# Request codes of the tape backend (tape_ops.h, REQ_TC_*).
REQ_TC_TUR = 0x0007
REQ_TC_REMAINCAP = 0x0014


@pytest.fixture(scope="module")
def profiled_mount(tmp_path_factory):
    base = tmp_path_factory.mktemp("capcache")
    tape_dir = base / "tape"
    mnt = base / "mnt"
    work = base / "work"
    for d in (tape_dir, mnt, work):
        d.mkdir()
    format_tape(tape_dir, serial="CAPC00", label="capcache")
    mount_tape(tape_dir, mnt, extra_opts=[f"work_directory={work}"])
    try:
        yield mnt, work
    finally:
        umount_tape(mnt)


def _drive_requests(work):
    """Count of ENTER records per request code in the driver profile."""
    (path,) = sorted(Path(work).glob("prof_driver_*.dat"))
    body = path.read_bytes()[_HEADER.size:]
    counts = {}
    for _time, req_num, _tid in _RECORD.iter_unpack(body):
        if req_num >> 28 != _REQ_STAT_ENTER or (req_num >> 16) & 0xFFF != _REQ_DRV:
            continue
        code = req_num & 0xFFFF
        counts[code] = counts.get(code, 0) + 1
    return counts


def _profile(mnt, work, action):
    """Run action with the driver profiler on and return the request counts."""
    for p in work.glob("prof_*.dat"):
        p.unlink()
    set_xattr(mnt, _PROFILER, hex(PROF_DRIVER))
    try:
        action()
    finally:
        set_xattr(mnt, _PROFILER, "0")
    return _drive_requests(work)


def _settle(mnt):
    """Put the cache in a known state: a sync (filemarks) drops it and the
    statfs after it reads the drive once; from here on nothing has been
    written since that reading."""
    set_xattr(mnt, "ltfs.sync", "1")
    os.statvfs(mnt)


def test_statfs_burst_asks_the_drive_once_at_most(profiled_mount):
    """A burst of statfs calls on an idle volume costs no LOG SENSE at all
    (the last figure is still good) and at most one TEST UNIT READY per
    second."""
    mnt, work = profiled_mount
    _settle(mnt)

    def burst():
        for _ in range(200):
            os.statvfs(mnt)

    counts = _profile(mnt, work, burst)
    assert counts.get(REQ_TC_REMAINCAP, 0) == 0, counts
    assert counts.get(REQ_TC_TUR, 0) <= 2, counts


def test_statfs_during_writes_is_answered_from_the_cache(profiled_mount):
    """Writes under a gibibyte within ten seconds do not make statfs ask the
    drive again, and the figure returned is the drive's, unchanged."""
    mnt, work = profiled_mount
    _settle(mnt)
    before = os.statvfs(mnt).f_bfree

    def write_and_ask():
        for i in range(8):
            (mnt / f"w{i}.bin").write_bytes(os.urandom(1024 * 1024))
            for _ in range(10):
                os.statvfs(mnt)

    counts = _profile(mnt, work, write_and_ask)
    assert counts.get(REQ_TC_REMAINCAP, 0) == 0, counts
    assert os.statvfs(mnt).f_bfree == before


def test_sync_drops_the_cache(profiled_mount):
    """Writing the index ends with filemarks, after which the next statfs
    asks the drive once and the following ones are answered from the cache
    again."""
    mnt, work = profiled_mount
    (mnt / "synced.bin").write_bytes(os.urandom(4096))  # something to index
    set_xattr(mnt, "ltfs.sync", "1")

    def ask():
        for _ in range(50):
            os.statvfs(mnt)

    counts = _profile(mnt, work, ask)
    assert counts.get(REQ_TC_REMAINCAP, 0) == 1, counts
