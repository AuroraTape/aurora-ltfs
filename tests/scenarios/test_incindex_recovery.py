"""Incremental index round trip: write, crash, recover (issue #133).

Every case builds a small tree, writes a full index, applies changes
and writes them as one or more incremental indexes through the
``ltfs.vendor.Aurora.IncrementalSync`` extended attribute. A copy of
the tape directory taken at that moment is the state a crash would
leave behind (the MAM ``attr_*`` files are left out so the volume
coherency shortcut cannot hide the incremental indexes). ``altfsck``
has to replay the incremental indexes on top of the last full index,
and the recovered volume must show exactly the tree — names and file
contents — that was mounted when the last incremental index was
written.

The cases concentrate on what the incremental index has to express
beyond "a new file in the root directory": changes below directories
that already exist in the full index, renames, and paths that share a
name prefix with a directory created or deleted in the same session.
"""

import os
import shutil

import pytest

from common.altfs import (
    LTFSCK_CORRECTED,
    format_tape,
    mount_tape,
    run_altfsck,
    umount_tape,
)
from common.helpers import full_sync, incremental_sync


def _tree(mnt):
    """Map of relative path -> file content (None for a directory)."""
    tree = {}
    for path in sorted(mnt.rglob("*")):
        rel = str(path.relative_to(mnt))
        tree[rel] = None if path.is_dir() else path.read_bytes()
    return tree


def _setup_base(mnt):
    (mnt / "d" / "sub").mkdir(parents=True)
    (mnt / "d2").mkdir()
    (mnt / "top.txt").write_text("top\n")
    (mnt / "d.txt").write_text("shares a prefix with d/\n")
    (mnt / "d" / "c.txt").write_text("c\n")
    (mnt / "d" / "sub" / "deep.txt").write_text("deep\n")
    (mnt / "d2" / "keep.txt").write_text("keep\n")


def _create_in_existing_dir(mnt):
    (mnt / "d" / "e.txt").write_text("e\n")


def _modify_in_existing_dirs(mnt):
    (mnt / "d" / "c.txt").write_text("c changed\n")
    (mnt / "d" / "sub" / "deep.txt").write_text("deep changed\n")


def _delete_in_existing_dir(mnt):
    (mnt / "d" / "c.txt").unlink()


def _changes_in_sibling_dirs(mnt):
    (mnt / "d" / "sub" / "new.txt").write_text("new\n")
    (mnt / "d2" / "new.txt").write_text("new in d2\n")
    (mnt / "after.txt").write_text("root entry after the directories\n")


def _rename_in_root(mnt):
    os.rename(mnt / "top.txt", mnt / "top2.txt")


def _rename_across_dirs(mnt):
    os.rename(mnt / "d" / "c.txt", mnt / "d" / "sub" / "c2.txt")
    os.rename(mnt / "top.txt", mnt / "d2" / "top.txt")


def _rename_dir(mnt):
    os.rename(mnt / "d" / "sub", mnt / "d2" / "moved")


def _modify_then_delete(mnt):
    (mnt / "d" / "c.txt").write_text("changed, then removed\n")
    (mnt / "d" / "c.txt").unlink()


def _create_then_delete(mnt):
    (mnt / "d" / "short-lived.txt").write_text("gone before the index\n")
    (mnt / "d" / "short-lived.txt").unlink()
    (mnt / "d" / "tmpdir").mkdir()
    (mnt / "d" / "tmpdir").rmdir()
    (mnt / "d" / "stays.txt").write_text("stays\n")


def _create_then_rename(mnt):
    (mnt / "d" / "draft.txt").write_text("draft\n")
    os.rename(mnt / "d" / "draft.txt", mnt / "d2" / "final.txt")


def _delete_then_recreate(mnt):
    (mnt / "d" / "c.txt").unlink()
    (mnt / "d" / "c.txt").write_text("a new file under the old name\n")


