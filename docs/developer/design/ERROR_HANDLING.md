# Error handling

An error in Aurora LTFS starts as SCSI sense data in a tape backend, or as a
condition the library detects itself, and ends as an `errno` value in the
application that called the file system, or as the exit code of a command.
On the way it is an integer code from `src/libltfs/ltfs_error.h`, a message
ID in the log, and a row of the mapping table in `src/libltfs/arch/errormap.c`.
This document describes the code spaces, the conventions the code follows
between the layers, the mapping at the boundary, the conditions that make a
volume read-only, and how a new code is added. It is one of the design
documents of `docs/developer/design/`; the components and layers document
gives the layering it refers to, and the path failover and revalidation
document covers the recovery after a path change in depth (both are
separate documents of the same directory).

## The code spaces

All error codes are defined in `src/libltfs/ltfs_error.h` and are returned
negated: a function returns `0` (or a positive count) on success and
`-LTFS_NO_DENTRY`, `-EDEV_WRITE_PERM` and so on when it fails. The absolute
value tells where the code comes from:

| Range | Prefix | Owner | Content |
|:--|:--|:--|:--|
| below `LTFS_ERR_MIN` (1000) | none | the C library | an `errno` value that was passed through unchanged |
| 1000 - 1207 | `LTFS_` | libaltfs | conditions of the library: arguments, paths and dentries, labels and indexes, volume state, plugins, the media changer code inherited from the reference implementation |
| 5000 - 5052 | `LTFS_XML_`, `LTFS_BAD_INDEX_TYPE` | libaltfs | the XML reader (`xml_reader.c`, `xml_reader_libltfs.c`): what was wrong in an index or label |
| 20000 - 29999 | `EDEV_` | the tape backends | device errors; `DEVICE_GOOD` (0) is success |
| 0x00 - 0xFF, bit mask | `PROG_` | the commands | process exit codes; `LTFSCK_*`, `MKLTFS_*` and `INDEXTOOL_*` are aliases of them |

The `LTFS_` numbers are allocated consecutively and never reused: retired
codes stay as a comment (`1030 (LTFS_DIRMOVE) retired`, `1174 - 1179
unused`), and `LTFS_ERR_MAX` (19999) closes the library space.

The `EDEV_` numbers encode the SCSI sense key: `20000 + sense key * 100 +
n`, with the generic code of a sense key at `n = 0`. Not ready is 202xx,
medium error 203xx, hardware error 204xx, illegal request 205xx, unit
attention 206xx, data protect 207xx, blank check 208xx, aborted command
211xx, volume overflow 213xx. Drive encryption errors are 216xx, errors
detected by the backend or the host rather than reported by the drive are
217xx (`EDEV_INTERNAL_ERROR`, `EDEV_DRIVER_ERROR`, `EDEV_NO_MEMORY`,
`EDEV_RESERVATION_CONFLICT`, `EDEV_CONNECTION_LOST`, `EDEV_NEED_FAILOVER`,
`EDEV_RETRY`, ...), and `EDEV_UNKNOWN` (29998) and `EDEV_VENDOR_UNIQUE`
(29999) close the space. The comment in the header states the rule for the
backends: a tape backend function returns `EDEV_` codes and nothing else.

`ltfs_error.h` also defines the classification macros that the layers above
use instead of comparing single codes: `IS_MEDIUM_ERROR()`,
`IS_HARDWARE_ERROR()`, `IS_UNIT_ATTENTION()`, `IS_READ_PERM()` and
`IS_WRITE_PERM()` (the last two include `EDEV_MEDIUM_FORMAT_CORRUPTED`).
`src/libltfs/tape.h` adds `NEED_REVAL()`, the set of codes after which the
cartridge may have been changed (power-on reset, medium may be changed,
reservation or registration preempted, real power-on reset, path failover),
and `IS_UNEXPECTED_MOVE()` (an operator asked for the medium to be removed).

## The message registry: AEI and AED

Every code has a message ID whose number is derived from the constant rather
than allocated: `AEI` plus the `LTFS_` value (`LTFS_RDONLY_VOLUME` = 1050 is
`AEI1050E`), `AED` plus the `EDEV_` value minus 20000 (`EDEV_WRITE_PERM` =
20309 is `AED0309E`). The texts live in `messages/internal_error/ei_root.txt`
and `ed_root.txt`; the `en` and `en_US` files of that directory are
intentionally empty, the root bundle is the text. Retired codes are kept as
`//unused AEI1030E:string { ... }`, as `messages/README` requires for every
released ID.

