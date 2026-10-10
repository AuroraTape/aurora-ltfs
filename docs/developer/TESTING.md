# Writing tests

How to run the test suites, with what they need installed, is in
[How to build](BUILDING.md#running-the-tests). This document is about
writing a test: where it belongs, the helpers it builds on, and the `file`
tape backend that most tests run on, with the ways it can put a volume into a
state that is hard to produce on a real drive.

Every suite is pytest. `pytest.ini` at the repository root fixes the root
directory, so `pytest tests/scenarios/test_foo.py` works from anywhere in the
tree, and `tests/conftest.py` is always loaded. The tests run the *installed*
commands (`altfs`, `mkaltfs`, `altfsck`, `altfsindextool`) found through
`PATH`, never the build tree: install into a prefix and run through the
`run.sh` of a suite, which puts `$ALTFS_PREFIX/bin` and `$ALTFS_PREFIX/lib`
in front of `PATH` and `LD_LIBRARY_PATH`.

## The suites

| Directory | What goes there | Mounts |
|:--|:--|:--|
| `tests/scenarios` | Command-line behaviour and whole scenarios: format, mount, write, crash, recover; options of the commands; index policies; the profiler; the service scripts. One module per scenario or feature. | Some |
| `tests/fsapi` | The file system API as an application sees it on a mounted volume: one module per system call family (`stat`, `rename`, `xattr`, `utime`, ...). | All |
| `tests/xplat` | Reading and recovering volumes that another machine wrote. Needs `ALTFS_IMAGE_DIR`, the output of `tests/xplat/make_images.py`; without it the module skips. | No |
| `tests/realdrive` | Shell scripts run by hand, as root, on a host with a tape drive. Not pytest. `tests/scenarios/test_realdrive_scripts.py` runs their dry-run modes on the `file` backend so CI notices when they break. | Yes |

A new test is a `test_*.py` module in `tests/scenarios` or `tests/fsapi`.
Start the module with a docstring that says what behaviour it pins down and
why; the existing modules are written that way and the docstring is where a
reader learns what the test protects.

### The `mount` marker

A test that mounts a volume through FUSE cannot run everywhere: the hosted
macOS CI runners cannot mount, and a machine without `fusermount` or an
approved macFUSE cannot either. Such tests carry the `mount` marker, which
`pytest.ini` registers (`--strict-markers` rejects any other marker), and are
deselected with `-m "not mount"`.

`tests/conftest.py` adds the marker where it is implied: on every test under
`tests/fsapi`, and on every test that asks for the `mounted_tape` fixture. A
test that mounts on its own (`mount_tape()`, `crash_and_recover()`, a script
that mounts) is marked in its module, per test or for the whole module:

```python
pytestmark = pytest.mark.mount  # every test here goes through a FUSE mount
```

## The shared helpers

`tests/common` is on `sys.path` (set by `tests/conftest.py`); import from it
as `from common.altfs import ...`.

`common.altfs`: the commands.

- `format_tape(tape_dir, serial="TEST00", label="test")`: `mkaltfs -e file`.
  The serial is exactly six characters.
- `mount_tape(tape_dir, mnt, sync_type="unmount", extra_opts=())`: a
  daemonized `altfs` on the `file` backend, returning when the mount is
  ready. `extra_opts` are more `-o` options (`["rollback_mount=3"]`).
  `ALTFS_TEST_MOUNT_OPTS`, when set, is added as one more `-o` to every mount
  made through the helpers, e.g. `backend=fskit` to run the suites over
  macFUSE's FSKit backend. `tape_dir=None` mounts without a device (an index
  file mount).
- `umount_tape(mnt)`: detaches the mount and waits for the daemon to exit, so
  the final index is on the "tape" when the function returns. Failing to
  detach is an error, not a warning: a leaked daemon breaks later tests.
- `mount_tape_foreground()` / `umount_tape_foreground()`: `altfs -f` as a
  child process, for tests that need the daemon's exit status; its output goes
  to `altfs-foreground.log` next to the mount point.
- `try_mount_tape()`: a mount that is expected to fail, returning the
  `CompletedProcess`. A mount that unexpectedly succeeds times out.
