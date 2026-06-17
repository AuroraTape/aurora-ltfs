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

import subprocess


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


def test_altfs_no_args_reports_missing_device():
    r = _run("altfs")
    assert r.returncode != 0
    # The default Linux backend (sg) has no default device. Exact
    # message text may evolve; both spellings of the noun appear in
    # the diagnostic and either is a reasonable signal.
    combined = (r.stdout + r.stderr).lower()
    assert "devname" in combined or "device" in combined


def test_altfs_device_list_with_file_backend(tmp_path):
    r = _run(
        "altfs",
        "-o", "tape_backend=file",
        "-o", f"devname={tmp_path}",
        "-o", "device_list",
    )
    assert r.returncode == 0, r.stderr
    assert "Tape Device list" in (r.stdout + r.stderr)


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
