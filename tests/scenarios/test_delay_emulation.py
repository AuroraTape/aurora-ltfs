"""Delay emulation of the file tape backend (issue #245).

With ``delay_mode`` set to ``Calculate`` in the per-cartridge configuration
file, the backend adds the time a real drive would spend on each locate,
rewind, load and unload to a counter that the ``seekLatency`` vendor
attribute reports. ``threading_sec`` is the load and unload share; its
default of 12 seconds has to reach the counter whether the element is
written as 0 (what configuration files of older versions hold) or left
out.
"""
import re

import pytest

from common.altfs import format_tape, mount_tape, umount_tape
from common.helpers import get_xattr, set_xattr

pytestmark = pytest.mark.mount  # every test here goes through a FUSE mount

_CONFIG = "filedebug_tc_conf.xml"
_VENDOR = "ltfs.vendor.Aurora."
_THREADING_DEFAULT = 12


def _set_element(conf, name, value):
    """Set <name> in the configuration file; value None removes the element."""
    text = conf.read_text()
    if value is None:
        text, n = re.subn(rf"\s*<{name}>[^<]*</{name}>", "", text)
    else:
        text, n = re.subn(rf"<{name}>[^<]*</{name}>",
                          f"<{name}>{value}</{name}>", text)
    assert n == 1, text
    conf.write_text(text)


def _seconds(latency):
    m = re.fullmatch(r"(\d+)s(\d+)ns", latency)
    assert m, latency
    return int(m.group(1))


@pytest.fixture
def tape_dir(tmp_path):
    """A formatted file-backend tape (the first format writes the config)."""
    d = tmp_path / "tape"
    d.mkdir()
    format_tape(d, serial="DELAY0", label="delay")
    return d


@pytest.mark.parametrize("threading", [0, None], ids=["zero", "absent"])
def test_threading_time_defaults_to_twelve_seconds(tape_dir, tmp_path, threading):
    conf = tape_dir / _CONFIG
    assert "<threading_sec>" in conf.read_text()
    _set_element(conf, "delay_mode", "Calculate")
    _set_element(conf, "threading_sec", threading)

    mnt = tmp_path / "mnt"
    mnt.mkdir()
    mount_tape(tape_dir, mnt)
    try:
        # The load accounted one threading time plus the seeks of the mount,
        # which are fractions of a second on a 3 GiB cartridge.
        seconds = _seconds(get_xattr(mnt, _VENDOR + "seekLatency"))
        assert _THREADING_DEFAULT <= seconds < 2 * _THREADING_DEFAULT, seconds

        # Writing 0 resets the counter
        set_xattr(mnt, _VENDOR + "seekLatency", "0")
        assert _seconds(get_xattr(mnt, _VENDOR + "seekLatency")) == 0
    finally:
        umount_tape(mnt)


def test_explicit_threading_time_is_used(tape_dir, tmp_path):
    conf = tape_dir / _CONFIG
    _set_element(conf, "delay_mode", "Calculate")
    _set_element(conf, "threading_sec", 30)

    mnt = tmp_path / "mnt"
    mnt.mkdir()
    mount_tape(tape_dir, mnt)
    try:
        seconds = _seconds(get_xattr(mnt, _VENDOR + "seekLatency"))
        assert 30 <= seconds < 60, seconds
    finally:
        umount_tape(mnt)
