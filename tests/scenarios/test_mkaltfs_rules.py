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
import xml.etree.ElementTree as ET

from common.altfs import mount_tape, umount_tape
from common.helpers import list_records, set_xattr


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


def _parse_index_records(record_paths):
    """Return [(generation, root_element), ...] sorted ascending for every
    record file under the given paths that holds an <ltfsindex>."""
    out = []
    for p in record_paths:
        if b"<ltfsindex" not in p.read_bytes()[:128]:
            continue
        root = ET.parse(p).getroot()
        gen_el = root.find("generationnumber")
        if gen_el is None:
            continue
        out.append((int(gen_el.text), root))
    out.sort(key=lambda kv: kv[0])
    return out


def _file_extent_partition(root, filename):
    """Letter ('a' or 'b') of the first extent's partition for the named file
    inside an <ltfsindex> root, or None if the file is absent."""
    for f in root.iter("file"):
        name = f.find("name")
        if name is not None and name.text == filename:
            partition = f.find(".//extent/partition")
            return partition.text if partition is not None else None
    return None


def test_mkaltfs_rules_size_and_name_route_only_matches_to_ip(tmp_path_factory):
    """`size=1M/name=*.jpg` caches a matching, under-cap file on
    the IP. A name mismatch or a name match that overshoots the
    size cap stays on the DP only.

    A mid-test `ltfs.sync` after writing the cached file leaves a
    DP-only index (gen 2) that predates the later writes, so we
    can verify that the older DP index references DP storage for
    photo.jpg while the latest IP index reroutes the same file
    to its cached IP copy."""
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
        # Forces a DP-only index write tagged with this commit
        # message. This generation has only photo.jpg and is the
        # "previous DP index" referenced in the assertions below.
        set_xattr(mnt, "ltfs.sync", "after-photo")
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

    # Raw-byte placement.
    assert small_match in ip_bytes, "matching small file should be cached on IP"
    assert small_match in dp_bytes, "matching small file must also exist on DP"
    assert big_match not in ip_bytes, "oversize match must not reach IP"
    assert big_match in dp_bytes
    assert nonmatch not in ip_bytes, "name mismatch must not reach IP"
    assert nonmatch in dp_bytes

    # Index XML cross-check.
    ip_indexes = _parse_index_records(ip_records)
    dp_indexes = _parse_index_records(dp_records)

    # Latest IP index reroutes the cached file to partition 'a'
    # (the IP), and leaves the non-cached files pointing into the
    # DP. This is what makes the cached copy actually useful — the
    # rapid-access lookup hits IP without traversing the DP.
    latest_ip_gen, latest_ip_root = ip_indexes[-1]
    assert _file_extent_partition(latest_ip_root, "photo.jpg") == "a"
    assert _file_extent_partition(latest_ip_root, "notes.txt") == "b"
    assert _file_extent_partition(latest_ip_root, "big.jpg") == "b"

    # The DP index from before the mid-test sync (gen 2 in this
    # scenario — gen 1 is the empty format-time index) saw only
    # photo.jpg and pointed at its DP copy. That older DP view
    # must remain DP-anchored: the IP cache is a forward
    # optimization, not a retroactive rewrite of past generations.
    prior_dp_gens = [g for g, _ in dp_indexes if g < latest_ip_gen]
    assert prior_dp_gens, f"expected an older DP index before gen {latest_ip_gen}"
    prev_dp_gen, prev_dp_root = next(
        (g, r) for g, r in dp_indexes
        if _file_extent_partition(r, "photo.jpg") is not None
        and g < latest_ip_gen
    )
    assert _file_extent_partition(prev_dp_root, "photo.jpg") == "b"


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