- `run_altfsck(*args, tape_dir=...)`: `altfsck -e file`, output captured.
  The exit codes are the constants `LTFSCK_NO_ERRORS`, `LTFSCK_CORRECTED`,
  `LTFSCK_UNCORRECTED`, ... A plain check of a healthy volume exits with
  `LTFSCK_CORRECTED`: it mounts and unmounts, which rewrites the index.
- `crash_altfs_daemon(mnt)`: SIGKILLs the daemon and detaches the dead mount,
  leaving the tape as a crash leaves it: data newer than the newest index.

`common.helpers`: extended attributes and the tape directory.

- `get_xattr()`, `get_xattr_int()`, `set_xattr()`, `remove_xattr()`,
  `list_xattrs()`: the attributes as altfs names them (`ltfs.sync`,
  `ltfs.vendor.Aurora.profiler`, `test.tag`). The helpers add the `user.`
  namespace on Linux and go through libc on macOS and the BSDs, where Python
  has no `os.*xattr`; never call `os.setxattr` in a test.
- `full_sync(mnt)` / `incremental_sync(mnt)`: write a full or an incremental
  index through the vendor attributes.
- `list_records(tape_dir)`: the data block files of each partition, in block
  order.

`common.index`: the index as an independent reader sees it.
`parse_latest_index(tape_dir, partition=0)` captures the indexes with `altfsindextool` and parses the newest one with
`xml.etree`, which shares no code with altfs's libxml2 parser; `index_records()`
flattens it for comparison, `records_with_tag()` finds the block files whose
XML top-level element is `ltfsindex`, `ltfsincrementalindex` or `ltfslabel`.

`common.recovery`: `crash_and_recover(tape_dir, mnt, crashed_dir)` is the
whole write / crash / `altfsck` / compare cycle of the incremental index
tests; `common.incindex_cases` holds the change sequences it is fed, and
`common.fssim` replays the command files of `contrib/fssim/testcases` on a
mount.

### Fixtures

`mounted_tape` (module scope, `tests/conftest.py`) formats and mounts one
volume for all the tests of a module and unmounts it at the end. Tests that
need a mount of their own, several mounts, or the tape directory, build them
from `tmp_path` or `tmp_path_factory` with the helpers above. Keep a mount
per module where you can: a mount costs about a second, an unmount with its
index write more.

### A scenario test

```python
"""A read-only mount refuses changes and leaves the medium as it was."""
import errno
import os

import pytest

from common.altfs import format_tape, mount_tape, umount_tape

pytestmark = pytest.mark.mount  # every test here goes through a FUSE mount


def test_ro_mount_rejects_writes(tmp_path):
    tape_dir, mnt = tmp_path / "tape", tmp_path / "mnt"
    tape_dir.mkdir()
    mnt.mkdir()
    format_tape(tape_dir, serial="RDONLY", label="rdonly")

    mount_tape(tape_dir, mnt)
    try:
        (mnt / "first.txt").write_text("first\n")
    finally:
        umount_tape(mnt)
    medium = {p.name: p.read_bytes() for p in tape_dir.iterdir()
              if not p.name.startswith("attr_")}   # MAM files are not the medium

    mount_tape(tape_dir, mnt, extra_opts=["ro"])
    try:
        with pytest.raises(OSError) as exc:
            (mnt / "new.txt").write_text("refused")
        assert exc.value.errno == errno.EROFS
        assert (mnt / "first.txt").read_text() == "first\n"
    finally:
        umount_tape(mnt)
    assert {p.name: p.read_bytes() for p in tape_dir.iterdir()
            if not p.name.startswith("attr_")} == medium
```

Rules the existing tests follow:

- Always unmount in `finally`; a volume left mounted takes the rest of the
  run down with it.
- Compare data after a remount. Read back on the same mount, the kernel may
  answer from its own cache without asking altfs.
- Assert on exit codes and on the message IDs (`ALB0189I`) rather than on
  message text, which the catalogs may change.
- Give a subprocess the test starts itself a timeout, so a hang fails the
  test instead of the job.
- Short tapes: the `file` backend stores every block as a file, so a few
  megabytes are plenty. `test_large_writes.py` is the exception that needs
  more, and it formats with a small block size instead.

## The `file` tape backend

