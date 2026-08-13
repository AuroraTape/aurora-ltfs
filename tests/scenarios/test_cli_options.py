"""CLI option-parser and early-exit paths for altfs and mkaltfs.

These tests do not mount a tape. They invoke each binary with
options that terminate before (or instead of) the FUSE main loop:
version banners, help screens, the device-list mode, and a few
expected error paths (missing required option, unopenable device).

The coverage target is the startup sequence each command shares —
locale resolution, ltfs_init, message-plugin load, getopt parsing,
usage printers, and (for device_list) the tape plugin dispatch.
Every invocation has a short timeout so a regression that hangs a
command fails the test cleanly instead of stalling CI.
"""

import re
import shlex
import subprocess
from pathlib import Path


_TIMEOUT = 10


def _run(*args):
    return subprocess.run(
        list(args),
        capture_output=True,
        text=True,
        timeout=_TIMEOUT,
    )


# ---------- altfs ----------


def test_altfs_version_exits_zero():
    r = _run("altfs", "--version")
    assert r.returncode == 0, r.stderr
    assert "version" in (r.stdout + r.stderr).lower()


def test_altfs_help_exits_zero():
    r = _run("altfs", "-h")
    assert r.returncode == 0, r.stderr
    assert "usage" in (r.stdout + r.stderr).lower()


def test_altfs_help_shows_default_device_with_file_backend():
    # The file backend has a static default device, so the devname
    # help line must include it (issue #21).
    r = _run("altfs", "-o", "tape_backend=file", "--help")
    assert r.returncode == 0, r.stderr
    combined = r.stdout + r.stderr
    assert re.search(r"-o devname=<dev>\s+Tape device \(default: ", combined)


def test_altfs_help_falls_back_without_default_device():
    # An unloadable backend cannot provide a default device; the
    # devname help line must fall back to the plain variant.
    r = _run("altfs", "-o", "tape_backend=nonexistent", "--help")
    assert r.returncode == 0, r.stderr
    combined = r.stdout + r.stderr
    assert re.search(r"-o devname=<dev>\s+Tape device\s*$", combined, re.M)


def test_altfs_no_args_reports_missing_device():
    r = _run("altfs")
    assert r.returncode != 0
    # The default Linux backend (sg) has no default device. Exact
    # message text may evolve; both spellings of the noun appear in
    # the diagnostic and either is a reasonable signal.
    combined = (r.stdout + r.stderr).lower()
    assert "devname" in combined or "device" in combined


def test_altfs_device_list_with_file_backend(tmp_path):
    # No drive-list pointer file exists for the process, so the file
    # backend enumerates nothing: just the header, exit code 0.
    r = _run(
        "altfs",
        "-o", "tape_backend=file",
        "-o", f"devname={tmp_path}",
        "-o", "device_list",
    )
    assert r.returncode == 0, r.stderr
    combined = r.stdout + r.stderr
    assert "Tape Device list" in combined
    assert "Device Name = " not in combined


