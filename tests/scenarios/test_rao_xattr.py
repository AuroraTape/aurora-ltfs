"""Setting ltfs.vendor.<vendor>.rao to the path of a GRAO parameter list
(#197).

altfs reads the list from the host file, sends it to the drive and
writes the answer to "<path>.out". The file backend has no GRAO, so a
list that is read completely fails at the backend. A list longer than
the request buffer used to be sent with no data at all; it must fail
before the drive is asked.

The other half of #197, the request buffers that were never freed, is
not visible from here; it was checked by the growth of the altfs
process over many requests.
"""
import errno

import pytest

from common.altfs import format_tape, mount_tape, umount_tape
from common.helpers import set_xattr

_RAO = "ltfs.vendor.Aurora.rao"
# RAO_MAX_RET_SIZE in src/libltfs/ltfs.h is below 100 KiB
_TOO_LONG = 1024 * 1024


@pytest.fixture
def mnt(tmp_path):
    tape = tmp_path / "tape"
    mnt = tmp_path / "mnt"
    tape.mkdir()
    mnt.mkdir()
    format_tape(tape)
    mount_tape(tape, mnt)
    yield mnt
    umount_tape(mnt)


def _errno(mnt, path):
    with pytest.raises(OSError) as e:
        set_xattr(mnt, _RAO, str(path))
    return e.value.errno


def test_missing_list(mnt, tmp_path):
    assert _errno(mnt, tmp_path / "no-such-list") == errno.ENOENT


def test_list_reaches_the_backend(mnt, tmp_path):
    rao_list = tmp_path / "rao-list"
    rao_list.write_bytes(bytes(64))
    assert _errno(mnt, rao_list) == errno.ENOTSUP
    assert not (tmp_path / "rao-list.out").exists()


def test_list_longer_than_the_buffer_is_refused(mnt, tmp_path):
    rao_list = tmp_path / "rao-list"
    rao_list.write_bytes(bytes(_TOO_LONG))
    assert _errno(mnt, rao_list) == errno.EIO
    assert not (tmp_path / "rao-list.out").exists()
