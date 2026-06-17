"""Integration coverage for altfsck against file-backend tapes.

altfsck has multiple modes (default check, list rollback points,
capture index, rollback, verify-against-generation) and outside of
the legacy bash recovery scenario none of them ran inside the
pytest harness, so coverage of `src/cmd/altfsck/altfsck.c` was
near zero on Codecov.

These tests exercise the modes that do not require encryption or
real rollback. The multi-generation case uses `ltfs.sync` with a
commit message to advance the generation deterministically: each
setxattr forces a full index write tagged with the message, which
then surfaces in `altfsck -l` output. This avoids depending on
the file backend's timing emulation and produces a stable tape
state we can assert against.
"""

import subprocess

from common.altfs import format_tape, mount_tape, umount_tape
from common.helpers import set_xattr


_RUN_TIMEOUT = 30


def _altfsck(*extra_args, tape_dir):
    return subprocess.run(
        ["altfsck", "-e", "file", *extra_args, str(tape_dir)],
        capture_output=True,
        text=True,
        timeout=_RUN_TIMEOUT,
    )


def test_altfsck_modes_on_clean_tape(tmp_path_factory):
    """A freshly formatted tape exposes one rollback point (the
    initial format) and is consistent under default check; the
    --capture-index mode must emit the format-generation schema
    files into the output directory."""
    base = tmp_path_factory.mktemp("altfsck-clean")
    tape_dir = base / "tape"
    tape_dir.mkdir()
    format_tape(tape_dir, serial="FSCKCL", label="fsck-clean")

    # Default check: altfsck returns LTFSCK_NO_ERRORS (0) or
    # LTFSCK_CORRECTED (1) on a consistent volume — both indicate
    # the volume was processed cleanly without unrecoverable error.
    check = _altfsck(tape_dir=tape_dir)
    assert check.returncode in (0, 1), check.stderr
    assert "consistent" in (check.stdout + check.stderr).lower()

    # -l: rollback-point listing should mention the initial index.
    listing = _altfsck("-l", tape_dir=tape_dir)
    assert listing.returncode == 0, listing.stderr
    listing_out = listing.stdout + listing.stderr
    assert "Initial Index" in listing_out
    assert "Format -" in listing_out  # auto-generated format comment

    # --capture-index: writes one <barcode>-<gen>-<id>.schema file
    # per partition copy of each index. A clean tape has the
    # initial index on the DP, so at least one schema file lands
    # in the output directory.
    capture_dir = base / "capture"
    capture_dir.mkdir()
    cap = _altfsck(f"--capture-index={capture_dir}", tape_dir=tape_dir)
    assert cap.returncode == 0, cap.stderr
    schemas = list(capture_dir.glob("*.schema"))
    assert schemas, f"no schema files produced: {list(capture_dir.iterdir())}"
    # Captured XML should start with the LTFS index root element.
    head = schemas[0].read_bytes()[:128]
    assert b"<ltfsindex" in head


def test_altfsck_l_lists_commit_messages_from_synced_writes(tmp_path_factory):
    """Each `setxattr user.ltfs.sync = <msg>` on the mount root
    forces a full index write tagged with the message. After three
    such cycles the rollback-point listing must contain every
    commit message we recorded, plus the initial-format entry."""
    base = tmp_path_factory.mktemp("altfsck-multi")
    tape_dir = base / "tape"
    mnt = base / "mnt"
    tape_dir.mkdir()
    mnt.mkdir()

    format_tape(tape_dir, serial="FSCKMG", label="fsck-multi")
    mount_tape(tape_dir, mnt)
    try:
        commits = ["alpha commit", "bravo commit", "charlie commit"]
        for i, msg in enumerate(commits, start=1):
            (mnt / f"f{i}.txt").write_text(f"file {i}")
            set_xattr(mnt, "ltfs.sync", msg)
    finally:
        umount_tape(mnt)

    listing = _altfsck("-l", tape_dir=tape_dir)
    assert listing.returncode == 0, listing.stderr
    out = listing.stdout + listing.stderr

    for msg in commits:
        assert msg in out, f"missing commit message {msg!r} in:\n{out}"
    assert "Initial Index" in out
