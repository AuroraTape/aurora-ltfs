"""Build a deep directory tree, mv it to a different deep location,
verify every file and the tree shape survive intact.

This exercises rename of a directory subtree (rather than a single
dentry) and validates the descendants are reachable at the new
path. The shallow rename case is already covered by test_rename.py;
this scenario stresses the recursive descent.
"""

import os
import shutil

_DEPTH = 6
_FILES_PER_DIR = 3


def _build_tree(root):
    cur = root
    for level in range(_DEPTH):
        cur = cur / f"d{level}"
        cur.mkdir()
        for i in range(_FILES_PER_DIR):
            (cur / f"f{i}.txt").write_text(f"{level}:{i}")
    return cur


def _walk_contents(root):
    return {
        os.path.relpath(os.path.join(dp, fn), str(root)): open(
            os.path.join(dp, fn)
        ).read()
        for dp, _, fns in os.walk(str(root))
        for fn in fns
    }


def test_mv_deep_tree(mounted_tape):
    src_root = mounted_tape / "src"
    src_root.mkdir()
    leaf = _build_tree(src_root)
    (leaf / "leaf_marker.txt").write_text("the bottom")

    before = _walk_contents(src_root)
    assert len(before) == _DEPTH * _FILES_PER_DIR + 1

    # mv src → a sibling deep destination chain
    dst_parent = mounted_tape / "dst_chain"
    dst_parent.mkdir()
    for level in range(_DEPTH):
        dst_parent = dst_parent / f"x{level}"
        dst_parent.mkdir()
    dst_root = dst_parent / "moved"

    shutil.move(str(src_root), str(dst_root))

    assert not src_root.exists()
    after = _walk_contents(dst_root)
    assert after == before
