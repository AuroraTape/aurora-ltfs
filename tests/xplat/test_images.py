"""Cross-platform volume check (issue #141): read and recover volumes that
another machine wrote.

``ALTFS_IMAGE_DIR`` points at the output of make_images.py, built where a
FUSE mount is possible (the Linux scenario job). Here nothing mounts: for
every image, ``altfsck`` checks (and for a crash state, recovers) a copy of
the volume, and the indexes on both partitions are captured with
``altfsindextool`` and compared with what the writer recorded. On macOS
this is the only way the index reader, the recovery and the file backend
get exercised on real volume data; on Linux the same test runs against the
images it just built, which keeps the check itself honest.

Without ``ALTFS_IMAGE_DIR`` the module is skipped.
"""

import json
import os
import shutil
from pathlib import Path

import pytest

from common.altfs import LTFSCK_CORRECTED, run_altfsck
from common.index import index_records, parse_latest_index

_IMAGE_DIR = os.environ.get("ALTFS_IMAGE_DIR")

pytestmark = pytest.mark.skipif(
    not _IMAGE_DIR, reason="ALTFS_IMAGE_DIR is not set: no volume images")


def _images():
    if not _IMAGE_DIR:
        return []
    root = Path(_IMAGE_DIR)
    return sorted(p.parent for p in root.rglob("expected.json"))


def _image_id(path):
    return str(path.relative_to(_IMAGE_DIR))


def _normalize(records):
    """index_records() uses tuples; JSON turns them into lists."""
    return json.loads(json.dumps(records))


@pytest.fixture
def image(request, tmp_path):
    """A private copy of the image: altfsck writes the recovered index
    into the volume, and the images must stay as the writer left them."""
    src = request.param
    work = tmp_path / "tape"
    shutil.copytree(src / "tape", work)
    expected = json.loads((src / "expected.json").read_text())
    return work, expected


def test_manifest_names_the_writer():
    manifest = json.loads((Path(_IMAGE_DIR) / "manifest.json").read_text())
    assert manifest["images"], manifest
    assert set(manifest["images"]) == {_image_id(p) for p in _images()}
    assert manifest["generator"]["system"] and manifest["altfs"]


def _consistent(check):
    """check_ltfs_volume() exits with LTFSCK_CORRECTED after processing a
    volume cleanly (it mounts and unmounts, which updates the MAM
    coherency data), see tests/scenarios/test_altfsck.py; the word is
    what tells a consistent volume from a corrected one."""
    out = (check.stdout + check.stderr).lower()
    return (check.returncode == LTFSCK_CORRECTED
            and "volume is consistent" in out
            and "alb0189i" not in out)


@pytest.mark.parametrize("image", _images(), indirect=True, ids=_image_id)
def test_check_recover_and_compare_indexes(image):
    tape, expected = image

    check = run_altfsck(tape_dir=tape)
    out = check.stdout + check.stderr
    if expected["altfsck"] == "consistent":
        assert _consistent(check), out
    else:
        assert expected["altfsck"] == "corrected", expected["altfsck"]
        assert check.returncode == LTFSCK_CORRECTED, out
        assert "ALB0189I" in out, "recovery must complete"

    # The (recovered) index describes every object like the writer's does:
    # UIDs, time stamps, read-only flags, extended attributes, symlink
    # targets and the extents.
    for partition in ("0", "1"):
        got = _normalize(index_records(parse_latest_index(tape, int(partition))))
        assert got == expected["index"][partition], f"partition {partition}"

    # A second check finds nothing left to recover.
    again = run_altfsck(tape_dir=tape)
    assert _consistent(again), again.stdout + again.stderr
