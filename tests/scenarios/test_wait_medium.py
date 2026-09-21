"""altfs -o wait_medium: start against an empty drive (issue #104).

The file backend can stand for a drive without a medium: when
``devname`` is a regular file instead of a directory, the file is the
"drive" and its content names the cartridge directory next to it, or
says ``empty``. The record is 36 bytes long, NUL padded. Writing a
cartridge name into the file is loading the cartridge.

Without the option altfs fails at once on an empty drive. With it,
altfs polls the drive, continues with the normal mount when a medium
shows up, gives up after the time limit if one is given, and leaves
cleanly — drive released, exit status 0 — when it is told to stop
while it waits.
"""

import os
import signal
import subprocess
import time

import pytest

from common.altfs import format_tape, umount_tape_foreground


_DRIVE_RECORD_SIZE = 36
_CARTRIDGE = "CART01"


def _set_drive(drive, content):
    drive.write_bytes(content.encode().ljust(_DRIVE_RECORD_SIZE, b"\0"))


@pytest.fixture
def station(tmp_path):
    """An empty drive, a formatted cartridge beside it and a mount point."""
    cartridge = tmp_path / _CARTRIDGE
    mnt = tmp_path / "mnt"
    cartridge.mkdir()
    mnt.mkdir()
    format_tape(cartridge, serial=_CARTRIDGE, label="waitmedium")

    drive = tmp_path / "Drive_DRV001.ULT3580-TD5"
    _set_drive(drive, "empty")
    return drive, mnt, tmp_path / "altfs.log"


def _start(drive, mnt, log_path, *options):
    log = open(log_path, "ab")
    cmd = ["altfs", "-f", "-o", "tape_backend=file", "-o", f"devname={drive}",
           "-o", "sync_type=unmount"]
    for option in options:
        cmd += ["-o", option]
    proc = subprocess.Popen(cmd + [str(mnt)], stdout=log, stderr=log)
    proc.altfs_log = log
    return proc


def _wait_for(predicate, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    return predicate()


def _finish(proc, timeout=30):
    try:
        return proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        raise
    finally:
        proc.altfs_log.close()


def test_empty_drive_fails_at_once_without_the_option(station):
    """Also the regression test for the wait loop of libaltfs: a backend
    that answers "need initialize" for an empty drive used to keep
    tape_wait_device_ready() spinning forever, deaf to SIGTERM."""
    drive, mnt, log_path = station

    proc = _start(drive, mnt, log_path)
    assert _finish(proc, timeout=20) == 1
    assert not os.path.ismount(mnt)
    assert "AFS0068E" in log_path.read_text(errors="replace")


def test_mount_continues_when_a_medium_is_loaded(station):
    drive, mnt, log_path = station

    proc = _start(drive, mnt, log_path, "wait_medium")
    try:
        assert _wait_for(
            lambda: "AFS0141I" in log_path.read_text(errors="replace"), 10)
        assert proc.poll() is None and not os.path.ismount(mnt)

        _set_drive(drive, _CARTRIDGE)

        # The drive is polled every five seconds.
        assert _wait_for(lambda: os.path.ismount(mnt), 20), \
            log_path.read_text(errors="replace")
        (mnt / "after-the-wait.txt").write_text("mounted\n")
    except BaseException:
        proc.kill()
        _finish(proc)
        raise

    assert umount_tape_foreground(proc, mnt) == 0
    log = log_path.read_text(errors="replace")
    assert "AFS0143I" in log and "ALB0032I" in log


def test_time_limit(station):
    drive, mnt, log_path = station

    started = time.monotonic()
    proc = _start(drive, mnt, log_path, "wait_medium=2")
    assert _finish(proc, timeout=20) == 1
    assert 2 <= time.monotonic() - started < 10

    log = log_path.read_text(errors="replace")
    assert "AFS0142I" in log and "AFS0145E" in log
    assert not os.path.ismount(mnt)


@pytest.mark.parametrize("signum", [signal.SIGTERM, signal.SIGINT],
                         ids=["SIGTERM", "SIGINT"])
def test_signal_ends_the_wait_cleanly(station, signum):
    drive, mnt, log_path = station

    proc = _start(drive, mnt, log_path, "wait_medium")
    assert _wait_for(
        lambda: "AFS0141I" in log_path.read_text(errors="replace"), 10)

    proc.send_signal(signum)
    assert _finish(proc, timeout=10) == 0
    assert "AFS0144I" in log_path.read_text(errors="replace")
    assert not os.path.ismount(mnt)

    # The drive is free again: a second altfs gets it and mounts.
    _set_drive(drive, _CARTRIDGE)
    proc = _start(drive, mnt, log_path)
    try:
        assert _wait_for(lambda: os.path.ismount(mnt), 20)
    except BaseException:
        proc.kill()
        _finish(proc)
        raise
    assert umount_tape_foreground(proc, mnt) == 0


@pytest.mark.parametrize("value", ["abc", "0", "-5", "10s"])
def test_invalid_time_limit_is_refused(station, value):
    drive, mnt, log_path = station

    proc = _start(drive, mnt, log_path, f"wait_medium={value}")
    assert _finish(proc, timeout=20) == 1
    assert "AFS0146E" in log_path.read_text(errors="replace")


def test_unusable_medium_is_not_waited_for(station, tmp_path):
    """Only an empty drive is waited for: a cartridge that cannot be
    mounted ends altfs like it does without the option."""
    drive, mnt, log_path = station
    (tmp_path / "BLANK1").mkdir()          # a cartridge that was never formatted
    _set_drive(drive, "BLANK1")

    proc = _start(drive, mnt, log_path, "wait_medium")
    assert _finish(proc, timeout=30) == 1
    assert "AFS0141I" not in log_path.read_text(errors="replace")
    assert not os.path.ismount(mnt)
