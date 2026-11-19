"""Index cache (-o index_cache_dir=<dir>): a copy of the last index on disk that the volume is
mounted from when the cartridge was not written since the copy was made.

The copy is <dir>/<BARCODE>.index.xml. Its extended attributes say what it is worth:
``user.altfs.volume_uuid`` and ``user.altfs.vcr`` (the Volume Change Reference of the
cartridge right after the index was written). A copy without the VCR is never mounted from.

The log line ALB0289I tells that a mount read the index from the copy, ALB0290I that it had
a copy but read the tape, and why.
"""

import os
import subprocess

import pytest

from common.altfs import format_tape, run_altfsck, umount_tape, _mount_args, _wait_until
from common.helpers import full_sync, incremental_sync, set_xattr

pytestmark = pytest.mark.mount

_SERIAL = "IDXC01"
_UUID = "user.altfs.volume_uuid"
_VCR = "user.altfs.vcr"


class Lib:
    def __init__(self, base):
        self.tape, self.mnt, self.cache = base / "tape", base / "mnt", base / "cache"
        for d in (self.tape, self.mnt):
            d.mkdir()
        format_tape(self.tape, serial=_SERIAL, label="cache")
        self.copy = self.cache / f"{_SERIAL}.index.xml"

    def mount(self, cached=True, sync_type="unmount"):
        """Mount in the background; returns what altfs logged until it daemonized."""
        opts = (f"index_cache_dir={self.cache}",) if cached else ()
        r = subprocess.run(["altfs"] + _mount_args(self.tape, self.mnt, sync_type, opts),
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr[-2000:]
        assert _wait_until(lambda: os.path.ismount(self.mnt))
        return r.stderr

    def umount(self):
        umount_tape(self.mnt)

    def eas(self):
        return {a: os.getxattr(self.copy, a).decode() for a in os.listxattr(self.copy)}


@pytest.fixture
def lib(tmp_path):
    try:
        probe = tmp_path / "probe"
        probe.write_text("")
        os.setxattr(probe, "user.altfs.probe", b"1")
    except OSError:
        pytest.skip("the file system of the test directory has no user extended attributes")
    lib = Lib(tmp_path)
    yield lib
    # A test that fails half way must not leave its daemon behind
    if os.path.ismount(lib.mnt):
        subprocess.run(["fusermount", "-u", "-z", str(lib.mnt)])


def test_copy_is_written_with_the_index_and_used_by_the_next_mount(lib):
    log = lib.mount()
    assert "ALB0289I" not in log
    (lib.mnt / "a.txt").write_text("first")
    lib.umount()

    eas = lib.eas()
    assert set(eas) == {_UUID, _VCR}
    assert "a.txt" in lib.copy.read_text()

    log = lib.mount()
    assert "ALB0289I" in log
    assert (lib.mnt / "a.txt").read_text() == "first"
    (lib.mnt / "b.txt").write_text("second")
    lib.umount()
    assert lib.eas()[_UUID] == eas[_UUID]
    assert lib.eas()[_VCR] != eas[_VCR]

    log = lib.mount()
    assert "ALB0289I" in log
    assert sorted(p.name for p in lib.mnt.iterdir()) == ["a.txt", "b.txt"]
    assert (lib.mnt / "b.txt").read_text() == "second"
    lib.umount()
    assert run_altfsck(tape_dir=lib.tape).returncode in (0, 1)


def test_copy_is_not_used_after_the_tape_was_written_without_it(lib):
    lib.mount()
    (lib.mnt / "a.txt").write_text("first")
    lib.umount()

    lib.mount(cached=False)
    (lib.mnt / "elsewhere.txt").write_text("written without the cache")
    lib.umount()

    log = lib.mount()
    assert "ALB0289I" not in log and "ALB0290I" in log
    assert (lib.mnt / "elsewhere.txt").read_text() == "written without the cache"
    lib.umount()

    # Reading the tape refreshed the copy: the mount after a mount that wrote nothing uses it
    log = lib.mount()
    assert "ALB0289I" in log
    assert (lib.mnt / "elsewhere.txt").read_text() == "written without the cache"
    lib.umount()


def test_copy_of_another_volume_with_the_same_barcode_is_not_used(lib):
    lib.mount()
    (lib.mnt / "old.txt").write_text("old volume")
    lib.umount()
    old = lib.eas()

    format_tape(lib.tape, serial=_SERIAL, label="again")
    # Even with the VCR of the new cartridge state, the UUID gives the old copy away
    for vcr in range(1, 40):
        os.setxattr(lib.copy, _VCR, str(vcr).encode())
        log = lib.mount()
        assert "ALB0289I" not in log
        assert list(lib.mnt.iterdir()) == []
        lib.umount()
        if lib.eas()[_UUID] != old[_UUID]:
            break   # the mount refreshed the copy for the new volume
        os.setxattr(lib.copy, _UUID, old[_UUID].encode())
    assert lib.eas()[_UUID] != old[_UUID]


def test_tampered_copy_falls_back_to_the_tape(lib):
    lib.mount()
    (lib.mnt / "a.txt").write_text("first")
    lib.umount()

    eas = lib.eas()
    lib.copy.write_text("<ltfsindex>not an index")
    for name, value in eas.items():
        os.setxattr(lib.copy, name, value.encode())

    log = lib.mount()
    assert "ALB0289I" not in log and "ALB0290I" in log
    assert (lib.mnt / "a.txt").read_text() == "first"
    lib.umount()


def test_incremental_index_leaves_no_usable_copy(lib):
    lib.mount()
    (lib.mnt / "a.txt").write_text("first")
    full_sync(lib.mnt)
    assert _wait_until(lambda: lib.copy.exists() and _VCR in lib.eas())
    (lib.mnt / "b.txt").write_text("second")
    incremental_sync(lib.mnt)
    # The copy is the last full index, and the tape has moved on
    assert _VCR not in lib.eas()
    assert "b.txt" not in lib.copy.read_text()
    lib.umount()
    assert _VCR in lib.eas()
    assert "b.txt" in lib.copy.read_text()


def _mount_and_add(lib, name):
    lib.mount()
    (lib.mnt / "kept.txt").write_text("on tape")
    lib.umount()
    assert _VCR in lib.eas()
    lib.mount()
    (lib.mnt / name).write_text("added")


def test_copy_is_not_used_after_a_failed_index_write(lib):
    _mount_and_add(lib, "added.txt")
    # The index reaches the data partition; its write to the index partition fails, without
    # a write perm. The unmount fails, and the tape is left for the next mount to sort out.
    set_xattr(lib.mnt, "ltfs.vendor.Aurora.forceErrorType", "1")
    set_xattr(lib.mnt, "ltfs.vendor.Aurora.forceErrorWrite", "1")
    lib.umount()
    assert _VCR not in lib.eas()

    # The next mount reads the tape, writes the index where it is missing, and the copy is
    # the index of the cartridge again
    log = lib.mount()
    assert "ALB0289I" not in log
    assert sorted(os.listdir(lib.mnt)) == ["added.txt", "kept.txt"]
    lib.umount()
    assert _VCR in lib.eas()
    assert "ALB0289I" in lib.mount()
    lib.umount()


def test_copy_is_not_used_after_a_write_perm(lib):
    _mount_and_add(lib, "first.txt")
    lib.umount()
    lib.mount()
    # The write to the data partition is accepted and lost, the index after it gets a write
    # perm there, and the index goes to the index partition instead
    set_xattr(lib.mnt, "ltfs.vendor.Aurora.forceErrorWrite", "-1")
    (lib.mnt / "late.txt").write_text("late")
    lib.umount()
    assert _VCR not in lib.eas()

    # The cartridge is read-only from here; its mounts read the index from the tape
    log = lib.mount()
    assert "ALB0289I" not in log
    assert (lib.mnt / "kept.txt").read_text() == "on tape"
    lib.umount()
    assert _VCR not in lib.eas()


def test_index_cache_dir_and_capture_index_are_refused_together(lib, tmp_path):
    r = subprocess.run(["altfs"] + _mount_args(lib.tape, lib.mnt, "unmount",
                                               (f"index_cache_dir={lib.cache}", f"capture_index={tmp_path / 'cap'}")),
                       capture_output=True, text=True)
    assert r.returncode != 0 and "AFS0162E" in r.stderr
    assert not os.path.ismount(lib.mnt)
