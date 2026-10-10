# Backend interfaces

libaltfs talks to everything outside itself through plugins: shared
libraries loaded at start that each implement one function table. There are
four tables, declared in `src/libltfs/`:

| Kind | Table | Declared in | Dispatch layer | Implementations |
|:---|:---|:---|:---|:---|
| Tape backend | `struct tape_ops` | `tape_ops.h` | `tape.c` | `src/tape_drivers/` (`sg`, `iokit`, `cam`, `scsipi-ibmtape`, `file`, `itdtimg`) |
| I/O scheduler | `struct iosched_ops` | `iosched_ops.h` | `iosched.c` | `src/iosched/` (`unified`, `fcfs`) |
| Dentry cache | `struct dcache_ops` | `dcache_ops.h` | `dcache.c` | none in this tree |
| Key manager (KMI) | `struct kmi_ops` | `kmi_ops.h` | `kmi.c` | `src/kmi/` (`simple`, `flatfile`) |

The dispatch layer is the only code that holds a pointer to the table. The
rest of libaltfs calls `tape_*()`, `iosched_*()`, `dcache_*()` and `kmi_*()`
functions, and that is where the locking, the retries and the state that is
common to every implementation live. This document describes each table:
when its operations are called, what they must return and what the dispatch
layer does around them. How a FUSE request travels through these layers is
the subject of the components design document (`COMPONENTS.md`).

## Loading a plugin

`altfs.conf` registers every plugin with a `plugin TYPE NAME PATH` line and
names the default of each kind with `default TYPE NAME` (the file and its
local companion are described in the
[configuration guide](../../user/CONFIGURATION.md)). `plugin_load()` in
`src/libltfs/plugin.c` looks the path up by type and name, `dlopen()`s it and
resolves two symbols:

| Type | Table symbol | Message bundle symbol |
|:---|:---|:---|
| `tape` | `tape_dev_get_ops` | `tape_dev_get_message_bundle_name` |
| `iosched` | `iosched_get_ops` | `iosched_get_message_bundle_name` |
| `dcache` | `dcache_get_ops` | `dcache_get_message_bundle_name` |
| `kmi` | `kmi_get_ops` | `kmi_get_message_bundle_name` |

Both symbols are required; a missing one is `-LTFS_PLUGIN_LOAD`. The table
function returns the address of a statically initialised `struct`. The
message function returns the name of the plugin's ICU message bundle and a
pointer to its compiled data (the `AT*`, `AIU*`, `AKS*`, ... messages under
`messages/`), or `NULL` when the plugin has none; a bundle is registered with
`ltfsprintf_load_plugin()` so that `ltfsmsg()` resolves the plugin's IDs.
`plugin.c` also knows the names `changer` and `crepos`; nothing in this tree
implements them.

Every table is complete or the plugin is rejected: the dispatch layer walks
the table as an array of pointers and fails with `-LTFS_PLUGIN_INCOMPLETE`
when one is `NULL` (`tape_device_open()`, `iosched_init()`, `kmi_init()`,
`dcache_init()`). A backend that does not support an operation implements it
and returns an error code (`-EDEV_UNSUPPORTED_FUNCTION` for a drive
operation), or does nothing and returns 0 where the interface says that is
acceptable.

### Who loads what, and when

`altfs` (`src/cmd/altfs/altfs.c`) loads the tape, I/O scheduler and KMI
plugins before anything else, picks them from `-o tape_backend=`,
`-o iosched_backend=` and `-o kmi_backend=` or the `default` lines, and
treats the name `none` as "no scheduler" / "no key manager". Then, in order:

1. `ltfs_volume_alloc()` allocates the volume and its `struct device_data`
   (`tape_device_alloc()`).
2. `ltfs_device_open()` calls `tape_device_open()` with the tape table: this
   is where the table is validated, the device opened and reserved.
3. The tape backend's `parse_opts()` gets the remaining `-o` options
   (`ltfs_parse_tape_backend_opts()`), then `kmi_init()` and the KMI's
   `parse_opts()` if a key manager is configured.