def _rename_dir_with_modified_child(mnt):
    (mnt / "d" / "sub" / "deep.txt").write_text("changed before the move\n")
    os.rename(mnt / "d" / "sub", mnt / "moved")


def _rename_parent_of_created_dir(mnt):
    # The journal drops what it holds below "/d" on the rename and must
    # survive further changes afterwards.
    (mnt / "d" / "fresh").mkdir()
    (mnt / "d" / "fresh" / "f.txt").write_text("fresh\n")
    os.rename(mnt / "d", mnt / "renamed")
    (mnt / "renamed" / "fresh" / "g.txt").write_text("after the move\n")
    (mnt / "d2" / "other.txt").write_text("elsewhere\n")


def _create_dir_with_prefix_sibling(mnt):
    # "/d2/..." must not be taken for a descendant of the new "/d2x"
    # and vice versa.
    (mnt / "d2x").mkdir()
    (mnt / "d2x" / "inside.txt").write_text("inside\n")
    (mnt / "d2x.txt").write_text("next to the new directory\n")
    (mnt / "d2" / "late.txt").write_text("late\n")


def _delete_dir_with_prefix_sibling(mnt):
    (mnt / "d.txt").write_text("changed, must survive rm -r d\n")
    shutil.rmtree(mnt / "d")


_CASES = [
    ("create-in-existing-dir", [_create_in_existing_dir]),
    ("modify-in-existing-dirs", [_modify_in_existing_dirs]),
    ("delete-in-existing-dir", [_delete_in_existing_dir]),
    ("changes-in-sibling-dirs", [_changes_in_sibling_dirs]),
    ("rename-in-root", [_rename_in_root]),
    ("rename-across-dirs", [_rename_across_dirs]),
    ("rename-dir", [_rename_dir]),
    ("modify-then-delete", [_modify_then_delete]),
    ("create-then-delete", [_create_then_delete]),
    ("create-then-rename", [_create_then_rename]),
    ("delete-then-recreate", [_delete_then_recreate]),
    ("rename-dir-with-modified-child", [_rename_dir_with_modified_child]),
    ("rename-parent-of-created-dir", [_rename_parent_of_created_dir]),
    ("create-dir-with-prefix-sibling", [_create_dir_with_prefix_sibling]),
    ("delete-dir-with-prefix-sibling", [_delete_dir_with_prefix_sibling]),
    ("chain", [_create_in_existing_dir, _modify_in_existing_dirs,
               _rename_across_dirs, _changes_in_sibling_dirs]),
]


@pytest.mark.parametrize("steps", [c[1] for c in _CASES],
                         ids=[c[0] for c in _CASES])
def test_recovered_tree_matches_mounted_tree(tmp_path, steps):
    tape_dir = tmp_path / "tape"
    crashed_dir = tmp_path / "tape-crashed"
    mnt = tmp_path / "mnt"
    tape_dir.mkdir()
    mnt.mkdir()

    format_tape(tape_dir, serial="INCIDX", label="incidx")
    mount_tape(tape_dir, mnt)
    try:
        _setup_base(mnt)
        full_sync(mnt, "base")
        for number, step in enumerate(steps, 1):
            step(mnt)
            incremental_sync(mnt, f"inc {number}")
        expected = _tree(mnt)
        # Nothing writes to the tape directory at this point: the sync
        # through the extended attribute is synchronous, all files are
        # closed and sync_type=unmount runs no periodic sync.
        shutil.copytree(tape_dir, crashed_dir,
                        ignore=shutil.ignore_patterns("attr_*"))
    finally:
        umount_tape(mnt)

    check = run_altfsck(tape_dir=crashed_dir)
    check_out = check.stdout + check.stderr
    assert check.returncode == LTFSCK_CORRECTED, check_out
    assert "ALB0189I" in check_out, "recovery must complete"

    mount_tape(crashed_dir, mnt)
    try:
        assert _tree(mnt) == expected
    finally:
        umount_tape(mnt)