`src/tape_drivers/generic/file/` is a tape drive and a cartridge made of a
directory. `-o tape_backend=file -o devname=<dir>` (`altfs`) or
`-e file -d <dir>` (`mkaltfs`, `altfsck`, `altfsindextool`) selects it. It is
the only backend CI can run, and the one a test should reach for whenever a
situation on the tape, not the SCSI path, is what is being tested.

### The directory

| Entry | Meaning |
|:--|:--|
| `<P>_<B>_R` | Block `B` of partition `P` (0 = index partition, 1 = data partition), the record's bytes as written |
| `<P>_<B>_F` | A filemark at block `B` (empty file) |
| `<P>_<B>_E` | The end of data of partition `P` is at block `B` (empty file); exactly one per partition on a healthy volume |
| `attr_<P>_<id>` | A MAM attribute (`id` in hex), e.g. the volume coherency and the volume lock state |
| `filedebug_tc_conf.xml` | The cartridge configuration, written with defaults the first time the cartridge is loaded |

Everything is plain files, so a test can take a copy of the tape at any
moment (`shutil.copytree`), look at what a sync wrote (`list_records`,
`records_with_tag`), or damage it:

- **A crash**: `crash_altfs_daemon()` kills the daemon, or copy the tape
  directory while it is mounted (what `crash_and_recover()` does). Leave the
  `attr_*` files out of the copy: the MAM volume coherency lets a mount take
  a shortcut that would hide an incremental index left on the tape.
- **EOD missing**: delete the `<P>_*_E` file of a partition
  (`test_missing_eod.py`). The mount is refused and `altfsck --deep-recovery`
  rebuilds the EOD from the other partition; with both deleted nothing is
  recoverable and the test checks that this is said.
- **A damaged or stray index**: the index is XML in `<P>_<B>_R` files;
  `records_with_tag()` finds them. An incremental index with no full index
  after it is the crash state of `test_format_spec25.py` and
  `test_incindex_recovery.py`.
- **Historic states**: `ltfs.sync` with a message as value writes a full
  index tagged with it, so a volume with several known generations is built
  deterministically and `altfsck -l`, `-o rollback_mount=<gen>` and
  `-o index_file=` have something to roll back to (`test_altfsck.py`,
  `test_volume_lifecycle.py`).

### The cartridge configuration

`filedebug_tc_conf.xml` is read at every load, so a test edits it between
the format and the mount (`test_write_perm.py`, `test_transfer_limit.py` do
it with a regular expression on the element). The elements:

| Element | Default | Emulates |
|:--|:--|:--|
| `emulate_readonly` | `false` | A write-protected cartridge: the mount comes up read-only |
| `capacity_mb` | 3072 | The cartridge capacity; the index partition gets 5 % of it. The early warning is raised when the blocks written on a partition, counted as 512 KiB each, reach its capacity, so a small value makes a volume that fills up |
| `max_transfer_bytes` | 0 (no limit) | The transfer limit of the host path: a block longer than this fails, as an HBA behind Thunderbolt would make it fail |
| `cart_type`, `density_code` | LTO5 data cartridge | Which cartridge is loaded (the `TC_MP_*` codes of `tape_drivers.h`): a type the emulated drive can only read mounts read-only, the 3592 WORM types (JX, JY, JZ) behave as WORM, a type the drive generation does not know is rejected |
| `dummy_io` | `false` | Writes to the data partition are not stored, to measure the layers above the backend |
| `delay_mode`, `wraps`, `eot_to_bot_sec`, `change_direction_us`, `change_track_us`, `threading_sec` | `None` | Positioning and load times of a real drive: `Calculate` accounts them, `Emulate` sleeps them |

The emulated drive is an `ULTRIUM-TD5` unless the device is named through
a drive file (below), whose name carries the model.

### Error injection through extended attributes

Once mounted, the backend takes orders through vendor attributes on the
mount point (`set_xattr(mnt, "ltfs.vendor.Aurora.forceErrorWrite", "5")`):

- `forceErrorWrite = N`: writes 1 to N after arming are accepted and the
  next one fails with a write permanent error. The last 20 writes before the
  failing one (`THRESHOLD_FORCE_WRITE_NO_WRITE` in `tape_drivers.h`) are
  accepted but silently dropped, as a drive buffer that never reaches the
  tape; this is how the recovery of a torn write is tested. A negative `N`
  clears the condition on the next partition change, so only the data
  partition is hit and the recovery index still reaches the index partition;
  a positive `N` persists and the index write fails too. `test_write_perm.py`
  has both.
