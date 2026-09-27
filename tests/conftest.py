from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from common.altfs import format_tape, mount_tape, umount_tape

_FSAPI_DIR = Path(__file__).resolve().parent / "fsapi"


def pytest_collection_modifyitems(items):
    """Attach the ``mount`` marker (registered in pytest.ini) where it is
    implied: every module under tests/fsapi exercises the mounted file
    system, and a test that asks for the ``mounted_tape`` fixture mounts by
    definition. A test that mounts on its own (mount_tape(),
    crash_and_recover(), a script that mounts, ...) is marked explicitly in
    its module, per test or with ``pytestmark``.
    """
    for item in items:
        if (Path(item.path).resolve().is_relative_to(_FSAPI_DIR)
                or "mounted_tape" in getattr(item, "fixturenames", ())):
            item.add_marker(pytest.mark.mount)


@pytest.fixture(scope="module")
def mounted_tape(tmp_path_factory):
    base = tmp_path_factory.mktemp("altfs")
    tape_dir = base / "tape"
    mnt_dir = base / "mnt"
    tape_dir.mkdir()
    mnt_dir.mkdir()

    format_tape(tape_dir)
    mount_tape(tape_dir, mnt_dir)
    try:
        yield mnt_dir
    finally:
        umount_tape(mnt_dir)
