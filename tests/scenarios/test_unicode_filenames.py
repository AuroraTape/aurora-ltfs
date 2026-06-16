"""LTFS stores filenames as UTF-8 NFC on tape and compares them in
case-fold + NFD form internally (pathname.c, ltfs_fuse.c). So:

- An NFD path opens the same file as the equivalent NFC path.
- A name passed in NFD ends up serialized as NFC in the index XML.
- The three canonical forms of Å (U+212B, U+00C5, U+0041 U+030A) all
  resolve to the same on-tape entry.

All non-ASCII codepoints are written with explicit \\u escapes to
guarantee the source bytes don't get silently re-normalized by an
editor.
"""

import unicodedata

from common.altfs import format_tape, mount_tape, umount_tape
from common.index import parse_latest_index

NFC_CAFE = "café.txt"        # é = U+00E9 (precomposed)
NFD_CAFE = "café.txt"       # e + combining acute (decomposed)
assert unicodedata.normalize("NFC", NFD_CAFE) == NFC_CAFE
assert NFC_CAFE != NFD_CAFE


def test_nfc_name_round_trips(mounted_tape):
    p = mounted_tape / NFC_CAFE
    p.write_text("nfc-payload")
    assert p.read_text() == "nfc-payload"


def test_nfd_lookup_finds_nfc_file(mounted_tape):
    nfc = mounted_tape / "café-via-nfc.txt"
    nfd = mounted_tape / "café-via-nfc.txt"
    nfc.write_text("v1")
    assert nfd.read_text() == "v1"


def test_nfc_lookup_finds_nfd_file(mounted_tape):
    nfd_create = mounted_tape / "café-via-nfd.txt"
    nfc_lookup = mounted_tape / "café-via-nfd.txt"
    nfd_create.write_text("v2")
    assert nfc_lookup.read_text() == "v2"


def test_angstrom_forms_resolve_to_same_file(mounted_tape):
    # All three canonical forms of Å
    angstrom_a = mounted_tape / "Ångstrom.txt"        # ANGSTROM SIGN
    angstrom_b = mounted_tape / "Ångstrom.txt"        # LATIN CAPITAL A WITH RING ABOVE
    angstrom_c = mounted_tape / "Ångstrom.txt"       # A + COMBINING RING ABOVE
    angstrom_a.write_text("payload-from-atom")
    assert angstrom_b.read_text() == "payload-from-atom"
    assert angstrom_c.read_text() == "payload-from-atom"


def test_nfd_name_is_stored_as_nfc_on_tape(tmp_path_factory):
    base = tmp_path_factory.mktemp("altfs-nfc")
    tape = base / "tape"
    mnt = base / "mnt"
    tape.mkdir()
    mnt.mkdir()
    format_tape(tape, serial="NFCTST", label="nfc")

    mount_tape(tape, mnt)
    try:
        (mnt / NFD_CAFE).write_text("payload")
    finally:
        umount_tape(mnt)

    root = parse_latest_index(tape)
    names = [n.text for n in root.iter("name")]
    assert NFC_CAFE in names
    assert NFD_CAFE not in names
