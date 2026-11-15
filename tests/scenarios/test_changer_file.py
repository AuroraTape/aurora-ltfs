"""The file medium changer plugin (libchanger-file) driven through altfschanger.

The plugin emulates an SMC medium changer on a directory (see
tests/common/changer.py for the layout). These tests check what the
changer layer will rely on: the element status it reports, MOVE and
EXCHANGE MEDIUM with their SMC errors, the source address a device
remembers, the faults a test can inject, and that a drive file the
changer rewrites is followed by the tape file backend without any
change on its side.
"""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.changer import (  # noqa: E402
    DRIVE_LINK_SIZE, DRIVE_START, IE_START, STORAGE_START, FileLibrary, error_code,
)
from common.altfs import format_tape, mount_tape, umount_tape  # noqa: E402

# EDEV_* values of libaltfs (src/libltfs/ltfs_error.h)
EDEV_DOOR_OPEN = -20207
EDEV_DEST_FULL = -20502
EDEV_SRC_EMPTY = -20503
EDEV_MAGAZINE_INACCESSIBLE = -20504
EDEV_INVALID_ADDRESS = -20505
EDEV_ELEMENT_DISABLED = -20507
EDEV_DT_ELEMENT_REMOVED = -20508
EDEV_MEDIUM_MAY_BE_CHANGED = -20601
EDEV_CONNECTION_LOST = -21720
EDEV_UNSUPPORTED_FUNCTION = -21705

DRIVE = DRIVE_START
IE = IE_START
S0, S1, S2, S3 = (STORAGE_START + i for i in range(4))


@pytest.fixture
def lib(tmp_path):
    return FileLibrary(tmp_path / "lib",
                       cartridges={S0: "AAA001L5", S1: "AAA002L5", S3: "nolabel-0"})


# ---------- identity and element status ----------


def test_info_reports_address_assignment(lib):
    info = lib.info()
    assert info["vendor"] == "AURORA"
    assert info["serial"] == "FLIB0001"
    assert info["transport"] == "1 1"
    assert info["storage"] == f"{STORAGE_START} 4"
    assert info["ie"] == f"{IE_START} 1"
    assert info["drive"] == f"{DRIVE_START} 1"
    assert info["barcode_reader"] == "yes"
    assert info["exchange"] == "yes"


def test_elements_report_every_type(lib):
    e = lib.elements()
    assert e[1]["type"] == "transport"
    assert e[DRIVE]["type"] == "drive" and not e[DRIVE]["full"]
    assert e[DRIVE]["dvcid"] == "1234567890"
    assert e[IE]["type"] == "ie" and not e[IE]["full"]
    assert e[S0] == {**e[S0], "type": "storage", "full": True, "voltag": "AAA001L5"}
    assert e[S1]["voltag"] == "AAA002L5"
    assert not e[S2]["full"]


def test_unlabeled_cartridge_is_full_without_voltag(lib):
    e = lib.elements()
    assert e[S3]["full"] and e[S3]["voltag"] is None


def test_elements_filter_by_type_and_range(lib):
    assert set(lib.elements("storage")) == {S0, S1, S2, S3}
    assert set(lib.elements("drive")) == {DRIVE}
    assert set(lib.elements("storage", S1, 2)) == {S1, S2}
    assert set(lib.elements("any", S3, 1)) == {S3}


def test_barcode_reader_off_hides_every_voltag(lib):
    lib.set_conf("barcode_reader", "false")
    e = lib.elements()
    assert e[S0]["full"] and e[S0]["voltag"] is None
    assert lib.info()["barcode_reader"] == "no"


def test_dvcid_off_hides_the_drive_serial(lib):
    lib.set_conf("dvcid", "false")
    assert lib.elements()[DRIVE]["dvcid"] is None


# ---------- MOVE MEDIUM ----------


def test_move_to_drive_records_source_and_writes_the_drive_file(lib):
    lib.run("move", S0, DRIVE, check=True)
    e = lib.elements()
    assert not e[S0]["full"]
    assert e[DRIVE]["full"] and e[DRIVE]["voltag"] == "AAA001L5"
    assert e[DRIVE]["source"] == S0
    raw = lib.drive_files[0].read_bytes()
    assert len(raw) == DRIVE_LINK_SIZE
    assert raw.rstrip(b"\0") == b"../cartridges/AAA001L5"
    assert lib.state()[f"source.{DRIVE}"] == str(S0)


def test_move_back_to_storage_forgets_the_source(lib):
    lib.run("move", S0, DRIVE, check=True)
    lib.run("move", DRIVE, S2, check=True)
    e = lib.elements()
    assert e[S2]["voltag"] == "AAA001L5" and e[S2]["source"] is None
    assert not e[DRIVE]["full"]
    assert lib.drive_files[0].read_bytes().rstrip(b"\0") == b"empty"
    assert f"source.{DRIVE}" not in lib.state()