4. `ltfs_setup_device()` sets the mode pages (programmable early warning,
   append-only mode), and `ltfs_mount()` loads the tape and reads the index.
5. `iosched_init()` is called from the FUSE `init` callback
   (`src/cmd/altfs/ltfs_fuse.c`), once the volume is mounted and the block
   size is known, and `iosched_destroy()` / `kmi_destroy()` from `destroy`.

`mkaltfs`, `altfsck` and `altfsindextool` load the tape plugin named by
`-e` (`--backend`) and the KMI named by `--kmi-backend`, and never load an
I/O scheduler: they write through `ltfs_fsraw_*` directly. The `-o` options
of a backend are parsed with libfuse's `fuse_opt_parse()` in every command,
which is why `fuse_opt` appears in the plugins and in `tape_ops.h`.

Every plugin's `parse_opts()` receives a `struct fuse_args` and must leave
the options it does not know in place (the `null_parser` callbacks return 1),
because the same argument list is passed to each plugin and then to libfuse.
`help_message()` is called by `altfs -h` and the other commands' `-h` for
every registered plugin of the type (`plugin_usage()`).

## Tape backend (`struct tape_ops`)

The tape backend turns the operations libaltfs needs into whatever the
platform offers: SCSI pass-through for a drive (`sg` on Linux, `iokit` on
macOS, `cam` on FreeBSD, `scsipi-ibmtape` on NetBSD), files in a directory for
the emulated tape (`file`), or a tape image written by IBM's ITDT (`itdtimg`,
read-only: its `write()` and `writefm()` return `-EDEV_WRITE_PROTECTED`). The
table has 56 operations; every implementation fills all of them.

### Contract

- **Handle.** `open()` returns an opaque handle that every other operation
  receives as its first argument. `tape.c` keeps it in
  `device_data.backend_data` and never looks inside.
- **Return values.** 0 on success, a negative error code otherwise, with the
  exceptions noted in the table (`read()` returns the byte count,
  `logsense()` and `modesense()` a length, `get_eod_status()` an `enum
  eod_status`, `is_mountable()` a `MEDIUM_*` value, `is_readonly()` a
  `bool`, `get_device_list()` a count). Error codes are the `EDEV_*`
  constants of `src/libltfs/ltfs_error.h` (20000 and up), negated. They are
  grouped by SCSI sense key, so `tape.c` can classify them with
  `IS_MEDIUM_ERROR()`, `IS_HARDWARE_ERROR()`, `IS_WRITE_PERM()`; the message
  IDs `AED2xxxxE` are derived from them (see `messages/README`). A backend
  may also return an `LTFS_*` code where the interface says so
  (`-LTFS_UNSUPPORTED_MEDIUM` from `load()`).
- **Position.** The operations that move the tape take a `struct
  tc_position *pos` and must fill it with the final position, on error as
  well. `tape.c` passes `&dev->position` and trusts it: after `read()` and
  `write()` the block number must have advanced by exactly one, and after
  `locate()` it must equal the destination or `tape.c` treats the call as
  failed. `write()` must also raise `programmable_early_warning` and
  `early_warning` in `pos` when the drive reports them; they drive the
  `PART_LESS_SPACE` / `PART_NO_SPACE` state that stops user writes while
  leaving room for the index.
- **One block per call.** `read()` reads exactly one logical block (0 with
  the position just past a filemark when it meets one) and `write()` writes
  the buffer as exactly one block. The block size is the volume's, up to the
  drive's `max_blksize` from `get_parameters()`; `tape_write()` refuses a
  larger buffer with `-LTFS_LARGE_BLOCKSIZE`.
