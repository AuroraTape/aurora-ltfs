"""LTFS chmod honors only writability — the chmod request is collapsed
to a single readonly flag (any write bit set → writable). Mode bits
returned by stat are controlled by mount-time file_mode/dir_mode, not
by chmod. See https://www.ibm.com/docs/en/storage-archive-sde/2.4.8?topic=tips-file-permissions
"""

import stat

import pytest


def test_chmod_no_write_bits_makes_readonly(mounted_tape):
    p = mounted_tape / "ro.txt"
    p.write_text("payload")
    p.chmod(0o444)
    with pytest.raises(PermissionError):
        open(p, "w")


def test_chmod_with_write_bit_keeps_writable(mounted_tape):
    p = mounted_tape / "rw.txt"
    p.write_text("payload")
    p.chmod(0o644)
    with open(p, "w") as f:
        f.write("updated")
    assert p.read_text() == "updated"


def test_chmod_readonly_then_writable_round_trip(mounted_tape):
    p = mounted_tape / "round.txt"
    p.write_text("v1")
    p.chmod(0o444)
    with pytest.raises(PermissionError):
        open(p, "w")
    p.chmod(0o644)
    with open(p, "w") as f:
        f.write("v2")
    assert p.read_text() == "v2"


def test_chmod_only_affects_writability_not_mode_bits(mounted_tape):
    p = mounted_tape / "mode_check.txt"
    p.write_text("x")
    p.chmod(0o644)
    m1 = stat.S_IMODE(p.stat().st_mode)
    p.chmod(0o600)
    m2 = stat.S_IMODE(p.stat().st_mode)
    assert m1 == m2


def test_chmod_missing_raises(mounted_tape):
    with pytest.raises(FileNotFoundError):
        (mounted_tape / "chmod_missing").chmod(0o644)
