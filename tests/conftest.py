from __future__ import annotations

import os
import subprocess
import time

import pytest


_READY_TIMEOUT = 5.0
_POLL_INTERVAL = 0.1


def _wait_until(predicate, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(_POLL_INTERVAL)
    return False


@pytest.fixture(scope="module")
def mounted_tape(tmp_path_factory):
    base = tmp_path_factory.mktemp("altfs")
    tape_dir = base / "tape"
    mnt_dir = base / "mnt"
    tape_dir.mkdir()
    mnt_dir.mkdir()

    subprocess.run(
        ["mkaltfs", "-e", "file", "-d", str(tape_dir),
         "-s", "TEST00", "-n", "test", "-f"],
        check=True,
    )
    subprocess.run(
        ["altfs",
         "-o", "tape_backend=file",
         "-o", f"devname={tape_dir}",
         "-o", "sync_type=unmount",
         str(mnt_dir)],
        check=True,
    )
    if not _wait_until(lambda: os.path.ismount(mnt_dir), _READY_TIMEOUT):
        raise RuntimeError(f"FUSE mount did not become ready: {mnt_dir}")

    try:
        yield mnt_dir
    finally:
        subprocess.run(["fusermount", "-u", str(mnt_dir)], check=False)
        _wait_until(lambda: not os.path.ismount(mnt_dir), _READY_TIMEOUT)
