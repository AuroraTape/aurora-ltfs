"""The incremental index cases: a base tree and the change sequences.

Shared by tests/scenarios/test_incindex_recovery.py (write, crash, recover
on one machine) and tests/xplat/make_images.py (build the crash states on
Linux for the cross-platform volume check, issue #141). Every step works
on a mounted volume and records its changes with the
``ltfs.vendor.Aurora.IncrementalSync`` extended attribute between steps
(see the callers).

The cases concentrate on what the incremental index has to express
beyond "a new file in the root directory": changes below directories
that already exist in the full index, renames, and paths that share a
name prefix with a directory created or deleted in the same session.
"""

import os
import shutil

from common.helpers import remove_xattr, set_xattr


def setup_base(mnt):
    (mnt / "d" / "sub").mkdir(parents=True)
    (mnt / "d2").mkdir()
    (mnt / "top.txt").write_text("top\n")
    (mnt / "d.txt").write_text("shares a prefix with d/\n")
    (mnt / "d" / "c.txt").write_text("c\n")
    (mnt / "d" / "sub" / "deep.txt").write_text("deep\n")
    (mnt / "d2" / "keep.txt").write_text("keep\n")
    set_xattr(mnt / "d2" / "keep.txt", "test.base", b"set before")
    set_xattr(mnt / "d2", "test.base", b"set before")


def _foundation(mnt):
    """Scenario 1 of the former shell harness: an unchanged file stays
    (L01), a file is modified (L02), a file is deleted (L03), a directory
    is created (D02) with a new file in it (L06), and a directory is
    deleted together with its child (D03)."""
    with open(mnt / "top.txt", "a") as f:
        f.write("changed\n")
    (mnt / "d.txt").unlink()
    (mnt / "new_dir").mkdir()
    (mnt / "new_dir" / "child.txt").write_text("hello\n")
    (mnt / "d" / "sub" / "deep.txt").unlink()
    (mnt / "d" / "sub").rmdir()


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


def _root_directory(mnt):
    # The root is no journal entry; the incremental index opens with it.
    set_xattr(mnt, "test.root", b"on the root directory")
    (mnt / "in-root.txt").write_text("moves the times of the root\n")


def _xattrs_on_files(mnt):
    (mnt / "d" / "tagged.txt").write_text("new and tagged\n")
    set_xattr(mnt / "d" / "tagged.txt", "test.new", b"on a new file")
    set_xattr(mnt / "d" / "c.txt", "test.added", b"on an old file")
    set_xattr(mnt / "d2" / "keep.txt", "test.base", b"changed")
    set_xattr(mnt / "d2" / "keep.txt", "test.second", b"\x00\x01bin")


def _xattr_removed(mnt):
    remove_xattr(mnt / "d2" / "keep.txt", "test.base")
    remove_xattr(mnt / "d2", "test.base")


def _xattrs_on_dirs(mnt):
    set_xattr(mnt / "d", "test.dir", b"on an existing directory")
    (mnt / "tagged-dir").mkdir()
    set_xattr(mnt / "tagged-dir", "test.dir", b"on a new directory")
    (mnt / "tagged-dir" / "in.txt").write_text("in\n")
    set_xattr(mnt / "tagged-dir" / "in.txt", "test.deep", b"deep")
    # The directory is also the path to a changed child.
    (mnt / "d" / "c.txt").write_text("c changed\n")


def _read_only(mnt):
    os.chmod(mnt / "d" / "c.txt", 0o444)
    os.chmod(mnt / "d2", 0o555)
    (mnt / "ro-new.txt").write_text("born read-only\n")
    os.chmod(mnt / "ro-new.txt", 0o444)


def _symlinks(mnt):
    os.symlink("c.txt", mnt / "d" / "to-c")
    os.symlink("../top.txt", mnt / "d" / "sub" / "to-top")


def _replace_dir_then_remove(mnt):
    # d2 of the full index is emptied and replaced by d/sub, then the
    # new d2 goes as well. The old d2 must still be deleted on the tape.
    (mnt / "d2" / "keep.txt").unlink()
    os.rename(mnt / "d" / "sub", mnt / "d2")
    shutil.rmtree(mnt / "d2")


def _replace_file(mnt):
    (mnt / "d" / "fresh.txt").write_text("replaces d/c.txt\n")
    os.rename(mnt / "d" / "fresh.txt", mnt / "d" / "c.txt")
    os.rename(mnt / "top.txt", mnt / "d.txt")


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


CASES = [
    ("foundation", [_foundation]),
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
    ("root-directory", [_root_directory]),
    ("xattrs-on-files", [_xattrs_on_files]),
    ("xattr-removed", [_xattr_removed]),
    ("xattrs-on-dirs", [_xattrs_on_dirs]),
    ("read-only", [_read_only]),
    ("symlinks", [_symlinks]),
    # _read_only comes last: it write-protects d/c.txt and d2.
    ("metadata-chain", [_xattrs_on_files, _xattr_removed, _symlinks,
                        _xattrs_on_dirs, _read_only]),
    ("replace-dir-then-remove", [_replace_dir_then_remove]),
    ("replace-file", [_replace_file]),
    ("create-dir-with-prefix-sibling", [_create_dir_with_prefix_sibling]),
    ("delete-dir-with-prefix-sibling", [_delete_dir_with_prefix_sibling]),
    ("chain", [_create_in_existing_dir, _modify_in_existing_dirs,
               _rename_across_dirs, _changes_in_sibling_dirs]),
]
