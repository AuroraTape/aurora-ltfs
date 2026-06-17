"""Coverage for mkaltfs --rules and the index_criteria.c match path.

Without --rules every test in the harness leaves the index in its
"no criteria" state, so the parse, glob-cache, and caseless match
code in src/libltfs/index_criteria.c is never exercised. These
tests format a fresh tape with a rule, write files that hit each
leg of it, and check on-tape placement on the file backend.

LTFS caches data that matches the rule on the index partition (IP,
partition 0) while always writing the full bytes to the data
partition (DP, partition 1). The file backend lays each tape block
down as a separate <part>_<block>_R record file, so we can read
the raw record contents and assert which partition each marker
landed on.
"""

import os
import subprocess

from common.altfs import mount_tape, umount_tape
from common.helpers import list_records


def _format_with_rules(tape_dir, rules, *, serial, label="rules"):
    """Format a fresh file-backend tape with the given --rules string."""
    subprocess.run(
        ["mkaltfs", "-e", "file", "-d", str(tape_dir),
         "-s", serial, "-n", label,
         f"--rules={rules}", "-f"],
        check=True,
        capture_output=True,
    )


def _concat_bytes(record_paths):
    return b"".join(p.read_bytes() for p in record_paths)


def test_mkaltfs_rules_size_and_name_route_only_matches_to_ip(tmp_path_factory):
    """`size=1M/name=*.jpg` caches a matching, under-cap file on
    the IP. A name mismatch or a name match that overshoots the
    size cap stays on the DP only."""
    base = tmp_path_factory.mktemp("rules-mix")
    tape_dir = base / "tape"
    mnt = base / "mnt"
    tape_dir.mkdir()
    mnt.mkdir()

    _format_with_rules(tape_dir, "size=1M/name=*.jpg", serial="RULEMX")

    small_match = b"MATCH-SMALL-JPG-MARKER"
    big_match = b"MATCH-BIG-JPG-MARKER"
    nonmatch = b"NAME-MISMATCH-TXT-MARKER"

    mount_tape(tape_dir, mnt)
    try:
        (mnt / "photo.jpg").write_bytes(small_match + b"x" * 200)
        # 2 MiB exceeds the 1 MiB cache cap; matches the name glob
        # but must not be cached on the IP.
        big_payload = big_match + os.urandom(2 * 1024 * 1024 - len(big_match))
        (mnt / "big.jpg").write_bytes(big_payload)
        (mnt / "notes.txt").write_bytes(nonmatch + b"y" * 200)
    finally:
        umount_tape(mnt)

    ip_records, dp_records = list_records(tape_dir)
    ip_bytes = _concat_bytes(ip_records)
    dp_bytes = _concat_bytes(dp_records)

    assert small_match in ip_bytes, "matching small file should be cached on IP"
    assert small_match in dp_bytes, "matching small file must also exist on DP"
    assert big_match not in ip_bytes, "oversize match must not reach IP"
    assert big_match in dp_bytes
    assert nonmatch not in ip_bytes, "name mismatch must not reach IP"
    assert nonmatch in dp_bytes


def test_mkaltfs_rules_size_only_caches_any_small_file_on_ip(tmp_path_factory):
    """A `size=…` rule with no `name=…` leg lets every under-cap
    file land on the IP — this is the index_criteria_match
    early-return when glob_patterns is NULL."""
    base = tmp_path_factory.mktemp("rules-size-only")
    tape_dir = base / "tape"
    mnt = base / "mnt"
    tape_dir.mkdir()
    mnt.mkdir()

    _format_with_rules(tape_dir, "size=100K", serial="RULESS")

    a_marker = b"ANY-NAME-DAT-MARKER"
    b_marker = b"OTHER-NAME-XYZ-MARKER"

    mount_tape(tape_dir, mnt)
    try:
        (mnt / "any-name.dat").write_bytes(a_marker + b"a" * 200)
        (mnt / "other.xyz").write_bytes(b_marker + b"b" * 200)
    finally:
        umount_tape(mnt)

    ip_records, _ = list_records(tape_dir)
    ip_bytes = _concat_bytes(ip_records)

    assert a_marker in ip_bytes
    assert b_marker in ip_bytes


def test_mkaltfs_rules_multiple_name_globs(tmp_path_factory):
    """`name=*.jpg:*.png` accepts files matching either extension.
    A file matching neither stays on the DP only."""
    base = tmp_path_factory.mktemp("rules-multi-glob")
    tape_dir = base / "tape"
    mnt = base / "mnt"
    tape_dir.mkdir()
    mnt.mkdir()

    _format_with_rules(tape_dir, "size=1M/name=*.jpg:*.png", serial="RULEMG")

    jpg = b"JPG-EXT-MARKER"
    png = b"PNG-EXT-MARKER"
    txt = b"TXT-EXT-MARKER"

    mount_tape(tape_dir, mnt)
    try:
        (mnt / "a.jpg").write_bytes(jpg + b"a" * 100)
        (mnt / "b.png").write_bytes(png + b"b" * 100)
        (mnt / "c.txt").write_bytes(txt + b"c" * 100)
    finally:
        umount_tape(mnt)

    ip_records, dp_records = list_records(tape_dir)
    ip_bytes = _concat_bytes(ip_records)
    dp_bytes = _concat_bytes(dp_records)

    assert jpg in ip_bytes
    assert png in ip_bytes
    assert txt not in ip_bytes
    assert txt in dp_bytes


def test_mkaltfs_rules_invalid_syntax_rejected(tmp_path):
    """A malformed --rules string must be rejected before any
    bytes touch the tape. Exact exit code is not part of the
    contract — only that it is non-zero and no record files were
    written."""
    r = subprocess.run(
        ["mkaltfs", "-e", "file", "-d", str(tmp_path),
         "-s", "BADRUL", "-n", "bad",
         "--rules=this=is=garbage", "-f"],
        capture_output=True, text=True, timeout=10,
    )
    assert r.returncode != 0
    ip_records, dp_records = list_records(tmp_path)
    assert ip_records == [] and dp_records == []


def test_mkaltfs_rules_invalid_size_value_rejected(tmp_path):
    """`size=oops` exercises the dedicated parse_size error path
    distinct from the unknown-keyword path covered above."""
    r = subprocess.run(
        ["mkaltfs", "-e", "file", "-d", str(tmp_path),
         "-s", "BADSIZ", "-n", "bad",
         "--rules=size=oops", "-f"],
        capture_output=True, text=True, timeout=10,
    )
    assert r.returncode != 0
