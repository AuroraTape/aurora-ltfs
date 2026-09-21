"""Keep the real-drive check scripts in tests/realdrive working (issue #152).

The scripts are run by hand on a real drive as root. Here they run in
their dry-run modes against the file backend, so a change in altfs or in
the scripts that would break them shows up in CI instead of at the next
real-drive session.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

from common.altfs import format_tape

_SCRIPTS = Path(__file__).resolve().parents[1] / "realdrive"
_RECORD = 36    # file backend drive file: cartridge name or "empty", NUL padded


def _drive_writer(drive):
    """Shell command that puts NAME ("empty" or a cartridge) into the drive file."""
    return (f"{sys.executable} -c \"import sys; open(sys.argv[1], 'wb')"
            f".write(sys.argv[2].encode().ljust({_RECORD}, b'\\\\0'))\" "
            f"{drive}")


def test_wait_medium_check_dry_run(tmp_path):
    cartridge = tmp_path / "CART01"
    mnt = tmp_path / "mnt"
    cartridge.mkdir()
    mnt.mkdir()
    format_tape(cartridge, serial="CART01", label="waitmedium")
    drive = tmp_path / "Drive_DRV001.ULT3580-TD5"
    drive.write_bytes(b"empty".ljust(_RECORD, b"\0"))

    writer = _drive_writer(drive)
    env = dict(os.environ,
               WM_DRYRUN="1",
               WM_EXTRA_OPTS="-o tape_backend=file -o sync_type=unmount",
               WM_INSERT_CMD=f"{writer} CART01",
               WM_EJECT_CMD=f"{writer} empty",
               WM_LIMIT="4")
    r = subprocess.run([str(_SCRIPTS / "wait-medium-check.sh"),
                        "--device", str(drive), "--mnt", str(mnt)],
                       env=env, capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Summary: 20 passed, 0 failed" in r.stdout, r.stdout
    assert not os.path.ismount(mnt)


def test_host_check_prefix_dry_run(tmp_path):
    prefix = Path(shutil.which("altfs")).resolve().parents[1]
    mnt = tmp_path / "mnt"
    env = dict(os.environ, HC_DRYRUN="1")
    r = subprocess.run([str(_SCRIPTS / "host-check.sh"),
                        "--prefix", str(prefix), "--mnt", str(mnt)],
                       env=env, capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stdout + r.stderr
    assert " 0 failed" in r.stdout, r.stdout
    assert not os.path.ismount(mnt)