def test_altfs_device_list_enumerates_file_backend_drives(tmp_path):
    # The file backend enumerates drives by reading /tmp/ltfs<pid>
    # (pid of the altfs process itself), which holds the path of a
    # directory whose Drive_<n>_<serial>.<model> entries are the
    # devices. Launch altfs through `sh -c 'echo ... > /tmp/ltfs$$;
    # exec altfs ...'` so the pointer file is created under the very
    # pid altfs will run as (exec preserves it).
    expected_drives = [
        ("0", "123456", "ULT3580-TD5"),
        ("1", "ABCDEF", "ULT3580-TD6"),
    ]
    drives = tmp_path / "drives"
    drives.mkdir()
    for n, serial, model in expected_drives:
        (drives / f"Drive_{n}_{serial}.{model}").touch()
    # A name without the Drive_ prefix must not be enumerated; the
    # entry-count assertion below is what catches it.
    (drives / "README").touch()

    # set -C (noclobber) refuses to overwrite an existing /tmp/ltfs$$
    # (stale file from a recycled pid, or a symlink planted by another
    # user); pointer_record keeps the exact path for cleanup.
    pointer_record = tmp_path / "pointer_path"
    script = (
        "set -C; "
        f"echo /tmp/ltfs$$ > {shlex.quote(str(pointer_record))} && "
        f"echo {shlex.quote(str(drives))} > /tmp/ltfs$$ || exit 97; "
        f"exec altfs -o tape_backend=file "
        f"-o devname={shlex.quote(str(drives))} -o device_list"
    )
    try:
        r = _run("sh", "-c", script)
    finally:
        if pointer_record.exists():
            pointer = pointer_record.read_text().strip()
            if pointer.startswith("/tmp/ltfs"):
                Path(pointer).unlink(missing_ok=True)

    assert r.returncode == 0, r.stderr
    out = r.stdout + r.stderr
    assert "Tape Device list" in out
    assert out.count("Device Name = ") == len(expected_drives)
    for n, serial, model in expected_drives:
        assert (
            f"Device Name = {drives}/Drive_{n}_{serial}.{model}, "
            f"Vendor ID = DUMMY, Product ID = {model}, "
            f"Serial Number = {serial}, Product Name =[{model}]"
        ) in out


# ---------- mkaltfs ----------


def test_mkaltfs_version_exits_zero():
    r = _run("mkaltfs", "--version")
    assert r.returncode == 0, r.stderr
    assert "version" in (r.stdout + r.stderr).lower()


def test_mkaltfs_help_exits_zero():
    r = _run("mkaltfs", "--help")
    assert r.returncode == 0, r.stderr
    assert "usage" in (r.stdout + r.stderr).lower()


def test_mkaltfs_no_args_fails():
    r = _run("mkaltfs")
    assert r.returncode != 0


def test_mkaltfs_short_serial_rejected(tmp_path):
    # Serial must be exactly 6 characters (see tests/common/altfs.py
    # and the AGENTS conventions). 5-character serials should fail
    # option validation before any device I/O is attempted.
    r = _run("mkaltfs", "-e", "file", "-d", str(tmp_path), "-s", "SHORT")
    assert r.returncode != 0


def test_mkaltfs_open_failure_on_bogus_device():
    r = _run(
        "mkaltfs", "-e", "file",
        "-d", "/nonexistent/path",
        "-s", "123456",
    )
    assert r.returncode != 0
    assert "open" in (r.stdout + r.stderr).lower()


# ---------- altfsck ----------


def test_altfsck_version_exits_zero():
    r = _run("altfsck", "--version")
    assert r.returncode == 0, r.stderr
    assert "version" in (r.stdout + r.stderr).lower()


def test_altfsck_help_exits_zero():
    r = _run("altfsck", "--help")
    assert r.returncode == 0, r.stderr
    assert "usage" in (r.stdout + r.stderr).lower()


def test_altfsck_no_args_fails():
    r = _run("altfsck")
    assert r.returncode != 0


def test_altfsck_verify_without_generation_rejected(tmp_path):
    # MODE_VERIFY (-n / --no-rollback) requires --generation; the
    # validator should reject before opening the device.
    r = _run("altfsck", "-e", "file", "-n", str(tmp_path))
    assert r.returncode != 0


# ---------- altfsindextool ----------


def test_altfsindextool_version_exits_zero():
    r = _run("altfsindextool", "--version")
    assert r.returncode == 0, r.stderr
    assert "version" in (r.stdout + r.stderr).lower()


def test_altfsindextool_help_exits_zero():
    r = _run("altfsindextool", "--help")
    assert r.returncode == 0, r.stderr
    assert "usage" in (r.stdout + r.stderr).lower()


def test_altfsindextool_no_args_fails():
    r = _run("altfsindextool")
    assert r.returncode != 0


def test_altfsindextool_open_failure_on_bogus_device(tmp_path):
    r = _run(
        "altfsindextool", "-e", "file",
        "-d", "/nonexistent/path",
        f"--output-dir={tmp_path}",
    )
    assert r.returncode != 0
    assert "open" in (r.stdout + r.stderr).lower()
