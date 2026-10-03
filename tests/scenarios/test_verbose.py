"""-o verbose=<syslog level> * 100 + <stderr level>.

A syslog level above the stderr level must not leak informational
messages to stderr: the mount service runs altfs with verbose=200 so
that the journal, which records both, gets each message once. Only
stderr is checked here; syslog is checked on a real system by
tests/realdrive/service-check.sh.

The mounts fail on purpose (an unformatted tape), which gives both
informational and error messages without a daemon to clean up.
"""

import re

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