- `forceErrorRead = N`: reads 1 to N succeed and the next one fails. Nothing
  is dropped on the read side.
- `forceErrorType = 1`: changes the error the failing command returns. The two
  sides are wired the other way round in the backend: a failing write returns
  a write permanent error by default and no sense with `forceErrorType = 1`,
  a failing read returns no sense by default and a read permanent error with
  `forceErrorType = 1`.

### A drive without a cartridge

When `devname` names a regular file instead of a directory, the file is the
drive and its content, 36 bytes NUL padded, names the cartridge directory
next to it or says `empty`. Writing a directory name into the file is loading
a cartridge; `test_wait_medium.py` uses it for `-o wait_medium`, and the
real-drive scripts run their dry runs against such a drive.

`altfs -o device_list` enumerates drives from `/tmp/ltfs<pid>` (the pid of
the altfs process), which holds the path of a directory whose
`Drive_<n>_<serial>.<model>` files are the drives; `test_cli_options.py`
shows how to create that file under the right pid.

### What is not emulated

Encryption keys, drive dumps and the vendor SCSI pages are stubs. Delay
emulation accounts the mechanical model loosely (one block size per wrap
calculation, no back hitch). Anything about the SCSI path, the sg command
filter, reservations and path failover needs a real drive and belongs in
`tests/realdrive`.

## The `itdtimg` backend

`src/tape_drivers/generic/itdtimg/` reads a tape image written by IBM's
Tape Diagnostic Tool: `-o tape_backend=itdtimg -o devname=<image>`
(default `tape.img`). It is read-only and takes no options. It exists to
mount a dump of a real cartridge sent in for analysis; no test uses it.

## The release branches

The `release/1.0` branch carries the test tree as it was at 1.0: no
`pytest.ini`, no `mount` marker and no `ALTFS_TEST_MOUNT_OPTS`, so its CI
runs the whole `tests/fsapi` and `tests/scenarios` on Linux only, and the
incremental index recovery lives in the shell harness
`tests/incindex-recovery`. A test backported there must not use the marker
or the newer helpers (`crash_altfs_daemon`, `common.recovery`,
`common.incindex_cases`), or must bring them along.

## What CI runs where

| Job | Platform | Runs |
|:--|:--|:--|
| FS API + scenarios (`scenario.yml`) | Ubuntu 24.04 | `tests/fsapi` and `tests/scenarios` in full, `--enable-warning-as-error`; then builds the cross-platform images and checks them with `tests/xplat` |
| Volume checks (`scenario.yml`) | macOS 15, FreeBSD 14.3 | `tests/xplat` on the Linux images; FreeBSD also writes its own and Linux reads them back. Tier 2, non-blocking |
| Coverage (`scenario.yml`) | Ubuntu 24.04 | The two suites again on a `--coverage` build (`-O0 -g -fprofile-update=atomic`), `lcov`, upload to Codecov |
| Build (`build.yml`) | Ubuntu 24.04, Rocky Linux 9, Debian 13, Ubuntu 26.04, Rocky Linux 10 | Build only |
| Build (`build.yml`) | macOS 15 | Build, then `tests/scenarios -m "not mount"`; the hosted runners cannot mount. Non-blocking |
| Build (`build.yml`) | FreeBSD 14.3, NetBSD 10.1 VMs | Build, `tests/scenarios -m "not mount"`; FreeBSD also runs the mounted tests, exploratory and non-blocking |

Coverage: Codecov's project status fails only when the overall figure drops
by more than 5 %; the patch status is informational, because CI reaches
libaltfs through the `file` backend only, and `codecov.yml` leaves the
hardware backends out of the denominator. A change in a real-drive code path
therefore shows as uncovered and is checked with `tests/realdrive` instead.

The macOS job cannot mount, so a test that must run there is one that does
not mount: `mkaltfs`, `altfsck`, `altfsindextool` on the `file` backend, the
command-line paths, and `tests/xplat`. On a Mac with macFUSE set up, both
suites run by hand; see [How to build](BUILDING.md#running-the-tests).