- **Revalidation codes.** Six codes mean "the path or the medium may have
  changed, repeat the command after revalidating": `EDEV_POR_OR_BUS_RESET`,
  `EDEV_MEDIUM_MAY_BE_CHANGED`, `EDEV_RESERVATION_PREEMPTED`,
  `EDEV_REGISTRATION_PREEMPTED`, `EDEV_REAL_POWER_ON_RESET` and
  `EDEV_NEED_FAILOVER` (the `NEED_REVAL()` macro in `tape.h`). The dispatch
  layer retries the housekeeping commands itself (`load()`, `rewind()`,
  `unload()`, `reserve_unit()`, `release_unit()`, medium removal) and lets
  the data path return the code to `ltfs.c`, which fences the device
  (`tape_start_fence()`), runs `ltfs_revalidate()` and repeats the request.
  `EDEV_MEDIUM_REMOVAL_REQ` (`IS_UNEXPECTED_MOVE()`) is final: the volume
  goes to the failed state and only an unmount is accepted.
- **No SCSI in `get_info()`.** It reports what `open()` learned; `tape.c`
  calls it while checking a connection.

### Operations

| Group | Operations | Called from `tape.c` |
|:---|:---|:---|
| Device | `open`, `reopen`, `close`, `close_raw`, `is_connected`, `get_device_list`, `get_info`, `get_serialnumber`, `default_device_name`, `help_message`, `parse_opts` | `tape_device_open()` opens, reserves (three attempts a second apart), releases the medium lock and reads the serial. `close_raw()` closes only the OS handle and `reopen()` restores it: `altfs` uses the pair around its fork, so the child that serves requests owns the descriptor. `is_connected()` tells whether the device named at open is still there. |
| Readiness | `test_unit_ready`, `inquiry`, `inquiry_page`, `get_parameters`, `is_mountable`, `is_readonly`, `get_worm_status` | `tape_test_unit_ready()` is called before most file system operations; `tape_wait_device_ready()` loops on it at load, loading the tape when the drive answers `EDEV_NEED_INITIALIZE`. `get_parameters()` gives the maximum block size, write protect and encryption state. `is_mountable()` compares cartridge type and density with what the drive can do (`MEDIUM_PERFECT_MATCH`, `MEDIUM_WRITABLE`, `MEDIUM_READONLY`, `MEDIUM_CANNOT_ACCESS`, `MEDIUM_PROBABLY_WRITABLE`); `is_readonly()` says whether this drive generation can only read the loaded cartridge. |
| Medium | `load`, `unload`, `prevent_medium_removal`, `allow_medium_removal`, `set_default` | `tape_load_tape()`: `load()` (`-EDEV_NO_MEDIUM` becomes `-LTFS_NO_MEDIUM`, `-EDEV_MEDIUM_FORMAT_ERROR` becomes `-LTFS_UNSUPPORTED_MEDIUM`), wait for ready, lock the medium, `readpos()`, `set_default()` (variable block size and the like), clear the key, read the capacity and the parameters, then set the per-partition space state from the capacity and the programmable early warning size. `tape_unload_tape()` unlocks, rewinds, unloads and turns append-only mode off. |
| Positioning | `rewind`, `locate`, `space`, `readpos`, `get_next_block_to_xfer` | `tape_seek()`, `tape_seek_eod()`, `tape_spacefm()`, `tape_rewind()`. `space()` is only used with filemarks (`TC_SPACE_FM_F` / `TC_SPACE_FM_B`); `TC_SPACE_EOD` and record spacing exist in the enum but are not issued. `get_next_block_to_xfer()` reports the first block still in the drive's buffer, which is where the data is cut after a permanent write error. |
| Data | `read`, `write`, `writefm`, `erase` | `tape_read()`, `tape_write()`, `tape_write_filemark()`, `tape_erase()`; see below. |
| Capacity and format | `remaining_capacity`, `setcap`, `format`, `get_eod_status` | `remaining_capacity()` returns the two partitions' remaining and maximum capacity in MiB, cached by `tape_get_capacity()` (below). `setcap()` and `format()` are always preceded by a locate to partition 0, block 0; `format()` takes `TC_FORMAT_DEFAULT` (one partition) or `TC_FORMAT_DEST_PART` (two). `get_eod_status()` returns `EOD_GOOD`, `EOD_MISSING` or `EOD_UNKNOWN`, which the mount uses to decide whether a recovery is needed. |
| Mode and log pages | `modesense`, `modeselect`, `logsense`, `set_compression`, `allow_overwrite` | `tape.c` reads and writes the Device Configuration Extension page for the programmable early warning size (`tape_set_pews()`) and append-only mode (`tape_enable_append_only_mode()`), the Read/Write Control page for the density, and the Medium Partition page at format. `allow_overwrite()` sets the append point in append-only mode. `logsense()` serves `tape_logsense()` for the vendor attributes; `set_compression()` returns 0 where compression does not exist. |
| MAM | `read_attribute`, `write_attribute` | The volume change reference (`TC_MAM_PAGE_VCR`), the cartridge coherency attributes written at every index (`tape_set_cart_coherency()`), and the application, label, barcode and media pool attributes (`tape_set_attribute_to_cm()` and friends). A backend without MAM support zeroes the buffer and returns a negative value. |
| Reservation | `reserve_unit`, `release_unit` | `tape_reserve_device()` at open and again at revalidation; `tape_release_device()` at close. The hardware backends use persistent reservations (exclusive access, a key derived from the host) and preempt a stale reservation of their own key. |
| Health | `get_cartridge_health`, `get_tape_alert`, `clear_tape_alert`, `takedump_drive`, `get_xattr`, `set_xattr` | The `ltfs.*` virtual extended attributes of the volume root read these; tape alerts are latched by the backend until `clear_tape_alert()`. `takedump_drive()` saves a drive dump into the work directory; the hardware backends also take one on their own after an error unless `-o noautodump` is given. |
| Encryption | `set_key`, `get_keyalias` | `tape_set_key()` sends the data key the KMI returned; `tape_read()` asks `get_keyalias()` for the key identifier of the next block when a read fails with `-EDEV_CRYPTO_ERROR` or `-EDEV_KEY_REQUIRED`, fetches that key from the KMI and retries once. Setting a key while not at the beginning of a partition forces the volume read-only. |
| Recommended access order | `grao`, `rrao` | `tape_rao_request()`, for `altfs_ordered_copy` through the `ltfs.vendor.*` attributes. |
| Profiler | `set_profiler` | Starts and stops the driver profile (`prof_driver_*.dat` in the work directory, through the `ltfs.vendor.Aurora.profiler` attribute); each operation then records an ENTER and an EXIT entry tagged with its `REQ_TC_*` code from `tape_ops.h`. |

