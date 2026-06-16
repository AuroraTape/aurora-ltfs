"""cp -r a populated tree from outside the FUSE mount into it, and
verify diff -r shows no difference.

Exercises the same code path users hit when archiving a project
onto a tape: lots of small files, nested directories, copied via a
real /usr/bin/cp invocation rather than the Python FS APIs.
"""

import os
import shutil
import subprocess


def _populate_source(tmpdir):
    """Build a moderately broad tree outside the tape mount."""
    for d in ("docs", "src", "data"):
        (tmpdir / d).mkdir()
    (tmpdir / "docs" / "readme.txt").write_text("hello")
    (tmpdir / "docs" / "notes.md").write_text("# notes\n* one\n* two\n")
    (tmpdir / "src" / "main.c").write_text("int main(){return 0;}\n")
    (tmpdir / "src" / "lib.h").write_text("#pragma once\n")
    (tmpdir / "src" / "sub").mkdir()
    (tmpdir / "src" / "sub" / "deep.c").write_text("// deep\n")
    (tmpdir / "data" / "blob.bin").write_bytes(os.urandom(64 * 1024))


def test_cp_recursive(mounted_tape, tmp_path):
    src = tmp_path / "project"
    src.mkdir()
    _populate_source(src)

    dst = mounted_tape / "project"
    subprocess.run(["cp", "-r", str(src), str(dst)], check=True)

    result = subprocess.run(
        ["diff", "-r", str(src), str(dst)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