def test_move_to_ie_keeps_the_storage_source(lib):
    lib.run("move", S0, DRIVE, check=True)
    lib.run("move", DRIVE, IE, check=True)
    assert lib.elements()[IE]["source"] == S0


def test_move_errors_use_the_smc_sense_codes(lib):
    assert error_code(lib.run("move", S2, S0)) == EDEV_SRC_EMPTY
    assert error_code(lib.run("move", S0, S1)) == EDEV_DEST_FULL
    assert error_code(lib.run("move", S0, 9999)) == EDEV_INVALID_ADDRESS
    assert error_code(lib.run("move", S0, 1)) == EDEV_INVALID_ADDRESS
    # nothing moved
    e = lib.elements()
    assert e[S0]["voltag"] == "AAA001L5" and e[S1]["voltag"] == "AAA002L5"


def test_move_sees_a_cartridge_placed_from_the_panel(lib):
    lib.put(S2, "BBB001L5")
    assert lib.elements()[S2]["voltag"] == "BBB001L5"
    assert error_code(lib.run("move", S0, S2)) == EDEV_DEST_FULL


# ---------- EXCHANGE MEDIUM ----------


def test_exchange_swaps_the_drive_in_one_command(lib):
    lib.run("move", S0, DRIVE, check=True)
    lib.run("exchange", S1, DRIVE, S2, check=True)
    e = lib.elements()
    assert e[DRIVE]["voltag"] == "AAA002L5" and e[DRIVE]["source"] == S1
    assert e[S2]["voltag"] == "AAA001L5"
    assert not e[S0]["full"] and not e[S1]["full"]
    assert lib.content(DRIVE) == "AAA002L5"


def test_exchange_back_into_the_source_slot(lib):
    lib.run("move", S0, DRIVE, check=True)
    lib.run("exchange", S1, DRIVE, S1, check=True)
    e = lib.elements()
    assert e[DRIVE]["voltag"] == "AAA002L5"
    assert e[S1]["voltag"] == "AAA001L5"


def test_exchange_is_refused_when_the_device_lacks_it(lib):
    lib.set_conf("exchange", "false")
    assert lib.info()["exchange"] == "no"
    lib.run("move", S0, DRIVE, check=True)
    assert error_code(lib.run("exchange", S1, DRIVE, S2)) == EDEV_UNSUPPORTED_FUNCTION
    e = lib.elements()
    assert e[DRIVE]["voltag"] == "AAA001L5" and e[S1]["voltag"] == "AAA002L5"


# ---------- faults ----------


def test_injected_unit_attention_fails_one_command_only(lib):
    lib.inject("ua 06/2800")
    assert error_code(lib.run("tur")) == EDEV_MEDIUM_MAY_BE_CHANGED
    assert lib.run("tur").returncode == 0
    assert lib.pending_injections() == []


def test_injected_move_failure_leaves_the_cartridge_in_place(lib):
    lib.inject("fail move 05/3B0D")
    assert error_code(lib.run("move", S0, S2)) == EDEV_DEST_FULL
    e = lib.elements()
    assert e[S0]["voltag"] == "AAA001L5" and not e[S2]["full"]
    lib.run("move", S0, S2, check=True)


def test_lost_connection_after_the_move_executed(lib):
    lib.inject("lost move_after")
    assert error_code(lib.run("move", S0, DRIVE)) == EDEV_CONNECTION_LOST
    # the device did move it: the layer has to look instead of repeating
    assert lib.elements()[DRIVE]["voltag"] == "AAA001L5"


def test_lost_connection_before_the_move(lib):
    lib.inject("lost move")
    assert error_code(lib.run("move", S0, DRIVE)) == EDEV_CONNECTION_LOST
    assert lib.elements()[S0]["voltag"] == "AAA001L5"


def test_door_open_makes_the_library_not_ready(lib):
    lib.inject("door_open 3600")
    assert error_code(lib.run("tur")) == EDEV_DOOR_OPEN
    assert error_code(lib.run("move", S0, DRIVE)) == EDEV_DOOR_OPEN
    assert error_code(lib.run("elements")) == EDEV_DOOR_OPEN
    # info does not touch the device
    assert lib.info()["serial"] == "FLIB0001"
    # closing the door
    (lib.dir / "state.conf").write_text("")
    assert lib.run("tur").returncode == 0