### What the dispatch layer adds

`struct device_data` (`tape.h`) holds the state that every backend shares:
the current position, the append position of each partition, the maximum
block size, the write protect and space state per partition, the
reservation and medium lock flags, and the two caches below. Its functions
expect the caller to hold the **device lock** (`tape_device_lock()` on
`backend_mutex`); `ltfs.c` takes it around every sequence of tape calls and
`tape_start_fence()` makes further lock requests fail with
`-LTFS_DEVICE_FENCED` while a revalidation runs.

**Writes.** `tape_write()` refuses before calling the backend when the
cartridge is write protected, when an earlier write failed (`write_error`
is set by the first non-revalidation write error and stays until unload),
when the partition is out of space, or when the buffer is larger than the
block size. After a successful write it records the append position, adds
the bytes to the capacity cache's counter and, when the backend raised an
early warning flag, updates the partition's space state and returns
`-LTFS_NO_SPACE` or `-LTFS_LESS_SPACE` unless the caller asked to ignore
them (index writes do).

**TEST UNIT READY is skipped for a second.** `tape_test_unit_ready()`
returns 0 without asking the drive when a command that needs a ready
medium succeeded within the last second: `previous_exist` is set after a
successful `read()`, `write()`, `writefm()`, `locate()`, `space()`,
`rewind()`, `erase()`, `remaining_capacity()` and TEST UNIT READY itself,
and cleared by close and unload. A sequence of file system requests on a
busy drive therefore costs no readiness probes.

