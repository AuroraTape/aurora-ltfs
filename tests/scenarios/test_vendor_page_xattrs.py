"""The logPage and mediaMAM vendor xattrs reach the tape backend (#196).

ltfs.vendor.<vendor>.logPage.<page>.<subpage> and
ltfs.vendor.<vendor>.mediaMAM.<partition> carry their arguments in the
name. They used to be read from fixed positions that only fit the vendor
name "IBM", so every request failed with "no such attribute" before the
backend was asked. On the file backend a request that reaches it still
fails, with another error: LOG SENSE is not implemented, and READ
ATTRIBUTE finds no attribute 0. A malformed argument must stay "no such
attribute".
"""
import errno

import pytest

from common.altfs import format_tape, mount_tape, umount_tape
from common.helpers import get_xattr_bytes

_PREFIX = "ltfs.vendor.Aurora."
# ENOATTR on macOS and the BSDs
_NO_ATTR = getattr(errno, "ENOATTR", errno.ENODATA)


@pytest.fixture(scope="module")
def mnt(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("vendorpage")
    tape = tmp / "tape"
    mnt = tmp / "mnt"
    tape.mkdir()
    mnt.mkdir()
    format_tape(tape)
    mount_tape(tape, mnt)
    yield mnt
    umount_tape(mnt)


def _errno(mnt, name):
    """The errno of reading the xattr, None when it succeeds."""
    try:
        get_xattr_bytes(mnt, _PREFIX + name)
    except OSError as e:
        return e.errno
    return None


@pytest.mark.parametrize("name", [
    "logPage.00.00",
    "logPage.17.00",
    "mediaMAM.IP",
    "mediaMAM.DP",
    "mediaMAM.00",
    "mediaMAM.01",
])
def test_request_reaches_the_backend(mnt, name):
    assert _errno(mnt, name) != _NO_ATTR


@pytest.mark.parametrize("name", [
    "logPage.0g.00",   # not hexadecimal
    "logPage.00.0g",
    "logPage.00.000",  # wrong length
    "logPage.+1.00",   # strtoul() would take a sign or white space
    "logPage. 1.00",
    "logPage.00x00",   # no separator
    "mediaMAM.+1",
    "mediaMAM.02",     # no such partition
    "mediaMAM.XY",
])
def test_malformed_argument_is_no_such_attribute(mnt, name):
    assert _errno(mnt, name) == _NO_ATTR
