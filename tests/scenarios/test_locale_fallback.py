"""Locale fallback warning at startup (issue #121).

Without a usable LANG the commands fall back to a default locale and say
so. The warning used to be a hardcoded "LTFS9015W ..." line printed before
the message catalogs were loaded; it is now a regular catalog message of
each command.
"""
import os
import subprocess

import pytest

from common.altfs import format_tape


def _run_without_lang(cmd):
    env = {k: v for k, v in os.environ.items()
           if k != "LANG" and not k.startswith("LC_")}
    return subprocess.run(cmd, env=env, capture_output=True, text=True,
                          timeout=60)


@pytest.fixture(scope="module")
def tape_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("locale") / "tape"
    d.mkdir()
    format_tape(d, serial="LOCALE", label="locale")
    return d


def _cases(tape_dir, out_dir):
    return [
        ("AMK0082W", "mkaltfs",
         ["mkaltfs", "-e", "file", "-d", str(tape_dir),
          "-s", "LOCALE", "-n", "locale", "-f"]),
        ("ACK0118W", "altfsck",
         ["altfsck", "-e", "file", str(tape_dir)]),
        ("AIX0067W", "altfsindextool",
         ["altfsindextool", "-e", "file", "-d", str(tape_dir),
          f"--output-dir={out_dir}"]),
    ]


def test_fallback_is_reported_with_a_catalog_id(tape_dir, tmp_path):
    for msg_id, name, cmd in _cases(tape_dir, tmp_path):
        r = _run_without_lang(cmd)
        output = r.stdout + r.stderr
        # altfsck uses fsck-style exit codes (1 = corrected), so the exit
        # status is not part of this check; the command must have run.
        assert r.returncode in (0, 1), (name, output)
        warning = [l for l in output.splitlines() if msg_id in l]
        assert len(warning) == 1, (name, output)
        # The text names the command that is actually running.
        assert warning[0].endswith(f"before starting {name}"), warning[0]
        assert "LTFS9015W" not in output and "LTFS9016E" not in output


def test_no_warning_with_a_usable_lang(tape_dir, tmp_path):
    env = dict(os.environ, LANG="C.UTF-8")
    for msg_id, name, cmd in _cases(tape_dir, tmp_path):
        r = subprocess.run(cmd, env=env, capture_output=True, text=True,
                           timeout=60)
        assert r.returncode in (0, 1), (name, r.stderr)
        assert msg_id not in r.stdout + r.stderr, name