This registry is documentation and a consistency check, not log output. The
IDs appear in the source only in the mapping table of `errormap.c`, which is
what lets `validate_error_messages.py` treat them as used; the one function
that returns them, `errormap_msg_id()`, has no caller, so the running code
never prints an `AEI` or `AED` line. What the log shows is the message of the
layer that detected the problem, usually with the numeric code as an
argument (`ALP0051E Cannot write block: backend call failed (-20309)`); the
registry is where a reader turns that number into words.

`validate_error_messages.py` (repository root) cross-checks every message ID
in `src/**/*.[ch]` against the catalogs, and the `--enable-message-checker`
build of CI expands each `ltfsmsg()` against the catalog text so that the
compiler checks the arguments. Both run on every pull request.

## Where errors are born

### Tape backends

A backend turns the sense data of a failed command into an `EDEV_` code with
`_sense2errorcode()` (`src/tape_drivers/tape_drivers.h`). The sense key, ASC
and ASCQ are packed into one 24-bit value and looked up, first in
`standard_tape_errors[]` (`src/tape_drivers/vendor_compat.c`), then, when the
value is in a vendor-unique range (ASC or ASCQ at or above 0x80), in the
table of the drive vendor (`ibm_tape_errors[]`, `hp_tape_errors[]`,
`quantum_tape_errors[]`). Each row carries the code and a short text. An
unknown vendor-unique value stays `EDEV_VENDOR_UNIQUE`, any other unknown
value becomes `EDEV_UNKNOWN`. The sg backend adds two steps of its own in
`sg_sense2errno()` (`sg_scsi_tape.c`): an unknown hardware-error sense
(04/xxxx) becomes `EDEV_HARDWARE_ERROR`, and a result that is still
`EDEV_UNKNOWN` is logged with the raw value (`ATG0088I`).

The backend is also where a failed command is logged and where a drive dump
is taken. In the sg backend every CDB goes through `_process_errors()`
(`sg_tape.c`), which logs the command name, the table text and the code
(`ATG0064I`, or `ATG0065E` when there is no text), reconnects to the drive
on `EDEV_CONNECTION_LOST`, and takes a dump when `is_dump_required()` says
so: for codes between `EDEV_NOT_READY` and `EDEV_INTERNAL_ERROR` that are
not a drive-state notice, with the unforced dump added for medium and
hardware errors (`-o noautodump`, `global_data.disable_auto_dump`, turns this
off). Conditions that a command is expected to report are filtered before
that by `is_expected_error()` (`sg_scsi_tape.c`): a filemark on READ, early warning on WRITE, a
cleaning request, an encryption key the file system has not set; they reach
the tape layer as a code but are not logged as failures.

### The tape layer and libaltfs

`src/libltfs/tape.c` passes `EDEV_` codes up unchanged and adds `LTFS_` codes
for the conditions it owns: the read-only states of the next section, a block
larger than the drive allows (`LTFS_LARGE_BLOCKSIZE`), an unexpected position
after a locate (`LTFS_BAD_LOCATE`). The rest of libaltfs does the same: a
function returns the code of whatever failed below it, or one of its own
`LTFS_` codes for what it detected. A `NULL` argument is caught at the top of
most entry points by `CHECK_ARG_NULL()` (`ltfslogging.h`), which logs
`ALC0006E` with the argument and function names and returns the code given.
Expected conditions are returned as codes too and filtered by the caller:
every write path in `ltfs_fsops.c` continues on `-LTFS_LESS_SPACE` (the
programmable early warning, writes can go on) and stops on anything else.

### The FUSE bridge

`src/cmd/altfs/ltfs_fuse.c` keeps the library codes until the last line of
each operation and converts with `errormap_fuse_error()` there, after the
request trace has recorded the real code. This holds for the checks the
bridge makes itself: the macOS check of a read-only file returns
`-LTFS_RDONLY_FILE`, and the short cut for `system.` and `security.`
attributes returns `errormap_fuse_error(-LTFS_NO_XATTR)`. The few argument
checks that return `-EINVAL` directly (a non-zero xattr position on macOS)
work because the mapper passes `errno` values through, but they are the
exception, not the pattern.

