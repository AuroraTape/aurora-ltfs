"""Pack a tarball on the host FS, extract it onto the FUSE mount,
verify the file set and contents match.

This is a write-heavy scenario that combines mkdir, file creation,
and (when tar restores mtime/mode) utime/chmod against a real tar
binary.
"""

import os
import subprocess


def _entries(root):
    out = {}
    for dp, _, fns in os.walk(str(root)):
        for fn in fns:
            full = os.path.join(dp, fn)
            rel = os.path.relpath(full, str(root))
            with open(full, "rb") as f:
                out[rel] = f.read()
    return out


def test_tar_extract_onto_tape(mounted_tape, tmp_path):
    src = tmp_path / "tar_src"
    src.mkdir()
    (src / "a.txt").write_text("alpha")
    (src / "b").mkdir()
    (src / "b" / "c.txt").write_text("charlie")
    (src / "b" / "d.bin").write_bytes(os.urandom(8 * 1024))
    (src / "b" / "deeper").mkdir()
    (src / "b" / "deeper" / "e.txt").write_text("echo")

    tarball = tmp_path / "src.tar"
    subprocess.run(
        ["tar", "-cf", str(tarball), "-C", str(src), "."],
        check=True,
    )

    dst = mounted_tape / "extracted"
    dst.mkdir()
    subprocess.run(
        ["tar", "-xf", str(tarball), "-C", str(dst)],
        check=True,
    )

    assert _entries(src) == _entries(dst)