**The remaining capacity is cached.** `tape_get_capacity()` returns the
drive's last answer as it is, and asks again only when
`TAPE_CAPACITY_REFRESH_BYTES` (1 GiB) have been written since, or when
something has been written since and the answer is
`TAPE_CAPACITY_REFRESH_SEC` (10 s) old. The figure is never adjusted by the
bytes written: the drive compresses, and the position of the head does not
change the remaining capacity, so locate, space and rewind leave the cache
alone. It is dropped by what changes the medium or its capacity: a
filemark, load, unload, format, erase, `tape_reset_capacity()`, closing the
device (`_tape_device_close()` and `tape_device_close_raw()`, so a reopened
device starts without a cached figure), and a write that hits an early
warning, where the exact figure matters. Without it a file system layer that asks for the
volume statistics after every request keeps the drive busy with LOG SENSE
between the writes.

### The existing backends

| Backend | Platform | Notes |
|:---|:---|:---|
| `sg` (`src/tape_drivers/linux/sg/`) | Linux, `/dev/sgN` or drive serial | SCSI pass-through through the sg driver. Options `-o scsi_lbprotect=on\|off`, `-o autodump` / `-o noautodump`, `-o strict_drive` (strict barcode length check). Reconnects on `EDEV_CONNECTION_LOST`. |
| `iokit` (`osx/iokit/`) | macOS, index of the drive in the device list | SCSITask user client; same options as `sg`. |
| `cam` (`freebsd/cam/`) | FreeBSD, `/dev/saN` (default `/dev/sa0`) | CAM pass-through; same options. |
| `scsipi-ibmtape` (`netbsd/scsipi-ibmtape/`) | NetBSD | scsipi pass-through; same options. |
| `file` (`generic/file/`) | any, a directory (default `/tmp/ltfs/tape`) | The emulated tape of the test suites. Each record is a file; the cartridge is described by `filedebug_tc_conf.xml` in the directory (capacity, cartridge type, density code, read-only, dummy I/O, delay emulation, a host transfer limit; see `examples/filedebug_tc_conf.xml`). Takes `-o strict_drive`. |
| `itdtimg` (`generic/itdtimg/`) | any, an ITDT image file | Read-only. |

The hardware backends share `src/tape_drivers/*.c`: the sense-to-code tables
(`vendor_compat.c`, `ibm_tape.c`, `hp_tape.c`, `quantum_tape.c`, with the
`_sense2errorcode()` lookup in `tape_drivers.h` that turns sense key, ASC
and ASCQ into an `EDEV_*` code and a message), the command timeouts per
drive generation, the supported-drive tables, the reservation key and the
CRC code for logical block protection (`crc32c_crc.c`,
`reed_solomon_crc.c`). A new hardware backend is mostly the pass-through
mechanism and the device enumeration; the SCSI knowledge is already there.

## I/O scheduler (`struct iosched_ops`)

The scheduler sits between `ltfs_fsops.c` and `ltfs_fsraw.c`. Without one
(`-o iosched_backend=none`, and always in `mkaltfs`, `altfsck` and
`altfsindextool`), `ltfs_fsops_read()`, `ltfs_fsops_write()` and the others
call `ltfs_fsraw_*` directly and every write becomes a tape block of its
own. With one, every file operation that touches data goes through the
table:

| Operation | Called from | Must do |
|:---|:---|:---|
| `init(vol)` | FUSE `init`, after the mount | Return the scheduler handle, or `NULL`, after which every file system callback fails with `-LTFS_IOSCHED_INIT` until the volume is unmounted. The block size (`vol->label->blocksize`) and the cache limits (`ltfs_min_cache_size()`, `ltfs_max_cache_size()`, the `-o min_pool_size` / `-o max_pool_size` options in MiB) are known at this point. |
| `destroy(handle)` | FUSE `destroy` | Flush everything and free. |
| `open(path, open_write, &dentry, handle)` | `ltfs_fsops_open()` | Open through `ltfs_fsraw_open()` and set up per-file state. |
| `close(dentry, flush, handle)` | `ltfs_fsops_close()` | Flush the file's pending data when `flush` is set, close through `ltfs_fsraw_close()`, report a write error that happened in the background. |
| `read(dentry, buf, size, offset, handle)` | `ltfs_fsops_read()` | Return the bytes, serving what is still in the write queue from memory and the rest with `ltfs_fsraw_read()`. |
| `write(dentry, buf, size, offset, isupdatetime, handle)` | `ltfs_fsops_write()` | Queue the bytes. Returns the number of bytes accepted; `iosched_write()` clips it to `size`. |
| `flush(dentry or NULL, closeflag, handle)` | `ltfs_fsops_flush()`, and before an index is written | Write the pending data of one file, or of every file, to the tape. After a full flush no data partition request may be left. |
| `truncate(dentry, length, handle)` | `ltfs_fsops_truncate()` | Cut or extend the queued data and the file. |
| `get_filesize(dentry, handle)` | `ltfs_fsops_getattr()` | The size including the queued writes. |
| `update_data_placement(dentry, handle)` | after a rename or an unlink | Re-evaluate whether the file's data belongs on the index partition: the rules match on the name, and a deleted file leaves it. |
| `set_profiler(work_dir, enable, handle)` | `ltfs.vendor.Aurora.profiler` | Start or stop the scheduler profile (`prof_iosched_*.dat`); entries carry the `REQ_IOS_*` codes. |

