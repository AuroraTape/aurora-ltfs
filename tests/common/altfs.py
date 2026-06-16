"""Format / mount / umount helpers for the altfs file backend.

Used by the module-scoped mounted_tape fixture in tests/conftest.py
and by tests that need to cycle through multiple mounts (e.g. the
index round-trip test). LTFS tape serial is fixed-width: exactly 6
characters.
"""

import os
import re
import subprocess
import time

_READY_TIMEOUT = 5.0
_POLL_INTERVAL = 0.1


def _wait_until(predicate, timeout=_READY_TIMEOUT):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(_POLL_INTERVAL)
    return False


def format_tape(tape_dir, serial="TEST00", label="test"):
    subprocess.run(
        ["mkaltfs", "-e", "file", "-d", str(tape_dir),
         "-s", serial, "-n", label, "-f"],
        check=True,
    )


def mount_tape(tape_dir, mnt, sync_type="unmount"):
    subprocess.run(
        ["altfs",
         "-o", "tape_backend=file",
         "-o", f"devname={tape_dir}",
         "-o", f"sync_type={sync_type}",
         str(mnt)],
        check=True,
    )
    if not _wait_until(lambda: os.path.ismount(mnt)):
        raise RuntimeError(f"FUSE mount did not become ready: {mnt}")


def umount_tape(mnt):
    subprocess.run(["fusermount", "-u", str(mnt)], check=False)
    _wait_until(lambda: not os.path.ismount(mnt))
    # fusermount returns as soon as the kernel detaches the mount,
    # but the altfs daemon still has its final index flush to do
    # (sync_type=unmount writes the index on the way out). Tests
    # that read the tape directory after umount race against that
    # flush — most visibly, altfs unlink+creates record files, so
    # an os.listdir hit can vanish a millisecond later. Wait for
    # the altfs process serving this mount to actually exit.
    pattern = f"altfs.*{re.escape(str(mnt))}$"
    _wait_until(
        lambda: subprocess.call(
            ["pgrep", "-f", pattern],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ) != 0
    )
