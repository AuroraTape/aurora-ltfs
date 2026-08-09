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


def try_mount_tape(tape_dir, mnt, sync_type="unmount", timeout=30):
    """Attempt a mount that is expected to fail (e.g. damaged volume).

    Runs altfs in the foreground (-f) so the exit status is
    authoritative and no daemon can outlive the call: in the default
    background mode the parent may exit before the volume mount has
    actually completed, which both races the exit status and can
    leak a daemon into later tests. A mount that unexpectedly
    succeeds blocks in the foreground until `timeout` kills it, so
    the TimeoutExpired below doubles as the "volume mounted even
    though it should not have" failure.

    Returns the CompletedProcess so callers can assert on the exit
    status.
    """
    try:
        return subprocess.run(
            ["altfs", "-f",
             "-o", "tape_backend=file",
             "-o", f"devname={tape_dir}",
             "-o", f"sync_type={sync_type}",
             str(mnt)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        subprocess.run(["fusermount", "-u", str(mnt)], check=False)
        raise


def run_altfsck(*args, tape_dir, timeout=30):
    """Run altfsck against a file-backend tape and capture its output."""
    return subprocess.run(
        ["altfsck", "-e", "file", *args, str(tape_dir)],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def umount_tape(mnt):
    # fusermount -u can fail transiently (EBUSY) while the kernel
    # still has an operation on the mount in flight, so retry until
    # the mount actually detaches. A silent single-shot here used to
    # leak a live mount + daemon into later tests whenever that race
    # hit, so failing to detach is now an error.
    def _detach():
        if not os.path.ismount(mnt):
            return True
        subprocess.run(["fusermount", "-u", str(mnt)],
                       capture_output=True, check=False)
        return not os.path.ismount(mnt)

    if not _wait_until(_detach):
        raise RuntimeError(f"could not unmount: {mnt}")

    # fusermount returns as soon as the kernel detaches the mount,
    # but the altfs daemon still has its final index flush to do
    # (sync_type=unmount writes the index on the way out). Tests
    # that read the tape directory after umount race against that
    # flush — most visibly, altfs unlink+creates record files, so
    # an os.listdir hit can vanish a millisecond later. Wait for
    # the altfs process serving this mount to actually exit. The
    # flush can be slow (coverage builds, loaded CI), hence the
    # longer timeout.
    pattern = f"altfs.*{re.escape(str(mnt))}$"
    daemon_gone = _wait_until(
        lambda: subprocess.call(
            ["pgrep", "-f", pattern],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ) != 0,
        timeout=30.0,
    )
    if not daemon_gone:
        raise RuntimeError(f"altfs daemon did not exit after umount: {mnt}")
