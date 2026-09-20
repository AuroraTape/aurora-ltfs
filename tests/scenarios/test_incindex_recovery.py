"""Incremental index round trip: write, crash, recover (issue #133).

Every case builds a small tree, writes a full index, applies changes
and writes them as one or more incremental indexes through the
``ltfs.vendor.Aurora.IncrementalSync`` extended attribute. A copy of
the tape directory taken at that moment is the state a crash would
leave behind (the MAM ``attr_*`` files are left out so the volume
coherency shortcut cannot hide the incremental indexes). ``altfsck``
has to replay the incremental indexes on top of the last full index,
and the recovered volume must show exactly the tree that was mounted
when the last incremental index was written: names, file contents,
link targets, the read-only flag and the extended attributes
(issue #136).

The recovered full index is also compared with the full index that
the clean unmount of the original volume wrote (the ground truth): same
objects, UIDs, time stamps, flags, extended attributes and extents.

This module replaces the shell harness ``tests/incindex-recovery``
(issue #79); its scenario 1 is the case ``foundation``.

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
from common.recovery import crash_and_recover


def _setup_base(mnt):
    (mnt / "d" / "sub").mkdir(parents=True)
    (mnt / "d2").mkdir()
    (mnt / "top.txt").write_text("top\n")
    (mnt / "d.txt").write_text("shares a prefix with d/\n")
    (mnt / "d" / "c.txt").write_text("c\n")
    (mnt / "d" / "sub" / "deep.txt").write_text("deep\n")
    (mnt / "d2" / "keep.txt").write_text("keep\n")
    os.setxattr(mnt / "d2" / "keep.txt", "user.test.base", b"set before")
    os.setxattr(mnt / "d2", "user.test.base", b"set before")


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
    os.setxattr(mnt, "user.test.root", b"on the root directory")
    (mnt / "in-root.txt").write_text("moves the times of the root\n")


def _xattrs_on_files(mnt):
    (mnt / "d" / "tagged.txt").write_text("new and tagged\n")
    os.setxattr(mnt / "d" / "tagged.txt", "user.test.new", b"on a new file")
    os.setxattr(mnt / "d" / "c.txt", "user.test.added", b"on an old file")
    os.setxattr(mnt / "d2" / "keep.txt", "user.test.base", b"changed")
    os.setxattr(mnt / "d2" / "keep.txt", "user.test.second", b"\x00\x01bin")


def _xattr_removed(mnt):
    os.removexattr(mnt / "d2" / "keep.txt", "user.test.base")
    os.removexattr(mnt / "d2", "user.test.base")


def _xattrs_on_dirs(mnt):
    os.setxattr(mnt / "d", "user.test.dir", b"on an existing directory")
    (mnt / "tagged-dir").mkdir()
    os.setxattr(mnt / "tagged-dir", "user.test.dir", b"on a new directory")
    (mnt / "tagged-dir" / "in.txt").write_text("in\n")
    os.setxattr(mnt / "tagged-dir" / "in.txt", "user.test.deep", b"deep")
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


_CASES = [
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
    except BaseException:
        umount_tape(mnt)
        raise

    crash_and_recover(tape_dir, mnt, crashed_dir)


def _inc_index_records(tape_dir):
    records = [p for p in tape_dir.glob("1_*_R")
               if b"<ltfsincrementalindex" in p.read_bytes()[:512]]
    return sorted(records, key=lambda p: int(p.name.split("_")[1]))


def _crashed_volume(tmp_path):
    """A crash state whose only incremental index modifies d/c.txt and
    creates d/e.txt."""
    tape_dir = tmp_path / "tape"
    crashed_dir = tmp_path / "tape-crashed"
    mnt = tmp_path / "mnt"
    tape_dir.mkdir()
    mnt.mkdir()

    format_tape(tape_dir, serial="INCBAD", label="incbad")
    mount_tape(tape_dir, mnt)
    try:
        _setup_base(mnt)
        full_sync(mnt, "base")
        (mnt / "d" / "c.txt").write_text("c changed\n")
        (mnt / "d" / "e.txt").write_text("e\n")
        incremental_sync(mnt, "inc")
        shutil.copytree(tape_dir, crashed_dir,
                        ignore=shutil.ignore_patterns("attr_*"))
    finally:
        umount_tape(mnt)
    return crashed_dir


@pytest.mark.parametrize("old,new,message", [
    # Not well-formed any more: the parser fails inside the entry.
    (b"<file>", b"<fiel>", "ALB0284E"),
    # Well-formed, but an element that cannot live in <contents>.
    (b"<file>", b"<flie>", "ALX0119E"),
    # The existing d/c.txt under another UID.
    (None, None, "ALX0121E"),
], ids=["not-well-formed", "unexpected-tag", "uid-conflict"])
def test_bad_incremental_index_leaves_volume_untouched(tmp_path, old, new,
                                                       message):
    """Recovery is all or nothing: when an incremental index cannot be
    applied, altfsck writes nothing and the volume keeps its last full
    index."""
    crashed_dir = _crashed_volume(tmp_path)

    (record,) = _inc_index_records(crashed_dir)
    data = record.read_bytes()
    if old is None:
        # <file><name>c.txt</name> ... <fileuid>N</fileuid>: bump N of
        # the first file entry by replacing its single digit.
        start = data.index(b"<name>c.txt</name>")
        uid_at = data.index(b"<fileuid>", start) + len(b"<fileuid>")
        digit = data[uid_at:uid_at + 1]
        assert digit.isdigit() and data[uid_at + 1:uid_at + 2] == b"<"
        patched = data[:uid_at] + (b"9" if digit != b"9" else b"8") \
            + data[uid_at + 1:]
    elif new == b"<flie>":
        patched = data.replace(b"<file>", b"<flie>", 1) \
                      .replace(b"</file>", b"</flie>", 1)
    else:
        patched = data.replace(old, new, 1)
    assert patched != data and len(patched) == len(data)
    record.write_bytes(patched)

    def blocks():
        # The MAM attribute files are no part of the medium contents;
        # altfsck may create them.
        return {p.name: p.read_bytes() for p in crashed_dir.iterdir()
                if not p.name.startswith("attr_")}

    before = blocks()

    check = run_altfsck(tape_dir=crashed_dir)
    check_out = check.stdout + check.stderr
    assert check.returncode not in (0, LTFSCK_CORRECTED), check_out
    assert message in check_out, check_out
    assert "ALB0189I" not in check_out

    assert blocks() == before, \
        "a failed recovery must not write to the volume"


def test_clean_recovery_is_quiet(tmp_path):
    """The recovery does not hand the data blocks between the indexes
    to the XML parser, so it logs no libxml errors and no read failure
    when nothing is wrong. (The backward search for the last full index
    that runs before it still probes every section, ALX0023E / ALB0084W
    from there are expected.)"""
    crashed_dir = _crashed_volume(tmp_path)

    check = run_altfsck(tape_dir=crashed_dir)
    check_out = check.stdout + check.stderr
    assert check.returncode == LTFSCK_CORRECTED, check_out
    for noise in ("parser error", "ALB0180E"):
        assert noise not in check_out, check_out
