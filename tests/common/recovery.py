"""Crash and recover: shared steps of the incremental index recovery tests.

A test mounts a volume, changes it and writes indexes, then calls
``crash_and_recover()`` while the volume is still mounted. The function

1. records the mounted tree (``visible_tree()``),
2. copies the tape directory — the state a crash at this moment would
   leave behind. The MAM ``attr_*`` files are left out so the next
   mount cannot take the volume coherency shortcut,
3. unmounts cleanly; nothing changed in between, so the full index of
   the unmount is the ground truth for the index a recovery has to come
   up with,
4. runs ``altfsck`` on the copy and compares the recovered full index,
   on both partitions, with the ground truth (``index_records()``),
5. mounts the recovered copy and compares the tree.
"""

import os
import shutil
import stat

from common.altfs import (
    LTFSCK_CORRECTED,
    LTFSCK_NO_ERRORS,
    mount_tape,
    run_altfsck,
    umount_tape,
)
from common.index import index_records, parse_latest_index


def visible_tree(mnt):
    """Map of relative path -> everything the index records about the
    object that a user can see: kind and content (link target for a
    symlink), the write permission bits (read-only flag) and the
    ``user.test.*`` extended attributes. The mount point itself is the
    entry "."."""
    tree = {}
    for path in [mnt] + sorted(mnt.rglob("*")):
        rel = str(path.relative_to(mnt))
        if path.is_symlink():
            content = ("link", os.readlink(path))
        elif path.is_dir():
            content = ("dir", None)
        else:
            content = ("file", path.read_bytes())
        xattrs = {key: os.getxattr(path, key, follow_symlinks=False)
                  for key in os.listxattr(path, follow_symlinks=False)
                  if key.startswith("user.test.")}
        writable = bool(stat.S_IMODE(os.lstat(path).st_mode) & 0o222)
        tree[rel] = (content, writable, xattrs)
    return tree


def crash_and_recover(tape_dir, mnt, crashed_dir, need_recovery=True):
    """See the module docstring. `mnt` must be the mounted `tape_dir`;
    it is unmounted when the function returns or raises.

    need_recovery: the crash state is known to end in an incremental
    index, so altfsck must report a corrected volume. Otherwise a
    consistent volume is accepted as well (the last index written may
    have been a full one)."""
    try:
        expected = visible_tree(mnt)
        # Nothing writes to the tape directory at this point: the sync
        # through the extended attribute is synchronous, all files are
        # closed and sync_type=unmount runs no periodic sync. (FUSE
        # releases a file after close() returned, but on Linux that
        # release changes nothing an index records.)
        shutil.copytree(tape_dir, crashed_dir,
                        ignore=shutil.ignore_patterns("attr_*"))
    finally:
        umount_tape(mnt)

    ground_truth = index_records(parse_latest_index(tape_dir))

    check = run_altfsck(tape_dir=crashed_dir)
    check_out = check.stdout + check.stderr
    if need_recovery:
        assert check.returncode == LTFSCK_CORRECTED, check_out
        assert "ALB0189I" in check_out, "recovery must complete"
    else:
        assert check.returncode in (LTFSCK_NO_ERRORS, LTFSCK_CORRECTED), \
            check_out

    # The recovered full index describes every object like the ground
    # truth does: UIDs, time stamps, read-only flags, extended
    # attributes, symlink targets and — the extents — where the data of
    # each file is on the tape.
    for partition in (0, 1):
        recovered = index_records(parse_latest_index(crashed_dir, partition))
        assert recovered == ground_truth, f"partition {partition}"

    mount_tape(crashed_dir, mnt)
    try:
        assert visible_tree(mnt) == expected
    finally:
        umount_tape(mnt)

    return check_out
