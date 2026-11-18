"""The medium changer layer (libaltfschanger) driven through altfschanger's
barcode and drive serial commands, on the file medium changer.

Every command opens the layer, takes an inventory, acts and prints the
inventory afterwards, so each test is one or a few command lines. The
operator's panel (direct writes to the library directory, see
common.changer.FileLibrary) and the inject / faults files make the library
change behind the layer's back.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.changer import (  # noqa: E402
    DRIVE_START, IE_START, STORAGE_START, FileLibrary, error_code,
)

# LTFS_* and EDEV_* values of libaltfs (src/libltfs/ltfs_error.h)
LTFS_BARCODE_NOT_FOUND = -6000
LTFS_BARCODE_AMBIGUOUS = -6001
LTFS_DRIVE_NOT_IN_LIBRARY = -6002
LTFS_DRIVE_OCCUPIED = -6003
LTFS_DRIVE_EMPTY = -6004
LTFS_NO_FREE_SLOT = -6007
LTFS_INVENTORY_STALE = -6008
LTFS_CLEANING_CARTRIDGE = -6010
LTFS_TAPE_IN_IE = -6012
LTFS_IE_NOT_ACCESSIBLE = -6013
LTFS_CHANGER_NOT_READY = -6014
LTFS_TAPE_IN_DRIVE = -6015
EDEV_MAGAZINE_INACCESSIBLE = -20504
EDEV_MEDIUM_MAY_BE_CHANGED = 20601

D1, D2 = DRIVE_START, DRIVE_START + 1
IE0, IE1 = IE_START, IE_START + 1
S0, S1, S2, S3, S4, S5 = (STORAGE_START + i for i in range(6))
DRV1, DRV2 = "DRV001", "DRV002"
FAST = ["--move-wait=1", "--ready-wait=1"]


def parse_inventory(stdout):
    """{'library': {...}, 'drives': {serial: {...}}, 'tapes': {barcode: {...}}}"""
    out = {"library": {}, "drives": {}, "tapes": {}}
    for line in stdout.splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "library":
            out["library"] = dict(p.split("=", 1) for p in parts[4:])
            out["library"].update(vendor=parts[1], model=parts[2], serial=parts[3])
        elif parts[0] == "drive":
            d = {"address": int(parts[2]), "full": parts[3] == "full",
                 "barcode": parts[4] if parts[3] == "full" else None, "flags": parts[5:] if parts[3] == "full" else parts[4:]}
            out["drives"][parts[1] if parts[1] != "-" else int(parts[2])] = d
        elif parts[0] == "tape":
            t = {"where": parts[2], "address": int(parts[3]), "state": parts[4]}
            for p in parts[5:]:
                k, _, v = p.partition("=")
                t[k] = int(v) if k == "home" else v
            out["tapes"][parts[1]] = t
    return out


class Layer:
    """altfschanger on a FileLibrary, through the changer layer."""

    def __init__(self, lib):
        self.lib = lib

    def run(self, *args, check=False):
        return self.lib.run(*FAST, *args, check=check)

    def inventory(self):
        return parse_inventory(self.run("inventory", check=True).stdout)

    def ok(self, *args):
        """Run a command that must succeed and return the inventory it printed."""
        return parse_inventory(self.run(*args, check=True).stdout)

    def fails(self, *args):
        """Run a command that must fail and return its error code."""
        proc = self.run(*args)
        assert proc.returncode == 8, proc.stderr
        return error_code(proc)


@pytest.fixture
def lib(tmp_path):
    return FileLibrary(tmp_path / "lib", slots=6, ie=2,
                       drives=(f"{DRV1}.ULTRIUM-TD9", f"{DRV2}.ULTRIUM-TD8"),
                       cartridges={S0: "AAA001L9", S1: "AAA002L8", S2: "CLN001L9"})


@pytest.fixture
def layer(lib):
    return Layer(lib)


# ---------- inventory ----------


def test_inventory_lists_tapes_drives_and_counts(layer):
    inv = layer.inventory()
    assert inv["library"]["serial"] == "FLIB0001"
    assert inv["library"]["ready"] == "yes" and inv["library"]["stale"] == "no"
    assert inv["library"]["tapes"] == "3" and inv["library"]["drives"] == "2"
    assert inv["library"]["storage_free"] == "3" and inv["library"]["ie_free"] == "2"
    assert inv["drives"][DRV1] == {"address": D1, "full": False, "barcode": None, "flags": []}
    assert inv["tapes"]["AAA001L9"] == {"where": "storage", "address": S0, "state": "available", "home": 0}
    assert inv["tapes"]["CLN001L9"]["state"] == "cleaning"


def test_unlabeled_cartridges_are_numbered_by_address(layer, lib):
    lib.put(S4, "second-nolabel")
    lib.put(S3, "first-nolabel")
    inv = layer.inventory()
    assert inv["library"]["unlabeled"] == "2"
    assert inv["tapes"]["unlabeled0"]["address"] == S3
    assert inv["tapes"]["unlabeled1"]["address"] == S4


def test_duplicate_barcodes_are_marked_and_refused(layer, lib):
    lib.put(S3, "AAA001L9")
    inv = layer.inventory()
    assert inv["library"]["tapes"] == "4"
    assert inv["tapes"]["AAA001L9"]["state"] == "duplicate"
    assert layer.fails("load", "AAA001L9", DRV1) == LTFS_BARCODE_AMBIGUOUS


def test_without_a_barcode_reader_everything_is_unlabeled(layer, lib):
    lib.set_conf("barcode_reader", "false")
    inv = layer.inventory()
    assert inv["library"]["unlabeled"] == "3"
    assert layer.fails("load", "AAA001L9", DRV1) == LTFS_BARCODE_NOT_FOUND


# ---------- load and return ----------


def test_load_moves_the_cartridge_and_records_its_home(layer, lib):
    inv = layer.ok("load", "AAA001L9", DRV1)
    assert inv["drives"][DRV1]["barcode"] == "AAA001L9"
    assert inv["tapes"]["AAA001L9"] == {"where": "drive", "address": D1, "state": "loaded", "home": S0}
    assert lib.content(D1) == "AAA001L9" and lib.content(S0) is None
    assert inv["library"]["storage_free"] == "4"


def test_load_is_idempotent_and_refuses_the_wrong_drive(layer):
    layer.ok("load", "AAA001L9", DRV1)
    layer.ok("load", "AAA001L9", DRV1)
    assert layer.fails("load", "AAA001L9", DRV2) == LTFS_TAPE_IN_DRIVE
    assert layer.fails("load", "AAA002L8", DRV1) == LTFS_DRIVE_OCCUPIED


def test_load_refuses_what_cannot_be_loaded(layer):
    assert layer.fails("load", "CLN001L9", DRV1) == LTFS_CLEANING_CARTRIDGE
    assert layer.fails("load", "ZZZ999L9", DRV1) == LTFS_BARCODE_NOT_FOUND
    assert layer.fails("load", "AAA001L9", "NOSUCH") == LTFS_DRIVE_NOT_IN_LIBRARY


def test_drive_can_be_named_by_address_when_it_has_no_serial(layer, lib):
    lib.set_conf("dvcid", "false")
    inv = layer.ok("load", "AAA001L9", str(D1))
    assert inv["drives"][D1]["barcode"] == "AAA001L9"


def test_return_goes_to_the_home_slot(layer, lib):
    layer.ok("load", "AAA001L9", DRV1)
    inv = layer.ok("return", DRV1)
    assert inv["tapes"]["AAA001L9"] == {"where": "storage", "address": S0, "state": "available", "home": 0}
    assert lib.content(S0) == "AAA001L9"
    assert layer.fails("return", DRV1) == LTFS_DRIVE_EMPTY


def test_return_uses_the_source_the_device_remembers(layer, lib):
    # Loaded outside the layer: no home in its tables, but the plugin recorded the source
    lib.run("move", S1, D2, check=True)
    inv = layer.ok("return", DRV2)
    assert inv["tapes"]["AAA002L8"]["address"] == S1


def test_return_picks_a_free_slot_when_home_is_taken(layer, lib):
    layer.ok("load", "AAA001L9", DRV1)
    lib.put(S0, "NEW001L9")           # the operator fills the home slot meanwhile
    proc = layer.run("return", DRV1, check=True)
    assert "ACL0014W" in proc.stderr
    inv = parse_inventory(proc.stdout)
    assert inv["tapes"]["AAA001L9"]["where"] == "storage"
    assert inv["tapes"]["AAA001L9"]["address"] not in (S0, S1, S2)
    assert inv["tapes"]["NEW001L9"]["address"] == S0


def test_return_picks_a_free_slot_without_any_home(layer, lib):
    lib.put(D1, "AAA003L9")           # appeared in the drive, nobody knows from where
    proc = layer.run("return", DRV1, check=True)
    assert "ACL0020W" in proc.stderr
    inv = parse_inventory(proc.stdout)
    assert inv["tapes"]["AAA003L9"]["where"] == "storage"
    assert lib.content(inv["tapes"]["AAA003L9"]["address"]) == "AAA003L9"
    assert lib.content(D1) is None


# ---------- swap ----------


def test_swap_with_exchange_medium(layer, lib):
    layer.ok("load", "AAA001L9", DRV1)
    proc = layer.run("swap", "AAA002L8", DRV1, check=True)
    assert "ACL0015I" not in proc.stderr
    inv = parse_inventory(proc.stdout)
    assert inv["drives"][DRV1]["barcode"] == "AAA002L8"
    assert inv["tapes"]["AAA001L9"]["address"] == S0
    assert inv["tapes"]["AAA002L8"]["home"] == S1


def test_swap_uses_two_moves_when_the_device_has_no_exchange(layer, lib):
    lib.set_conf("exchange", "false")
    layer.ok("load", "AAA001L9", DRV1)
    proc = layer.run("swap", "AAA002L8", DRV1, check=True)
    assert proc.stderr.count("ACL0012I") == 2
    inv = parse_inventory(proc.stdout)
    assert inv["drives"][DRV1]["barcode"] == "AAA002L8"
    assert lib.content(S0) == "AAA001L9" and lib.content(D1) == "AAA002L8"


def test_swap_falls_back_to_two_moves_when_exchange_is_refused(layer, lib):
    layer.ok("load", "AAA001L9", DRV1)
    lib.inject("fail exchange 05/2000")  # invalid operation code: the probe lied
    proc = layer.run("swap", "AAA002L8", DRV1, check=True)
    assert "ACL0015I" in proc.stderr
    inv = parse_inventory(proc.stdout)
    assert inv["drives"][DRV1]["barcode"] == "AAA002L8"
    assert lib.content(S0) == "AAA001L9" and lib.content(D1) == "AAA002L8"


def test_swap_on_an_empty_drive_is_a_load(layer):
    inv = layer.ok("swap", "AAA001L9", DRV1)
    assert inv["drives"][DRV1]["barcode"] == "AAA001L9"


# ---------- import / export ----------


def test_export_and_import(layer, lib):
    inv = layer.ok("export", "AAA001L9")
    assert inv["tapes"]["AAA001L9"]["where"] == "ie" and lib.content(IE0) == "AAA001L9"
    assert layer.fails("load", "AAA001L9", DRV1) == LTFS_TAPE_IN_IE
    inv = layer.ok("import", "AAA001L9")
    assert inv["tapes"]["AAA001L9"]["where"] == "storage"
    assert lib.content(inv["tapes"]["AAA001L9"]["address"]) == "AAA001L9"


def test_export_needs_a_free_usable_ie_element(layer, lib):
    lib.put(IE0, "EXT001L9")
    lib.put(IE1, "EXT002L9")
    assert layer.fails("export", "AAA001L9") == LTFS_NO_FREE_SLOT
    lib.put(IE1, "")
    lib.fault(IE1, "inaccessible")
    lib.fault(IE0, "inaccessible")
    assert layer.fails("export", "AAA001L9") == LTFS_IE_NOT_ACCESSIBLE


def test_import_needs_a_free_storage_slot(layer, lib):
    for addr in (S3, S4, S5):
        lib.put(addr, f"FULL{addr}L9")
    layer.ok("export", "AAA001L9")
    lib.put(S0, "FULL000L9")
    assert layer.fails("import", "AAA001L9") == LTFS_NO_FREE_SLOT


# ---------- the library changes behind the layer's back ----------


def test_faulty_slot_makes_its_cartridge_not_accessible(layer, lib):
    lib.fault(S0, "3B18")
    inv = layer.inventory()
    assert inv["tapes"]["AAA001L9"]["state"] == "not-accessible"
    assert inv["tapes"]["AAA001L9"]["except"] == "3B/18"
    assert inv["library"]["storage_unusable"] == "1"
    assert layer.fails("load", "AAA001L9", DRV1) == EDEV_MAGAZINE_INACCESSIBLE


def test_unit_attention_is_absorbed_and_remembered(layer, lib):
    lib.inject("ua 06/2800")
    inv = layer.inventory()
    assert inv["library"]["last_ua"] == str(EDEV_MEDIUM_MAY_BE_CHANGED)
    assert inv["library"]["tapes"] == "3"
    assert lib.pending_injections() == []


def test_not_ready_changer_opens_but_refuses_moves(layer, lib):
    lib.inject("door_open 3600")
    layer.run("tur")                      # fire the injection: the door is now open
    inv = layer.inventory()
    assert inv["library"]["ready"] == "no" and inv["library"]["stale"] == "yes"
    assert inv["library"]["tapes"] == "0"
    assert layer.fails("load", "AAA001L9", DRV1) == LTFS_CHANGER_NOT_READY


def test_move_that_never_ran_is_repeated_after_a_failover(layer, lib):
    lib.inject("lost move")
    proc = layer.run("load", "AAA001L9", DRV1, check=True)
    assert "ACL0013W" in proc.stderr
    assert lib.content(D1) == "AAA001L9"


def test_move_that_ran_before_the_failover_is_not_repeated(layer, lib):
    lib.inject("lost move_after")
    proc = layer.run("load", "AAA001L9", DRV1, check=True)
    assert "ACL0013W" in proc.stderr
    assert parse_inventory(proc.stdout)["tapes"]["AAA001L9"]["address"] == D1
    assert lib.content(D1) == "AAA001L9"


def test_unexplained_move_failure_rereads_the_library(layer, lib):
    # The device says the source is empty, but the element status says otherwise
    lib.inject("fail move 05/3B0E")
    assert layer.fails("load", "AAA001L9", DRV1) == LTFS_INVENTORY_STALE
    assert lib.content(S0) == "AAA001L9"


def test_operator_move_is_seen_at_open(layer, lib):
    # Every command opens the layer and reads the whole library first
    lib.put(S0, "")
    lib.put(S3, "AAA001L9")
    inv = layer.ok("load", "AAA001L9", DRV1)
    assert inv["tapes"]["AAA001L9"]["home"] == S3


def test_move_refused_by_a_recovering_changer_is_redone_from_the_checks(layer, lib):
    # The device answers the MOVE with not ready once, then is ready: the
    # operation checks the elements again and moves once
    lib.inject("fail move 02/0418")
    proc = layer.run("load", "AAA001L9", DRV1, check=True)
    assert proc.stderr.count("ACL0012I") == 1
    assert lib.content(D1) == "AAA001L9" and lib.pending_injections() == []


def test_unit_attention_on_the_move_rereads_and_redoes_the_checks(layer, lib):
    lib.inject("fail move 06/2800")
    proc = layer.run("load", "AAA001L9", DRV1, check=True)
    assert "ACL0007W" in proc.stderr and proc.stderr.count("ACL0012I") == 1
    inv = parse_inventory(proc.stdout)
    assert inv["library"]["last_ua"] == str(EDEV_MEDIUM_MAY_BE_CHANGED)
    assert inv["tapes"]["AAA001L9"]["address"] == D1


def test_cleaning_cartridge_stays_refused_after_its_duplicate_leaves(layer, lib):
    lib.put(S3, "CLN001L9")
    assert layer.inventory()["tapes"]["CLN001L9"]["state"] == "duplicate"
    lib.put(S3, "")
    assert layer.inventory()["tapes"]["CLN001L9"]["state"] == "cleaning"
    assert layer.fails("load", "CLN001L9", DRV1) == LTFS_CLEANING_CARTRIDGE
