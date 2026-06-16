from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from common.altfs import format_tape, mount_tape, umount_tape


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
