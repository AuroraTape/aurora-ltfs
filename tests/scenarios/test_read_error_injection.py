"""Read-error injection of the file tape backend (issue #256).

``ltfs.vendor.Aurora.forceErrorRead = N`` lets reads 1..N succeed and
fails the next one. ``forceErrorType`` selects the error it fails with,
the same way for reads as for writes: a permanent error by default
(EDEV_READ_PERM, -20308), no sense (EDEV_NO_SENSE, -20000) with 1.
"""
import errno
import os

import pytest

from common.altfs import (
    format_tape,
    mount_tape,
    mount_tape_foreground,
    umount_tape,
    umount_tape_foreground,
)
from common.helpers import set_xattr

pytestmark = pytest.mark.mount  # every test here goes through a FUSE mount

_VENDOR = "ltfs.vendor.Aurora."
_SIZE = 3 * 1024 * 1024  # several 512 KiB blocks


@pytest.mark.parametrize("error_type, code", [(None, -20308), (1, -20000)],
                         ids=["default-read-perm", "type1-no-sense"])
def test_injected_read_error_code(tmp_path, error_type, code):
    tape_dir = tmp_path / "tape"
    mnt = tmp_path / "mnt"
    tape_dir.mkdir()
    mnt.mkdir()
    format_tape(tape_dir, serial="RDERR0", label="rderr")

    # Write the file in one session, read it back from the tape in the next
    mount_tape(tape_dir, mnt)
    (mnt / "f").write_bytes(os.urandom(_SIZE))
    umount_tape(mnt)

    proc = mount_tape_foreground(tape_dir, mnt)
    try:
        if error_type is not None:
            set_xattr(mnt, _VENDOR + "forceErrorType", str(error_type))
        set_xattr(mnt, _VENDOR + "forceErrorRead", "1")
        with pytest.raises(OSError) as exc:
            (mnt / "f").read_bytes()
        assert exc.value.errno == errno.EIO
    finally:
        assert umount_tape_foreground(proc, mnt) == 0

    log = (tmp_path / "altfs-foreground.log").read_text(errors="replace")
    assert "ATF0008E" in log
    assert f"ALP0055E Cannot read: backend call failed ({code})" in log, log
