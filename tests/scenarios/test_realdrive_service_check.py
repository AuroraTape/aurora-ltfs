"""Keep tests/realdrive/service-check.sh (issue #105) runnable.

The script needs root, systemd and a real drive, so CI can only check that
it parses and that it refuses to run without root. It mounts nothing, which
is why it is not in test_realdrive_scripts.py (marked "mount").
"""
import os
import subprocess
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "realdrive" / "service-check.sh"


def _run(*args):
    return subprocess.run([str(_SCRIPT), *args], capture_output=True, text=True, timeout=30)


def test_service_check_parses():
    assert subprocess.run(["bash", "-n", str(_SCRIPT)]).returncode == 0
    r = _run("--help")
    assert r.returncode == 0
    assert "--after-reboot" in r.stdout and "S7" in r.stdout


def test_service_check_usage_errors():
    r = _run("--device")
    assert r.returncode == 2 and "needs a value" in r.stderr
    if os.geteuid() != 0:
        r = _run("--device", "X")
        assert r.returncode == 2 and "run as root" in r.stderr