## Conventions

- Zero or a count means success, a negative code means failure. `tape_write()`
  returns the bytes written, `ltfs_fuse_write()` returns the request size to
  FUSE; `DEVICE_GOOD` is 0.
- The code travels unchanged. A layer returns what it got, or replaces it
  with a code of its own when it knows better what the condition means to
  its caller (`ltfs_fsops_open()` turns `LTFS_INVALID_PATH` into
  `LTFS_INVALID_SRC_PATH`, so that a bad name on an existing-file operation
  is `ENOENT` and not `EINVAL`).
- The layer that detects a failure logs it, with its own context, and so do
  the layers above that add context of their own. A write that fails on the
  drive produces a chain: the backend's `ATG0065E` with the command, the tape
  layer's `ALP0051E` with the code and the note that the volume drops to
  read-only, `ALB0042E` from `ltfs_fsraw_write()`, and the caller's message
  (`ALB0034E Cannot unmount: failed to write an index` at unmount). Read the
  chain from the drive upwards; the first line names the command, the last
  what the user was doing. There is no rule that a code is logged exactly
  once, and no code path swallows a code silently: a function that returns a
  different code than it received has made a deliberate translation as
  above, and a function that passes a code on may log it with its context
  first (`ALI0001E` for a path that cannot be normalised).
- Retries belong to the backends. The sg backend retries a command after a
  kernel buffer allocation failure (`EDEV_BUFFER_ALLOCATE_ERROR`): it reads
  the position to learn whether the command reached the drive, spaces back
  when it did, and returns `EDEV_RETRY` to its own loop, up to `MAX_RETRY`
  times. `EDEV_RETRY` never leaves the backend. When the path to the drive
  changes (a reservation conflict after a host or fabric event), the backend
  re-registers its key, preempts the stale reservation and returns
  `EDEV_NEED_FAILOVER`; on a write it first checks with READ POSITION whether
  the block landed and reports success when it did.
- Revalidation belongs to libaltfs. When a code satisfies `NEED_REVAL()`,
  the caller in `ltfs.c`, `ltfs_fsops.c`, `ltfs_fsops_raw.c` or `xattr.c`
  calls `ltfs_revalidate()` and restarts the operation from the beginning
  (`goto start`). While it runs, `ltfs_get_volume_lock()` makes every other
  operation wait; when it fails, or when `IS_UNEXPECTED_MOVE()` holds,
  `vol->reval` is set to `-LTFS_REVAL_FAILED` and every operation that takes
  the volume lock gets that code (`EFAULT` to the application) until the
  volume is unmounted.

## The mapping to errno

`fuse_error_list[]` in `src/libltfs/arch/errormap.c` has one row per code:
the constant, its `AEI`/`AED` message ID and the `errno` value. `errormap_init()`
(called from `ltfs_fs_init()`) loads the rows into a hash table, and
`errormap_fuse_error(ret)` looks a negative code up: a value whose absolute
value is below `LTFS_ERR_MIN` is returned unchanged (it is already an
`errno`), a code without a row becomes `-EIO`. A few rows depend on the
platform: `ENOMEDIUM`, `ENOATTR` and `EUCLEAN` are used where the system
defines them, with `EAGAIN` or `ENODATA` otherwise.

The mapping is coarse by design. Most `LTFS_` codes become `EINVAL` or
`EIO`, and all the `LTFS_XML_` codes are `EINVAL`, so the application learns
that the operation failed and the log says why. The codes that carry a
meaning POSIX applications act on are mapped to it:

