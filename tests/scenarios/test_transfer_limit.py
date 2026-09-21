"""Host transfer limit (issue #148).

A tape block is read and written with one command, so a host path that
cannot transfer a whole block in one command (e.g. 256 KiB for an HBA
behind a Thunderbolt port) cannot use a volume with larger blocks. The sg
backend reports that limit as part of the maximum block size; the file
backend emulates it with ``max_transfer_bytes`` in its per-cartridge
configuration file.
"""
import os
import re
import subprocess

import pytest

from common.altfs import format_tape, mount_tape, run_altfsck, try_mount_tape, umount_tape
from common.helpers import get_xattr

_CONFIG = "filedebug_tc_conf.xml"
_RUN_TIMEOUT = 60


def _set_limit(tape_dir, limit):
    """Set the emulated transfer limit (0 = none) of a file-backend tape."""
    conf = tape_dir / _CONFIG
    text, n = re.subn(r"<max_transfer_bytes>\d*</max_transfer_bytes>",
                      f"<max_transfer_bytes>{limit}</max_transfer_bytes>",
                      conf.read_text())
    assert n == 1, text
    conf.write_text(text)


def _mkaltfs(tape_dir, *extra):
    return subprocess.run(
        ["mkaltfs", "-e", "file", "-d", str(tape_dir), "-s", "XFER00",
         "-n", "xfer", "-f", *extra],
        capture_output=True, text=True, timeout=_RUN_TIMEOUT)


@pytest.fixture
def tape_dir(tmp_path):
    """A formatted file-backend tape (the first format writes the config)."""
    d = tmp_path / "tape"
    d.mkdir()
    format_tape(d, serial="XFER00", label="xfer")
    return d


@pytest.mark.parametrize("limit,expected", [(262144, 262144),
                                            (300000, 262144),
                                            (131072, 131072)])
def test_mkaltfs_lowers_the_default_block_size(tape_dir, tmp_path, limit, expected):
    _set_limit(tape_dir, limit)

    r = _mkaltfs(tape_dir)
    output = r.stdout + r.stderr
    assert r.returncode == 0, output
    assert "AMK0084I" in output, output

    # The volume is usable on the limited host, across several blocks.
    mnt = tmp_path / "mnt"
    mnt.mkdir()
    mount_tape(tape_dir, mnt)
    try:
        assert get_xattr(mnt, "ltfs.volumeBlocksize") == str(expected)
        payload = os.urandom(3 * expected + 1234)
        (mnt / "data.bin").write_bytes(payload)
    finally:
        umount_tape(mnt)
    mount_tape(tape_dir, mnt)
    try:
        assert (mnt / "data.bin").read_bytes() == payload
    finally:
        umount_tape(mnt)


def test_mkaltfs_keeps_the_default_without_a_limit(tape_dir, tmp_path):
    r = _mkaltfs(tape_dir)
    assert r.returncode == 0, r.stderr
    assert "AMK0084I" not in r.stdout + r.stderr

    mnt = tmp_path / "mnt"
    mnt.mkdir()
    mount_tape(tape_dir, mnt)
    try:
        assert get_xattr(mnt, "ltfs.volumeBlocksize") == "524288"
    finally:
        umount_tape(mnt)


def test_mkaltfs_refuses_an_explicit_block_size_above_the_limit(tape_dir):
    _set_limit(tape_dir, 262144)
    r = _mkaltfs(tape_dir, "-b", "524288")
    output = r.stdout + r.stderr
    assert r.returncode != 0, output
    assert "ALB0057E" in output, output
    assert "AMK0084I" not in output


def test_mount_refuses_a_volume_with_larger_blocks(tape_dir, tmp_path):
    # Formatted with 512 KiB blocks (as other implementations do), then
    # brought to a host that transfers at most 256 KiB at once.
    _set_limit(tape_dir, 262144)
    mnt = tmp_path / "mnt"
    mnt.mkdir()

    r = try_mount_tape(tape_dir, mnt)
    output = r.stdout + r.stderr
    assert r.returncode != 0, output
    assert not os.path.ismount(mnt)
    error = [l for l in output.splitlines() if "ALB0013E" in l]
    assert error, output
    assert "524288" in error[0] and "262144" in error[0], error[0]
    # Refused from the label, before any block is read.
    assert "ALX0023E" not in output and "ALP0055E" not in output, output

    r = run_altfsck(tape_dir=tape_dir)
    assert r.returncode != 0
    assert "ALB0013E" in r.stdout + r.stderr


def test_altfsindextool_read_size(tape_dir, tmp_path):
    _set_limit(tape_dir, 262144)
    assert _mkaltfs(tape_dir).returncode == 0   # 256 KiB blocks

    def indextool(out, *extra):
        out.mkdir()
        return subprocess.run(
            ["altfsindextool", "-e", "file", "-d", str(tape_dir),
             f"--output-dir={out}", *extra],
            capture_output=True, text=True, timeout=_RUN_TIMEOUT)

    # Default read size (512 KiB) is lowered to the limit.
    out = tmp_path / "out-default"
    r = indextool(out)
    assert r.returncode == 0, r.stderr
    assert "AIX0069I" in r.stdout + r.stderr
    assert len(list(out.iterdir())) == 2      # initial index on both partitions

    # An explicit read size above the limit is refused.
    r = indextool(tmp_path / "out-explicit", "-b", "524288")
    assert r.returncode != 0
    assert "AIX0070E" in r.stdout + r.stderr