The scheduler must take the volume lock (`ltfs_get_volume_lock()`) before
touching the volume, as any other caller does, and may hold a per-dentry
lock of its own (`dentry->iosched_lock`, `dentry->iosched_priv`, both
reserved for it in `struct dentry`).

### The unified scheduler

`src/iosched/unified.c` is the one to use. It has two jobs: turn the small
writes the kernel sends into full tape blocks, and keep the files that the
data placement rules select (`-o rules=`, `mkaltfs -r`) on the index
partition as well.

- **Requests and the cache pool.** Each write becomes, or is merged into, a
  `write_request` that owns one cache block of the volume's block size,
  allocated from `cache_manager.c` (a pool that grows from the minimum to
  the maximum pool size and never beyond). A request is `REQUEST_PARTIAL`
  while its block is not full, `REQUEST_DP` when it is, and `REQUEST_IP`
  once it has been written to the data partition and still has to go to the
  index partition. The requests of a file are kept sorted by offset in its
  `dentry_priv`; a write that overlaps or covers existing requests updates
  them, and a write that covers an `REQUEST_IP` request truncates, splits or
  removes it, so that old bytes are never flushed after new ones.
- **The writer thread.** `_unified_writer_thread()` wakes up when a file
  has full requests (`dp_queue`) or when a writer is waiting for a cache
  block. It writes the full requests of the data partition first; under
  cache pressure it also flushes partial requests (the `working_set`), and
  it drains the index partition queue when it holds more than
  `IP_HIGH_WATERMARK` (60 %) of the cache blocks. Data goes to the tape
  with `ltfs_fsraw_write()`, which appends the block and adds the extent to
  the file; the index partition copy with `ltfs_fsraw_write_data()`, whose
  extents are collected in an alternate extent list and swapped into the
  file when its last handle is closed, provided it still matches the rules.
- **Errors.** A write error in the background is kept in the `dentry_priv`
  and returned by the next `write()`, `flush()` or `close()` of that file.
  A permanent write error on the data partition
  (`_unified_write_index_after_perm()`) is recorded in the MAM
  (`tape_set_cart_volume_lock_status()`), the extents that point past the
  first block the drive did not transfer are cut back, and a full index is
  written to the index partition at once; the same error on the index
  partition is recorded in the MAM and left to the next index write.
- **Reads** are served from the queued requests where they overlap and from
  the tape (`ltfs_fsraw_read()`) elsewhere; the tape reads are issued after
  the dentry lock is released.
- **Locking.** A reader-writer lock over the whole scheduler (`priv->lock`,
  taken for write by a full flush and by the index partition writer), a
  queue lock for the three lists, a cache lock around the pool, and per
  file `dentry->iosched_lock` and `dentry_priv->io_lock`. The order is
  documented at the top of the `unified_data` structure; the queue lock is
  the innermost.

`src/iosched/fcfs.c` is the sample: one mutex, and every operation passes
straight to `ltfs_fsraw_*`. It shows the minimum a scheduler has to do and
is not meant for use.

