"""-o verbose=<syslog level> * 100 + <stderr level>, and --verbose for the commands.

A syslog level above the stderr level must not leak informational
messages to stderr: the mount service runs altfs with verbose=200 so
that the journal, which records both, gets each message once. Only
stderr is checked here; syslog is checked on a real system by
tests/realdrive/service-check.sh.

The mounts fail on purpose (an unformatted tape), which gives both
informational and error messages without a daemon to clean up.
"""

import re
import subprocess

import pytest

from common.altfs import try_mount_tape

INFO = re.compile(r"\bA[A-Z]{2}[0-9A-Z]{4}I\b")
ERROR = re.compile(r"\bA[A-Z]{2}[0-9A-Z]{4}E\b")


@pytest.fixture
def unformatted(tmp_path):
    tape = tmp_path / "tape"
    tape.mkdir()
    mnt = tmp_path / "mnt"
    mnt.mkdir()
    return tape, mnt


@pytest.mark.parametrize("opts, info", [
    ((), True),                  # default verbose=2
    (("verbose=200",), False),   # syslog INFO, stderr ERR
    (("verbose=202",), True),
    (("quiet",), False),
])
def test_stderr_level(unformatted, opts, info):
    tape, mnt = unformatted
    r = try_mount_tape(tape, mnt, extra_opts=opts)
    assert r.returncode != 0
    assert ERROR.search(r.stderr), r.stderr
    assert bool(INFO.search(r.stderr)) == info, r.stderr


DEBUG = re.compile(r"\bA[A-Z]{2}[0-9A-Z]{4}D\b")


def _format(tmp_path, *args):
    tape = tmp_path / "tape"
    tape.mkdir(exist_ok=True)
    return subprocess.run(
        ["mkaltfs", "-e", "file", "-d", str(tape), "-s", "VERB00", "-n", "verbose", "-f", *args],
        capture_output=True, text=True, timeout=120,
    )


@pytest.mark.parametrize("args, info, debug", [
    ((), True, False),               # default: informational, no debug
    (("--verbose=3",), True, True),  # debug messages appear
    (("--verbose=0",), False, False),
    (("-q",), False, False),
])
def test_command_verbose(tmp_path, args, info, debug):
    r = _format(tmp_path, *args)
    assert r.returncode == 0, r.stderr
    assert bool(INFO.search(r.stderr)) == info, r.stderr
    assert bool(DEBUG.search(r.stderr)) == debug, r.stderr


def test_command_quiet_and_verbose_conflict(tmp_path):
    r = _format(tmp_path, "-q", "--verbose=3")
    assert r.returncode != 0
    assert "AMK0081E" in r.stderr, r.stderr


@pytest.mark.parametrize("option", ["-t", "--trace", "--syslogtrace", "-x", "--fulltrace"])
def test_trace_options_are_gone(tmp_path, option):
    """The trace shorthands were removed; getopt rejects them."""
    r = _format(tmp_path, option)
    assert r.returncode != 0, r.stderr


def test_mount_trace_options_are_gone(unformatted):
    """-o trace and -o fulltrace are not mount options any more; FUSE rejects them."""
    tape, mnt = unformatted
    for opt in ("trace", "fulltrace", "syslogtrace"):
        r = try_mount_tape(tape, mnt, extra_opts=(opt,))
        assert r.returncode != 0, r.stderr


@pytest.mark.parametrize("value", ["abc", "3x", "", "-1"])
def test_command_verbose_rejects_non_numbers(tmp_path, value):
    r = _format(tmp_path, f"--verbose={value}")
    assert r.returncode != 0
    assert "AMK0086E" in r.stderr, r.stderr


def test_command_verbose_above_debug_is_clamped(tmp_path):
    """Nothing logs above level 3; a higher number is clamped with a warning."""
    r = _format(tmp_path, "--verbose=7")
    assert r.returncode == 0, r.stderr
    assert "ALG0025W" in r.stderr, r.stderr
    assert DEBUG.search(r.stderr), r.stderr