def test_scan_and_prevent_allow(lib):
    assert lib.run("scan").returncode == 0
    assert lib.run("scan", S0, 2).returncode == 0
    assert lib.run("prevent").returncode == 0
    assert lib.state()["ie_locked"] == "1"
    assert lib.run("allow").returncode == 0
    assert lib.state()["ie_locked"] == "0"
    lib.set_conf("prevent_supported", "false")
    assert error_code(lib.run("prevent")) == EDEV_UNSUPPORTED_FUNCTION


# ---------- device list and names ----------


def test_device_list_and_open_by_serial(tmp_path, lib):
    env = {"ALTFS_FILE_CHANGER_ROOT": str(lib.dir.parent)}
    proc = lib.run("list", env=env, device=False, check=True)
    assert proc.stdout.split() == [str(lib.dir), "AURORA", "FILECHANGER", "FLIB0001"]
    proc = subprocess.run(["altfschanger", "-e", "file", "-d", "FLIB0001", "info"],
                          capture_output=True, text=True, timeout=30,
                          env={**dict(__import__("os").environ), **env})
    assert proc.returncode == 0 and "serial FLIB0001" in proc.stdout


def test_a_plain_directory_is_not_a_library(tmp_path):
    proc = subprocess.run(["altfschanger", "-e", "file", "-d", str(tmp_path), "info"],
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode != 0
    assert "ACF0002E" in proc.stderr


def test_usage_and_version():
    assert subprocess.run(["altfschanger", "-V"], capture_output=True, text=True,
                          timeout=10).returncode == 0
    proc = subprocess.run(["altfschanger", "-h"], capture_output=True, text=True, timeout=10)
    assert proc.returncode == 0 and "elements" in proc.stdout + proc.stderr
    proc = subprocess.run(["altfschanger", "-e", "file", "bogus"], capture_output=True,
                          text=True, timeout=10)
    assert proc.returncode == 16


# ---------- lasting element faults (the faults file) ----------


def test_inaccessible_slot_is_reported_and_refused(lib):
    lib.fault(S2, "inaccessible")
    assert "inaccessible" in lib.elements()[S2]["flags"]
    assert error_code(lib.run("move", S0, S2)) == EDEV_MAGAZINE_INACCESSIBLE
    assert lib.content(S0) == "AAA001L5"


def test_disabled_slot_shows_the_exception_and_refuses_moves(lib):
    lib.fault(S0, "3B18")
    e = lib.elements()[S0]
    assert e["full"] and e["except"] == "3B/18"
    assert error_code(lib.run("move", S0, S2)) == EDEV_ELEMENT_DISABLED
    assert error_code(lib.run("exchange", S1, S0, S2)) == EDEV_ELEMENT_DISABLED
    assert lib.content(S0) == "AAA001L5" and lib.content(S1) == "AAA002L5"


def test_removed_drive_refuses_a_load(lib):
    lib.fault(DRIVE, "3B1A")
    assert lib.elements()[DRIVE]["except"] == "3B/1A"
    assert error_code(lib.run("move", S0, DRIVE)) == EDEV_DT_ELEMENT_REMOVED
    assert lib.content(DRIVE) is None


# ---------- the tape file backend follows the drive file ----------


@pytest.mark.mount
def test_tape_backend_follows_the_drive_file(tmp_path, lib):
    format_tape(lib.cartridge_dir("AAA001L5"), serial="AAA001", label="vol1")
    format_tape(lib.cartridge_dir("AAA002L5"), serial="AAA002", label="vol2")
    drive_file = lib.drive_files[0]
    mnt = tmp_path / "mnt"
    mnt.mkdir()

    lib.run("move", S0, DRIVE, check=True)
    mount_tape(drive_file, mnt)
    try:
        (mnt / "hello.txt").write_text("hello\n")
        assert sorted(p.name for p in mnt.iterdir()) == ["hello.txt"]
    finally:
        umount_tape(mnt)

    # swap the cartridge in the drive: the same drive file now serves vol2
    lib.run("exchange", S1, DRIVE, S2, check=True)
    mount_tape(drive_file, mnt)
    try:
        assert list(mnt.iterdir()) == []
    finally:
        umount_tape(mnt)

    # the data went to the first cartridge
    lib.run("exchange", S2, DRIVE, S1, check=True)
    mount_tape(drive_file, mnt)
    try:
        assert (mnt / "hello.txt").read_text() == "hello\n"
    finally:
        umount_tape(mnt)

    # an empty drive has no medium
    lib.run("move", DRIVE, S0, check=True)
    proc = subprocess.run(["altfs", "-f", "-o", "tape_backend=file",
                           "-o", f"devname={drive_file}", str(mnt)],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode != 0
    assert "ALP0022E" in proc.stderr
