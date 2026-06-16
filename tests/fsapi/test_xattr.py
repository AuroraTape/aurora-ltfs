import base64
import os

import pytest

from common.altfs import format_tape, mount_tape, umount_tape
from common.helpers import get_xattr, set_xattr
from common.index import find_entries_by_name, parse_latest_index

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


def test_unprintable_xattr_value_is_base64_on_tape(tmp_path_factory):
    """An xattr value that contains bytes pathname_validate_xattr_value
    rejects (NUL, 0x7f, high bytes, etc.) must be serialized as
    <value type="base64">...</value> in the index XML, and must
    round-trip back to the original bytes through a re-mount."""
    base = tmp_path_factory.mktemp("altfs-xattr-bin")
    tape = base / "tape"
    mnt = base / "mnt"
    tape.mkdir()
    mnt.mkdir()
    format_tape(tape, serial="XATTRB", label="xattr-bin")

    binary_value = b"\x00\x01\x02\x7f\x80\xfe\xff"
    qname = _USER_NS + "test.binary"

    mount_tape(tape, mnt)
    try:
        f = mnt / "binxattr.txt"
        f.write_text("payload")
        os.setxattr(os.fspath(f), qname, binary_value)
    finally:
        umount_tape(mnt)

    root = parse_latest_index(tape)
    entries = find_entries_by_name(root, {"binxattr.txt"})
    file_el = entries["binxattr.txt"]
    value_el = None
    for xattr in file_el.iter("xattr"):
        if xattr.find("key").text == "test.binary":
            value_el = xattr.find("value")
            break
    assert value_el is not None, "test.binary xattr not present in index"
    assert value_el.get("type") == "base64"
    assert base64.b64decode(value_el.text) == binary_value

    mount_tape(tape, mnt)
    try:
        assert os.getxattr(os.fspath(mnt / "binxattr.txt"), qname) == binary_value
    finally:
        umount_tape(mnt)