| Condition | Codes | errno |
|:--|:--|:--|
| name lookup | `LTFS_NO_DENTRY`, `LTFS_INVALID_SRC_PATH` | `ENOENT` |
| exists / not empty / too long | `LTFS_DENTRY_EXISTS`, `LTFS_DIRNOTEMPTY`, `LTFS_NAMETOOLONG` | `EEXIST`, `ENOTEMPTY`, `ENAMETOOLONG` |
| wrong kind of entry | `LTFS_ISFILE` | `ENOTDIR` |
| volume cannot be written | `LTFS_RDONLY_VOLUME`, `LTFS_WRITE_PROTECT`, `LTFS_WRITE_ERROR` | `EROFS` |
| volume full | `LTFS_NO_SPACE`, `LTFS_LESS_SPACE`, `LTFS_LARGE_XATTR` | `ENOSPC` |
| entry cannot be changed | `LTFS_RDONLY_XATTR`, `LTFS_RDONLY_ROOT`, `LTFS_RDONLY_FILE`, `LTFS_WORM_ENABLED` | `EACCES` |
| no such attribute | `LTFS_NO_XATTR` | `ENOATTR` or `ENODATA` |
| attribute buffer too small | `LTFS_SMALL_BUFFER` | `ERANGE` |
| needs the tape, index-only mount | `LTFS_INDEX_ONLY`, `LTFS_NO_INDEX` | `ENODATA` |
| try again | `LTFS_DEVICE_UNREADY`, `LTFS_REVAL_RUNNING`, `LTFS_DEVICE_FENCED`, the `EDEV_` not-ready family, `EDEV_DEVICE_BUSY` | `EAGAIN` |
| no cartridge | `LTFS_NO_MEDIUM`, `EDEV_NO_MEDIUM` | `ENOMEDIUM` (`EAGAIN` where the system has no `ENOMEDIUM`) |
| revalidation failed | `LTFS_REVAL_FAILED` | `EFAULT` |
| busy | `LTFS_UNLINKROOT`, `LTFS_OUTSTANDING_REFS`, `LTFS_CARTRIDGE_IN_USE` | `EBUSY` |
| drive timeout | `EDEV_TIMEOUT` | `ETIMEDOUT` |
| position | `EDEV_EOD_DETECTED`, `EDEV_EOD_NOT_FOUND`, `EDEV_RECORD_NOT_FOUND` | `ESPIPE` |
| rejected command, WORM overwrite | `EDEV_ILLEGAL_REQUEST`, `EDEV_INVALID_FIELD_CDB`, `EDEV_INTEGRITY_CHECK` | `EILSEQ` |
| unsupported drive or command | `EDEV_DEVICE_UNSUPPORTABLE`, `EDEV_UNSUPPORTED_FIRMWARE`, `EDEV_UNSUPPORETD_COMMAND` | `EOPNOTSUPP` |
| everything else from the drive | medium, hardware, unit attention, data protect, crypto, `EDEV_WRITE_PERM` | `EIO` |

The commands do not use this table. `mkaltfs`, `altfsck` and
`altfsindextool` return the `PROG_` bit mask: 0 success, 1 "treat as
success" (for `altfsck` the volume was corrected, which every check does
when it updates the MAM), 2 reboot required (defined, used by no command),
4 uncorrected, 8 an operational error from the
device or the library, 16 wrong arguments, 32 cancelled by the user, 64 a
library load error. The per-command aliases at the end of `ltfs_error.h` say
which of them each command uses; the man pages do not list them.

## Fatal conditions for a volume

Five states restrict writes on a mounted volume; the first three make it
read-only, the last two are the space states of a partition. `tape_read_only()` in
`tape.c` reports them, `ltfs_get_tape_readonly()` and
`ltfs_get_volume_readonly()` in `ltfs.c` add the volume-level ones, and
every write path asks before it starts:

| State | Set by | Code |
|:--|:--|:--|
| read-only mount, rollback mount | `-o ro` (`ltfs_set_readonly_mount()`), `-o rollback_mount` | `LTFS_RDONLY_VOLUME` |
| write-protected cartridge, MAM volume lock | the cartridge tab, `ltfs.volumeLockState`, `LOCKED_MAM` / `PERMLOCKED_MAM` | `LTFS_WRITE_PROTECT` |
| a write error happened | `dev->write_error`, see below; a `PWE_MAM_*` lock state at mount | `LTFS_WRITE_ERROR` |
| partition in early warning | `dev->partition_space[]` after a WRITE reported early warning | `LTFS_NO_SPACE` |
| partition in programmable early warning | likewise, programmable early warning | `LTFS_LESS_SPACE` (writes continue, new files are refused) |

