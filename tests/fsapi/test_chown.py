"""LTFS does not model per-file ownership at all: the on-tape XML
index has no uid/gid field. Tapes are portable, and a numeric uid
stored on tape would not refer to the same person on a different
system — so per-file ownership isn't just unimplemented, it would be
semantically meaningless across the cartridge's lifetime. Possession
of the tape is the access boundary instead.

ltfs_fuse_chown therefore returns success unconditionally and the
owner reported by stat — sourced from the mount-time uid/gid options
of the current host — never changes.
"""

import os


def test_chown_is_a_noop_to_self(mounted_tape):
    p = mounted_tape / "chown_noop.txt"
    p.write_text("x")
    uid, gid = os.getuid(), os.getgid()
    before = p.stat()
    os.chown(p, uid, gid)
    after = p.stat()
    assert (before.st_uid, before.st_gid) == (after.st_uid, after.st_gid)