## Dentry cache (`struct dcache_ops`)

`dcache_ops.h` declares a cache of the directory tree on disk, so that a
volume's metadata can be served without the tape and survive between
mounts: lifecycle and work directory, the validation metrics (volume UUID,
index generation, dirty flag), a disk image, advisory locks, and a full set
of file system operations (`open`, `openat`, `close`, `create`, `unlink`,
`rename`, `flush`, `readdir`, the extended attribute operations). `dcache.c`
is the dispatch layer, and `ltfs_fsops.c` and `ltfs_fsops_raw.c` call it
behind `dcache_initialized()` checks at every operation that changes a
dentry.

Nothing in this tree implements the table or calls `dcache_init()`, so
`dcache_initialized()` is always false and those branches are dead code.
The `option dcache` lines that `config_file.c` accepts are parsed and
unused. The interface is kept for the library edition it was designed for;
a new implementation would be loaded like the other plugins and initialised
before the mount, because the cache has to be consulted while the index is
read.

## Key manager (`struct kmi_ops`)

A drive that encrypts needs a data key (DK, 32 bytes) and a data key
identifier (DKi, 12 bytes). The KMI plugin supplies the pair and knows
nothing about the tape:

| Operation | Called from | Must do |
|:---|:---|:---|
| `init(vol)` | `kmi_init()`, after the device is open | Return the handle. |
| `destroy(handle)` | FUSE `destroy`, or the command's exit | Free it. Keys are wiped from memory. |
| `get_key(&keyalias, &key, handle)` | `ltfs_format_tape()`, and `tape_read()` on `-EDEV_CRYPTO_ERROR` / `-EDEV_KEY_REQUIRED` | With `*keyalias` set, return the key of that identifier (`-LTFS_KEY_NOT_FOUND` when there is none). With `*keyalias` `NULL`, return the pair to format with, or `*key == NULL` and 0 for a plain cartridge. The buffers are allocated by the plugin and freed by the caller. |
| `help_message()` | `-h` | Print the plugin's options. |
| `parse_opts(args)` | right after `kmi_init()` | Take the plugin's `-o` options out of the argument list. |

`tape_set_key()` passes the pair to the tape backend's `set_key()`;
`tape_clear_key()` sends `NULL`s at load and close, and a key set while the
head is not at the beginning of a partition forces the volume read-only,
because a cartridge with several keys, or with plain and encrypted data, is
not compatible with the drive's library- and system-managed encryption.

The two plugins share `src/kmi/key_format_ltfs.c`, which parses the list
`DK:DKi/DK:DKi/...` (the DK in Base64, the DKi as 3 ASCII characters and
9 bytes in hexadecimal) and picks the pair:

- `simple` (`simple.c`) takes the list from `-o kmi_dk_list=`, or builds it
  from `-o kmi_dk=` / `-o kmi_dki=` and `-o kmi_dk_for_format=` /
  `-o kmi_dki_for_format=`.
- `flatfile` (`flatfile.c`) takes `-o kmi_dk_list=<file>` and converts the
  file (`DK=` and `DKi=` lines) into the same list the first time
  `get_key()` is called; `-o kmi_dki_for_format=` names the pair to format
  with.

The pair is cleared after every `get_key()`; the flat file is kept in memory
so that a key can be looked up again after a drive power-on reset.

## Adding a backend

1. Implement every function of the table and the two symbols; the `file`
   backend is the most readable tape example, `fcfs` the scheduler one,
   `simple` the KMI one.
2. Return the codes the dispatch layer understands: `-EDEV_*` from a tape
   backend (add a constant to `ltfs_error.h` and its `AED` message when no
   existing code fits), `-LTFS_*` elsewhere.
3. Give the plugin a message bundle under `messages/` with a component code
   of its own, or return `NULL`.
4. Add it to `Makefile.am` of its directory, to `conf/altfs.conf.in`, and to
   the package lists, so that `plugin TYPE NAME PATH` finds it.
5. Run the suites in `tests/` against it; the file backend tests show what
   libaltfs expects of a tape backend.