**Write errors.** `tape_write()` and `tape_write_filemark()` set
`dev->write_error` when the backend fails for any reason other than a
`NEED_REVAL()` code, log `ALP0051E` / `ALP0053E`, and from then on refuse
every write with `-LTFS_WRITE_ERROR`. `tape_seek_append_position()` does the
same when it cannot reach the append position. The state is deliberate:
after a failed write the position on the tape is uncertain, and continuing
would risk the data already there. The index is the exception.
`ltfs_write_index()` clears `write_error` for its own duration when the data
partition got a permanent write error (`IS_WRITE_PERM()`), resets the append
position so that the index is appended and not written over existing
records, writes a full index on the other partition, records the state in
the MAM (`PWE_MAM_DP`, `PWE_MAM_IP`, `PWE_MAM_BOTH`), and sets `write_error`
again. A sync in that state writes the index on the index partition and
returns `-LTFS_SYNC_FAIL_ON_DP` (`EIO`) to the caller (`ALB0161I`), because
the file contents that were being written may not be on the tape. At the
next mount `ltfs_start_mount()` reads the lock state from the MAM, logs it
(`ALB0154I`) and sets `write_error` before any file operation, so the volume
comes up read-only and `altfsck` is the way back.

**A failed index write at unmount.** `ltfs_unmount()` writes the index on
the index partition when the volume is dirty or its last index is on the
data partition. A `NEED_REVAL()` failure is retried once through
`ltfs_revalidate()`; any other failure logs `ALB0034E`, leaves `vol->reval`
set when the medium was removed, and returns the code. The `altfs` daemon
calls `ltfs_unmount()` from the FUSE `destroy` callback, which has no way to
return a value, so the log is the only report; the tape is left with its
previous index (and the data-partition index when that was written) and
`altfsck` brings it back to consistency. The commands return the code as
`PROG_OPERATIONAL_ERROR`.

**Permanent revalidation failure.** When `ltfs_revalidate()` finds a
different cartridge, a label that does not match, or an end of data that
has moved, or when the operator requested removal of the medium, `vol->reval`
stays `-LTFS_REVAL_FAILED`. Only the unmount proceeds; it resets the flag
so that a later mount can start clean.

## Adding a new error code

New constants are added on `main` only; a release branch gets them by
backporting the change, so that the derived `AEI`/`AED` numbers never
diverge between lines (`messages/README`, "Release-branch ID shapes").

1. Pick the number. A library condition takes the next `LTFS_` value after
   the last one defined (`LTFS_RDONLY_FILE` is 1207 at the time of writing);
   a device condition goes into the `EDEV_` group of its sense key, or the
   217xx group when the backend or the host detects it. Add the `#define`
   with a one-line comment to `src/libltfs/ltfs_error.h`.
2. Add the row to `fuse_error_list[]` in `src/libltfs/arch/errormap.c`, in
   numeric order, with the message ID and the `errno` an application should
   see. Prefer the specific `errno` of the table above over `EIO` / `EINVAL`
   when one fits.
3. Add the catalog entry to `messages/internal_error/ei_root.txt` or
   `ed_root.txt`: `AEI1208E:string { "..." }`, the text in the style of the
   header comment. `make` regenerates the bundle objects.
4. Run `python3 validate_error_messages.py` from the repository root; it
   reports a code that is in one place and not the other.
5. Return the code negated from the function that detects the condition,
   log a message of that component with the context that identifies the
   failing object, and let the callers pass the code through.

To retire a code: comment it out in `ltfs_error.h` with a note, remove its
row from `errormap.c`, and keep the catalog entry commented out with the
`unused` marker, as `AEI1030E` shows. The number is never reused.

## Things worth knowing when reading the code

- `fuse_error_list[]` lists `EDEV_DRIVER_ERROR` twice; the second row is
  never reached.
- `mkaltfs.c` returns `LTFSCK_OPERATIONAL_ERROR` in one place. It has the
  same value as `MKLTFS_OPERATIONAL_ERROR`, so the exit code is right.
- The first write that fails on the drive returns the device code
  (`EDEV_WRITE_PERM`, `EIO`); every write after it returns
  `LTFS_WRITE_ERROR` (`EROFS`). An application therefore sees two different
  `errno` values for one event.
- The `AEI`/`AED` texts are not printed by any code path; they are read by
  people. A message in the log carries the numeric code instead.
- `errormap.c` still carries the note that a Windows mapping is to be
  defined; `general_error` is an `errno` on every supported platform.
