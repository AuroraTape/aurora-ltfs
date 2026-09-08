import base64
import os
import re
import uuid

import pytest

from common.altfs import format_tape, mount_tape, umount_tape
from common.helpers import full_sync, get_xattr, get_xattr_int, set_xattr
from common.index import find_entries_by_name, parse_latest_index

_USER_NS = "user."

# xml_format_time() emits "%04d-%02d-%02dT%02d:%02d:%02d.%09ldZ"
_LTFS_TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{9}Z$")


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


# --- Virtual (ltfs.*) extended attributes ---
#
# LTFS exposes volume/file metadata as read-mostly virtual xattrs in the
# ltfs.* namespace (user.ltfs.* through the Linux FUSE bridge). They are
# computed on the fly, never stored in the dentry xattr list.


def test_virtual_root_xattrs_values(mounted_tape):
    # The mounted_tape fixture formats with serial=TEST00, label=test.
    assert get_xattr(mounted_tape, "ltfs.volumeName") == "test"
    assert get_xattr(mounted_tape, "ltfs.volumeSerial") == "TEST00"
    assert get_xattr(mounted_tape, "ltfs.softwareVendor") == "Aurora"
    assert get_xattr(mounted_tape, "ltfs.volumeBlocksize") == "524288"
    assert get_xattr(mounted_tape, "ltfs.partitionMap") == "I:a,D:b"
    assert get_xattr_int(mounted_tape, "ltfs.indexGeneration") >= 1
    # volumeUUID must parse as a UUID
    uuid.UUID(get_xattr(mounted_tape, "ltfs.volumeUUID"))
    assert re.match(r"^[ab]:\d+$", get_xattr(mounted_tape, "ltfs.indexLocation"))
    assert _LTFS_TIME_RE.match(get_xattr(mounted_tape, "ltfs.volumeFormatTime"))
    assert _LTFS_TIME_RE.match(get_xattr(mounted_tape, "ltfs.indexTime"))
    # The file backend does not report the media encryption status through
    # get_parameters(), so the tri-state in device_data stays at 0 (unknown).
    assert get_xattr(mounted_tape, "ltfs.mediaEncrypted") == "unknown"
    # Likewise the cached decryption state stays at 0 (unknown), so the value
    # comes from the MP 0x25 fallback, whose CRYPTO CONTROL bits read 0 (off).
    assert get_xattr(mounted_tape, "ltfs.driveEncryptionState") == "off"


def test_virtual_file_xattrs_values(mounted_tape):
    p = mounted_tape / "vx_file.txt"
    p.write_text("payload")
    assert get_xattr_int(p, "ltfs.fileUID") > 0
    for name in ("ltfs.createTime", "ltfs.modifyTime", "ltfs.accessTime",
                 "ltfs.changeTime", "ltfs.backupTime"):
        assert _LTFS_TIME_RE.match(get_xattr(p, name)), name
    # Per-file volumeUUID is the volume's UUID
    assert get_xattr(p, "ltfs.volumeUUID") == get_xattr(mounted_tape, "ltfs.volumeUUID")


def test_virtual_data_placement_xattrs(mounted_tape):
    """ltfs.partition / ltfs.startblock appear once the file has extents
    on tape and must point at the data partition."""
    p = mounted_tape / "vx_place.bin"
    p.write_bytes(b"z" * 4096)
    # The xattrs only exist once the extents are on tape; force the
    # scheduler to flush rather than relying on close-time behavior.
    full_sync(mounted_tape)
    assert get_xattr(p, "ltfs.partition") == "b"
    assert get_xattr_int(p, "ltfs.startblock") > 0


def test_virtual_xattrs_hidden_from_listxattr(mounted_tape):
    p = mounted_tape / "vx_list.txt"
    p.write_text("payload")
    set_xattr(p, "test.real", "v")
    names = os.listxattr(p)
    assert _USER_NS + "test.real" in names
    assert not any(n.startswith(_USER_NS + "ltfs.") for n in names)


def test_virtual_xattr_write_protected(mounted_tape):
    p = mounted_tape / "vx_ro.txt"
    p.write_text("payload")
    with pytest.raises(PermissionError):
        os.setxattr(p, _USER_NS + "ltfs.fileUID", b"42")
    with pytest.raises(PermissionError):
        os.setxattr(mounted_tape, _USER_NS + "ltfs.volumeUUID", b"x")
    with pytest.raises(PermissionError):
        os.setxattr(mounted_tape, _USER_NS + "ltfs.indexGeneration", b"9")
    # The whole ltfs.* namespace is reserved: unknown names are rejected too.
    with pytest.raises(PermissionError):
        os.setxattr(p, _USER_NS + "ltfs.notAVirtualXattr", b"x")


def test_virtual_xattr_not_removable(mounted_tape):
    p = mounted_tape / "vx_norm.txt"
    p.write_text("payload")
    with pytest.raises(PermissionError):
        os.removexattr(p, _USER_NS + "ltfs.fileUID")
    with pytest.raises(PermissionError):
        os.removexattr(mounted_tape, _USER_NS + "ltfs.volumeUUID")


def test_virtual_modify_time_is_settable(mounted_tape):
    """ltfs.modifyTime is one of the writable virtual xattrs: setting it
    must round-trip exactly and be reflected in stat() at ns precision."""
    p = mounted_tape / "vx_settime.txt"
    p.write_text("payload")
    stamp = "2020-01-02T03:04:05.123456789Z"
    set_xattr(p, "ltfs.modifyTime", stamp)
    assert get_xattr(p, "ltfs.modifyTime") == stamp
    assert p.stat().st_mtime_ns == 1_577_934_245_123_456_789


def test_volume_name_set_remove_and_persistence(tmp_path_factory):
    """ltfs.volumeName is a writable virtual xattr backed by the index:
    a new value must survive a remount, and removexattr must clear it."""
    base = tmp_path_factory.mktemp("altfs-volname")
    tape = base / "tape"
    mnt = base / "mnt"
    tape.mkdir()
    mnt.mkdir()
    format_tape(tape, serial="VOLNAM", label="before")
    qname = _USER_NS + "ltfs.volumeName"

    mount_tape(tape, mnt)
    try:
        assert os.getxattr(mnt, qname) == b"before"
        os.setxattr(mnt, qname, b"after")
        assert os.getxattr(mnt, qname) == b"after"
    finally:
        umount_tape(mnt)

    # The new name is committed to the on-tape index: the root directory's
    # <name> element carries the volume name.
    root = parse_latest_index(tape)
    assert root.find("directory/name").text == "after"

    mount_tape(tape, mnt)
    try:
        assert os.getxattr(mnt, qname) == b"after"
        os.removexattr(mnt, qname)
        assert os.getxattr(mnt, qname) == b""
    finally:
        umount_tape(mnt)


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
