"""Replay the fssim test cases and recover from the crash state (#82).

Every command file in ``contrib/fssim/testcases`` is replayed on a
mounted volume (see ``common.fssim``). Its ``index`` commands become a
full index first and incremental indexes afterwards. When the script
ends, the volume "crashes": ``altfsck`` has to replay the incremental
indexes, and the recovered index and tree must equal what a clean
unmount produces (see ``common.recovery``).

The simulator verifies its cases the other way round, by merging its
own incremental indexes into its first full index. Its XML differs from
what libaltfs writes, so the ground truth here is the clean unmount of
the real implementation, not the simulator's output.
"""

from pathlib import Path

import pytest

from common.altfs import format_tape, mount_tape, umount_tape
from common.fssim import Replay
from common.recovery import crash_and_recover


_TESTCASES = sorted(
    (Path(__file__).resolve().parents[2] / "contrib" / "fssim" /
     "testcases").glob("*.txt"))


def _last_dp_index_is_incremental(tape_dir):
    """The file backend stores block B of the data partition as 1_<B>_R."""
    last = None
    for record in sorted(tape_dir.glob("1_*_R"),
                         key=lambda p: int(p.name.split("_")[1])):
        head = record.read_bytes()[:512]
        if b"<ltfsincrementalindex " in head:
            last = True
        elif b"<ltfsindex " in head:
            last = False
    return bool(last)


def test_testcases_are_found():
    assert len(_TESTCASES) >= 21


@pytest.mark.parametrize("script", _TESTCASES, ids=lambda p: p.stem)
def test_fssim_case_recovers(tmp_path, script):
    tape_dir = tmp_path / "tape"
    crashed_dir = tmp_path / "tape-crashed"
    mnt = tmp_path / "mnt"
    tape_dir.mkdir()
    mnt.mkdir()

    format_tape(tape_dir, serial="FSSIM1", label="fssim")
    mount_tape(tape_dir, mnt)
    try:
        replay = Replay(mnt).run(script)
        if replay.changed_since_index:
            # The script ends with changes that no index holds. They
            # would be lost in the crash by design; give them an index so
            # the whole script is what the recovery has to reproduce.
            replay._index("-i", "end of script")
    except BaseException:
        umount_tape(mnt)
        raise

    assert replay.indexes, "the script must write at least one index"

    # Commands may fail like they do in the simulator (removing a
    # directory with rm, ...), but a script that mostly fails means the
    # driver no longer understands it.
    assert len(replay.failed) <= 2, replay.failed

    # The crash state needs a recovery if the data partition ends in an
    # incremental index. An "index" without changes before it writes a
    # full index even when an incremental one is asked for (the commit
    # message is the only change, and the journal cannot carry that).
    crash_and_recover(tape_dir, mnt, crashed_dir,
                      need_recovery=_last_dp_index_is_incremental(tape_dir))
