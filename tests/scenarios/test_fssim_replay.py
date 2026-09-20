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
from common.helpers import list_records
from common.recovery import crash_and_recover


_TESTCASES = sorted(
    (Path(__file__).resolve().parents[2] / "contrib" / "fssim" /
     "testcases").glob("*.txt"))


# Commands that fail during the replay, per script. They fail in the
# simulator as well: "rm" of what is a directory at that point, and the
# "mv" that depends on it. Any other failure means that the driver and
# the script no longer understand each other.
_EXPECTED_FAILURES = {
    "daptest5": ["rm /A/B/n1"],
    "fssimin10": ["rm /A/B/n1", "mv n1 /A/B"],
}


def _last_dp_index_is_incremental(tape_dir):
    last = False
    _, dp_records = list_records(tape_dir)
    for record in dp_records:
        with open(record, "rb") as f:
            head = f.read(512)
        if b"<ltfsincrementalindex " in head:
            last = True
        elif b"<ltfsindex " in head:
            last = False
    return last


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
            replay.index("-i", "end of script")

        assert replay.indexes, "the script must write at least one index"
        assert [line for _, line in replay.failed] == \
            _EXPECTED_FAILURES.get(script.stem, [])
        need_recovery = _last_dp_index_is_incremental(tape_dir)
    except BaseException:
        umount_tape(mnt)
        raise

    # The crash state needs a recovery if the data partition ends in an
    # incremental index. An "index" without changes before it writes a
    # full index even when an incremental one is asked for (the commit
    # message is the only change, and the journal cannot carry that).
    crash_and_recover(tape_dir, mnt, crashed_dir,
                      need_recovery=need_recovery)
