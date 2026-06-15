import os

import pytest

from common.helpers import get_xattr, set_xattr

_USER_NS = "user."


def test_setxattr_getxattr_roundtrip(mounted_tape):
    p = mounted_tape / "xa_basic.txt"
    p.write_text("payload")
    set_xattr(p, "test.basic", "hello")
    assert get_xattr(p, "test.basic") == "hello"


def test_listxattr_includes_set_attribute(mounted_tape):
    p = mounted_tape / "xa_list.txt"
    p.write_text("payload")
    set_xattr(p, "test.a", "1")
    set_xattr(p, "test.b", "2")
    names = set(os.listxattr(p))
    assert {_USER_NS + "test.a", _USER_NS + "test.b"} <= names


def test_removexattr_deletes_attribute(mounted_tape):
    p = mounted_tape / "xa_rm.txt"
    p.write_text("payload")
    set_xattr(p, "test.del", "x")
    os.removexattr(p, _USER_NS + "test.del")
    with pytest.raises(OSError):
        get_xattr(p, "test.del")


def test_getxattr_missing_raises(mounted_tape):
    p = mounted_tape / "xa_missing.txt"
    p.write_text("payload")
    with pytest.raises(OSError):
        get_xattr(p, "test.never_set")


def test_setxattr_replace_on_missing_raises(mounted_tape):
    p = mounted_tape / "xa_replace.txt"
    p.write_text("payload")
    with pytest.raises(OSError):
        os.setxattr(p, _USER_NS + "test.r", b"x", flags=os.XATTR_REPLACE)


def test_setxattr_create_on_existing_raises(mounted_tape):
    p = mounted_tape / "xa_create.txt"
    p.write_text("payload")
    set_xattr(p, "test.c", "first")
    with pytest.raises(FileExistsError):
        os.setxattr(p, _USER_NS + "test.c", b"second", flags=os.XATTR_CREATE)


def test_xattr_on_directory(mounted_tape):
    d = mounted_tape / "xa_dir"
    d.mkdir()
    set_xattr(d, "test.tag", "v1")
    assert get_xattr(d, "test.tag") == "v1"


def test_xattr_survives_after_writes_to_file(mounted_tape):
    p = mounted_tape / "xa_persist.txt"
    p.write_text("v1")
    set_xattr(p, "test.persist", "tag")
    p.write_text("v2-longer-content")
    assert get_xattr(p, "test.persist") == "tag"
