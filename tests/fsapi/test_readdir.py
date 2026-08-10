"""readdir() behavior through the FUSE bridge.

os.listdir() drops "." and ".." before returning, so where the dot
entries matter (ltfs_fuse_readdir fills them explicitly before
walking the dentry list) the stream is read via `ls -a` instead.
"""

import os
import subprocess


def _raw_entries(path):
    """Full readdir stream including "." / ".." (ls -a keeps them)."""
    out = subprocess.run(
        ["ls", "-a", "-1", os.fspath(path)],
        check=True, capture_output=True, text=True,
    ).stdout
    return out.splitlines()


def test_listdir_returns_created_entries(mounted_tape):
    d = mounted_tape / "rd_basic"
    d.mkdir()
    expected = {f"f{i}.txt" for i in range(10)} | {"subdir"}
    for name in expected - {"subdir"}:
        (d / name).write_text(name)
    (d / "subdir").mkdir()
    assert set(os.listdir(d)) == expected


def test_readdir_includes_dot_and_dotdot(mounted_tape):
    d = mounted_tape / "rd_dots"
    d.mkdir()
    (d / "one.txt").write_text("1")
    entries = _raw_entries(d)
    assert "." in entries
    assert ".." in entries
    assert "one.txt" in entries


def test_readdir_empty_directory(mounted_tape):
    d = mounted_tape / "rd_empty"
    d.mkdir()
    assert os.listdir(d) == []
    assert sorted(_raw_entries(d)) == [".", ".."]


def test_readdir_has_no_duplicates(mounted_tape):
    d = mounted_tape / "rd_dup"
    d.mkdir()
    for i in range(50):
        (d / f"e{i:02d}").write_text("x")
    entries = _raw_entries(d)
    assert len(entries) == len(set(entries))
    assert len(entries) == 50 + 2  # files + "." + ".."


def test_readdir_tracks_create_and_unlink(mounted_tape):
    d = mounted_tape / "rd_track"
    d.mkdir()
    (d / "keep.txt").write_text("k")
    (d / "gone.txt").write_text("g")
    assert set(os.listdir(d)) == {"keep.txt", "gone.txt"}

    (d / "gone.txt").unlink()
    assert set(os.listdir(d)) == {"keep.txt"}

    (d / "new.txt").write_text("n")
    assert set(os.listdir(d)) == {"keep.txt", "new.txt"}


def test_readdir_large_directory(mounted_tape):
    """A directory big enough to need several READDIR round-trips
    (the FUSE buffer is 4 KiB-ish per batch) returns every entry
    exactly once."""
    d = mounted_tape / "rd_large"
    d.mkdir()
    expected = {f"file_{i:04d}.dat" for i in range(500)}
    for name in expected:
        (d / name).touch()
    listed = os.listdir(d)
    assert len(listed) == len(expected)
    assert set(listed) == expected


def test_readdir_stable_across_repeated_reads(mounted_tape):
    """Entry set is identical when the directory is re-read after the
    dentry cache has been populated by a previous full listing."""
    d = mounted_tape / "rd_reread"
    d.mkdir()
    expected = {f"r{i}" for i in range(20)}
    for name in expected:
        (d / name).touch()
    first = sorted(os.listdir(d))
    second = sorted(os.listdir(d))
    assert first == second == sorted(expected)
