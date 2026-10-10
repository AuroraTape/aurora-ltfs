# Components and layers

How a file system call reaches the tape, what the pieces are called in the
source tree, and which structures and locks hold a mounted volume together.
This is the first document to read before changing libaltfs; the contracts
of the plugin interfaces are described separately in the backend-interfaces
design document (`docs/developer/design/BACKENDS.md`), and the paths that
react to a lost drive or a changed cartridge in the revalidation document.

## The pieces

Everything that understands the LTFS format is in one shared library,
libaltfs (`src/libltfs/`). The commands link it; the plugins are loaded by
it at run time.

| Piece | Source | What it is |
|:--|:--|:--|
| `altfs` | `src/cmd/altfs/` | The FUSE daemon: option parsing and start-up in `altfs.c`, the FUSE-to-libaltfs bridge in `ltfs_fuse.c` |
| `mkaltfs` | `src/cmd/mkaltfs/` | Formats a cartridge: partitions, labels, the first index on both partitions (`ltfs_format_tape()`), or wipes it (`ltfs_unformat_tape()`) |
| `altfsck` | `src/cmd/altfsck/` | Checks and repairs a volume: mounts with the recovery flags of `ltfs_mount()`, recovers a missing EOD, rolls back to an earlier index generation with `ltfs_traverse_index_*()` and `ltfs_write_index()` |
| `altfsindextool` | `src/cmd/altfsindextool/` | Reads the indexes off a partition into files, or checks an index file against the volume, without mounting |
| `altfsctl` | `src/cmd/altfsctl/` | Python; sets up the Linux `altfs@<serial>.service` unit, no libaltfs involved |
| `altfs_ordered_copy` | `src/cmd/altfs_ordered_copy/` | Python; copies files in tape order using the `ltfs.*` extended attributes of a mounted volume |
| libaltfs | `src/libltfs/` | The library: volume, index and dentry structures, the file system operations, the tape layer, index XML, plugin loading, messages and tracing |
| tape backends | `src/tape_drivers/` | One plugin per operating system interface: `linux/sg`, `osx/iokit`, `freebsd/cam`, `netbsd/scsipi-ibmtape`, and the drive-less `generic/file` (a directory that emulates a cartridge) and `generic/itdtimg` (a drive dump image). Vendor-specific tables and helpers shared by all of them are in `ibm_tape.c`, `hp_tape.c`, `quantum_tape.c` and `vendor_compat.c` |
| I/O schedulers | `src/iosched/` | `unified.c`, the default scheduler, and `fcfs.c`, a minimal first-come-first-served implementation that `-o iosched_backend=fcfs` selects; it exists as a reference, not for use |
| key managers | `src/kmi/` | `simple.c` (the key comes from the mount options) and `flatfile.c` (from a file) |

The commands never open the drive themselves. Each one allocates a
`struct ltfs_volume`, loads the plugins named in `altfs.conf`, opens the
device through the tape layer (`ltfs_device_open()`) and then calls the
volume-level functions of `ltfs.c`: `ltfs_mount()`, `ltfs_format_tape()`,
`ltfs_write_index()`, `ltfs_unmount()`. Only `altfs` goes further and
serves file operations.

## Layers of a file operation

```
  application                     (read(2), write(2), stat(2), ...)
       |
  kernel / FUSE                   Linux fuse, macFUSE (kernel extension or FSKit)
       |
  +--------------------------------------------------------------------------+
  |  altfs: FUSE bridge                      src/cmd/altfs/ltfs_fuse.c       |
  |  struct fuse_operations ltfs_ops; one handler per FUSE call;             |
  |  open-file table; errno conversion with errormap_fuse_error()            |
  +--------------------------------------------------------------------------+
       |  ltfs_fsops_*()                       libaltfs error codes (-LTFS_*)
  +--------------------------------------------------------------------------+
  |  libaltfs: file system operations         src/libltfs/ltfs_fsops.c       |
  |  path lookup, dentry tree, attributes, xattrs (xattr.c), rename, unlink; |
  |  takes the volume lock, waits for revalidation                           |
  +--------------------------------------------------------------------------+
       |  iosched_open/read/write/flush/close  (iosched.c -> plugin)
  +--------------------------------------------------------------------------+
  |  I/O scheduler plugin                      src/iosched/unified.c         |
  |  write requests queued per file in cache blocks of one tape block;       |
  |  a writer thread writes them in order; reads pass through                |
  +--------------------------------------------------------------------------+
       |  ltfs_fsraw_read/write()
  +--------------------------------------------------------------------------+
  |  libaltfs: raw format layer               src/libltfs/ltfs_fsops_raw.c   |
  |  extents <-> tape blocks: seek to the block of an extent, read it;       |
  |  append a block, record the extent in the dentry, mark the index dirty   |
  +--------------------------------------------------------------------------+
       |  tape_read/write/seek/...             (tape.c, device lock)
  +--------------------------------------------------------------------------+
  |  libaltfs: tape layer                      src/libltfs/tape.c            |
  |  one struct device_data per drive; position, capacity, TUR and MAM       |
  |  caches; retries and revalidation on the EDEV_* codes that need it       |
  +--------------------------------------------------------------------------+
       |  struct tape_ops                      (tape_ops.h, 56 operations)
  +--------------------------------------------------------------------------+
  |  tape backend plugin                       src/tape_drivers/<os>/<name>  |
  |  builds the SCSI CDBs and talks to the OS pass-through interface        |
  +--------------------------------------------------------------------------+
       |
  tape drive
```

Each layer only calls the one below it, and the plugins are reached through
function tables, never by name. Everything from the bridge down to the tape
backend runs in the `altfs` process; the FUSE library calls the bridge from
its own worker threads, so every layer must be thread safe.

### The FUSE bridge

`ltfs_fuse.c` fills `struct fuse_operations ltfs_ops`, one handler per FUSE
operation the daemon supports (plus `setattr_x` and `fsetattr_x` on macOS).
Each handler fetches the daemon's state,
`struct ltfs_fuse_data`, from `fuse_get_context()->private_data`, converts
the FUSE arguments (paths, `struct stat`, open flags), calls one or a few
`ltfs_fsops_*()` functions, and converts the result at the boundary with
`errormap_fuse_error()` (`src/libltfs/arch/errormap.c`): a libaltfs code
such as `-LTFS_RDONLY_FILE` becomes `-EACCES`, an unknown code `-EIO`, and
a value that already looks like an errno is passed through. The bridge
itself never returns `-errno` from libaltfs paths.

The bridge keeps the only state that FUSE needs and libaltfs does not: a
hash table of open file handles (`file_table`, one `struct file_info` per
dentry with the open count, and a `struct ltfs_file_handle` per `open(2)`),
the permission override options (`uid`, `gid`, `umask`, `fmask`, `dmask`),
and the index-writing policy, `sync_type` (see below).

Two handlers matter more than the others. `init` (`ltfs_fuse_mount()`) runs
after FUSE has daemonised: it reopens the device if start-up closed it
before forking, initialises the I/O scheduler and starts the periodic sync
thread. `destroy` stops that thread, destroys the scheduler (flushing every
file) and calls `ltfs_unmount()`, which writes the final index.

### File system operations

`ltfs_fsops.c` is libaltfs's own file system API, independent of FUSE; the
commands use parts of it too (`altfsck`, `altfsindextool`). Every
operation:

1. takes `vol->lock` for read (see Locking) and, through
   `ltfs_wait_revalidation()`, waits while a revalidation is running;
2. resolves the path to a `struct dentry` with the helpers of `fs.c`
   (`fs_path_lookup()` walks the tree; each directory keeps its children
   in a hash table keyed by name);
3. does the work on the dentry and marks the index dirty
   (`ltfs_set_index_dirty()`) when metadata changed.

Data goes through the scheduler: `ltfs_fsops_write()` and
`ltfs_fsops_read()` call `iosched_write()` and `iosched_read()`;
`ltfs_fsops_open()` takes a `use_iosched` flag, and the bridge passes
`false` only for directories (`opendir`). `ltfs_fsops_close()` counts the
file's blocks (`ltfs_fsops_update_used_blocks()`) before `iosched_close()`
hands the last partial request to the tape, so the figure the index gets
is the one the scheduler saw.

Extended attributes are in `xattr.c`: user attributes are stored in the
dentry and written to the index; the `ltfs.*` names are virtual, computed
from the volume, the label, the index, the drive or the cartridge memory,
and a few are commands (`ltfs.sync` writes an index, `ltfs.commitMessage`
sets its commit message, `ltfs.vendor.Aurora.*` switch tracing, the
profiler and the log level).

### The I/O scheduler

The scheduler exists because tape has one head and no random access: a
write is a sequential append, and FUSE delivers writes in pieces of 4 KiB
to 1 MiB that may arrive out of order. The interface is
`src/libltfs/iosched_ops.h` (`init`, `destroy`, `open`, `close`, `read`,
`write`, `flush`, `truncate`, `get_filesize`, `update_data_placement`,
`set_profiler`), and
`iosched.c` is the thin wrapper that libaltfs calls; it also answers
"no scheduler" when a command works without one.

`unified.c` keeps, per open file, a list of write requests
(`struct write_request`) in cache blocks of exactly one tape block
(`cache_manager.c` is the pool, bounded by the `min_pool_size` /
`max_pool_size` mount options). A request is `REQUEST_PARTIAL` while it is being filled,
`REQUEST_DP` when full and ready for the data partition, and `REQUEST_IP`
once written to the data partition when the file also goes to the index
partition. A background writer thread (`_unified_writer_thread()`) takes
the queues in that order and calls `ltfs_fsraw_write()` for each block,
so the tape sees full blocks in file order whatever order FUSE delivered.
Files whose name and size match the volume's data placement policy
(`index_criteria.c`, the `-o rules` option and the policy stored in the
index) are written twice, to the data partition first and to the index
partition afterwards, so that small files can be read from the index
partition without a long locate.

Reads are not cached: `unified_read()` serves the bytes that are still in
queued write requests from memory and asks `ltfs_fsraw_read()` for the
rest, after releasing the dentry's scheduler lock so that a long tape read
does not block other operations on the file.

`fcfs.c` is kept as the smallest possible implementation of the interface
for reference; `altfs.conf` registers it and `-o iosched_backend=fcfs`
selects it, but every write then becomes a tape block of its own.

### The raw format layer and the tape layer

`ltfs_fsops_raw.c` maps between a file's extents and tape blocks. For a
read, it walks the dentry's `extentlist`, fills holes with zeros, and for
each extent computes the block that holds the next byte, seeks there if the
drive is not already positioned on it (`tape_seek()`), and reads one block
(`tape_read()`); `vol->last_block` is a one-block cache so that two reads
inside the same block cost one tape read. For a write,
`ltfs_fsraw_write()` positions at the append point of the partition
(`tape_seek_append_position()`), writes the block (`tape_write()`), and
adds the resulting `struct extent_info` to the dentry under its
`contents_lock`. The tape device lock is held across each seek-and-read
and each position-and-write, so another thread cannot move the head in
between.

`tape.c` owns `struct device_data`, one per opened drive, and is the only
caller of the backend's `struct tape_ops`. It adds what every backend would
otherwise repeat: the device lock (`tape_device_lock()`), the cached
position (`tape_update_position()`), the remaining-capacity and
TEST UNIT READY caches, the append-position bookkeeping per partition,
read-only handling (write-protected cartridge, `-o ro`, a volume that
turned read-only after an error), the retry and failover logic around a
command, the encryption key hand-off to the key manager plugin, and the
MAM attributes (cartridge coherency, volume lock, media pool). The
backends return `-EDEV_*` codes (`ltfs_error.h`), produced from the SCSI
sense data by the shared tables in `src/tape_drivers/`, and `tape.c`
turns the ones that mean "the cartridge may have changed" into a
revalidation.

### The dentry cache plugin

`dcache_ops.h` describes a fourth plugin type, a dentry cache that would
keep the directory tree on disk instead of in memory, with a disk image,
advisory locks and per-name caches. `ltfs_fsops.c` calls it wherever a
dentry is opened, created, renamed or flushed, but always behind
`dcache_initialized()`, and nothing in this tree initialises it: there is
no dcache backend under `src/`, `altfs` has no option to name one, and
`dcache_init()` has no caller. The code is inherited from the reference
implementation and is dormant; `dcache_initialized()` is false on every
mount, and the whole tree lives in memory.

## The volume in memory

Three structures, all in `src/libltfs/ltfs.h`:

- **`struct ltfs_volume`** is a mounted cartridge: the `label`, the
  current `index`, the `device` (`struct device_data`), the opaque handles
  of the plugins (`iosched_handle`, `kmi_handle`, `dcache_handle`,
  `periodic_sync_handle`), the mount options that libaltfs needs
  (`readonly_mount`, `mount_type`, `traverse_mode`, `full_index_interval`,
  `work_directory`), the one-block read cache, the cached cartridge
  health, tape alerts and capacity, the revalidation state (`reval`,
  `reval_lock`, `reval_cond`), and the journal of an incremental index
  (`journal`, `created_dirs`).
- **`struct ltfs_index`** is one generation of the index: the volume UUID
  and name, the `generation` number, the self pointer and back pointer to
  the previous generation (`selfptr`, `backptr`, and their `_inc`
  counterparts for incremental indexes), the data placement criteria, the
  `root` dentry, the dirty flags (`dirty` for a full index, `inc_dirty`
  for any index, `atime_dirty`), counters (`file_count`, `valid_blocks`,
  `uid_number` for allocating file UIDs), the commit message, and the
  format versions read and written.
- **`struct dentry`** is a file, directory or symbolic link: identity
  (`uid`, the persistent UID from the index, and `ino`, the per-process
  inode number), `name` and `platform_safe_name`, `parent`, the children
  in `child_list` (a hash table of `struct name_list`), the `extentlist`
  of `struct extent_info` (where on which partition each range of the
  file is), sizes (`size` and `realsize`), the timestamps, the
  `readonly` flag (the only permission bit the format has), `xattrlist`,
  the reference counts (`numhandles`, `link_count`), `deleted`, and
  `iosched_priv`, the scheduler's per-file state.

An extent (`struct extent_info`) says that `bytecount` bytes of the file
from `fileoffset` are on tape at `start` (partition and block) plus
`byteoffset` into that block. Blocks are the volume's `blocksize` from the
label; a file written in one go is one extent.

### Locking

The lock type is `MultiReaderSingleWriter` (`ltfs_locking.h`, selecting
`ltfs_locking_new.h` or `ltfs_locking_old.h` by platform), used through
`acquireread_mrsw()` / `acquirewrite_mrsw()` and their release functions.

- `vol->lock` is taken for read by every file system operation and for
  write by anything that needs the volume to itself: writing an index,
  revalidation, unmount. `ltfs_get_volume_lock()` is the entry point that
  also checks the revalidation state.
- A dentry has three locks, and the comment above them in `ltfs.h` gives
  the order: `iosched_lock`, then `contents_lock`, then `meta_lock`. The
  tape device lock, when needed, is taken before `meta_lock`, and all of a
  parent's locks before any of the child's. `contents_lock` covers the
  extent list and the child list, `meta_lock` the names, timestamps,
  xattrs and flags; `size`, `realsize` and `used_blocks` are written under
  both and read under either.
- `struct ltfs_index` has `rename_lock` (the name tree during a rename),
  `dirty_lock` (the dirty flags) and `refcount_lock`.
- The device lock in `struct device_data` serialises every command to the
  drive and guards the caches in `tape.c` and the one-block read cache in
  the volume.
- The scheduler has its own: `dentry_priv->io_lock` and
  `write_error_lock`, and the dentry's `iosched_lock`; the rule written in
  `unified.c` is that `write_error_lock` is the innermost lock and nothing
  is taken while holding it.

## The index on tape

A cartridge has two partitions. The label of each one (`struct ltfs_label`,
`label.c`, written as the VOL1 ANSI label plus an XML label by
`xml_make_label()`) says which logical ID (`a`, `b`) is the data partition
and which the index partition, the block size and whether compression is
on. `ltfs_part_id2num()` maps the logical ID to the physical partition
number the drive uses.

Indexes are XML (`xml_writer_libltfs.c`, `xml_reader_libltfs.c`, with the
generic helpers in `xml_writer.c` and `xml_reader.c`), one index per
generation, written between file marks. A full index describes the whole
tree; an incremental index (format version 2.5 and later) describes only
what changed since the previous one and is applied on top of it at mount
(`ltfs_apply_incindex_from_tape()`, `inc_journal.c` keeps the journal that
feeds it).

**Mount** (`ltfs_mount()` in `ltfs.c`): `ltfs_start_mount()` loads the
tape, reads both labels (`ltfs_read_labels()`), sets compression and
checks the block size against the drive; `ltfs_check_eod_status()` makes
sure both partitions end in EOD; the cartridge coherency attributes in the
MAM say where the last index of each partition is, so the mount seeks
there and reads it (`ltfs_read_index()`). When the MAM and the tape
disagree or a partition does not end in an index, `ltfs_check_medium()`
walks the partition to find the newest consistent index and, for a
read-write mount, writes a recovery index. The result is one of the
`mount_type` values: `MOUNT_NORMAL`, `MOUNT_ROLLBACK` (an older generation
was requested), `MOUNT_ROLLBACK_META` (the same from an index file, without
the data), `MOUNT_ERR_TAPE` (the tape could be read but not
repaired; writes are refused). `-o index_file` mounts an index file instead
(`ltfs_mount_indexfile()`), with or without a tape.

**Sync** (`ltfs_sync_index()`): writes a new generation if the index is
dirty. An incremental index always goes to the data partition; a full one
goes to the data partition too, which is faster because the data is being
appended there, unless the data partition already ends in an index and the
index partition does not. The caller holds `vol->lock` for write while
`ltfs_write_index()` writes a file mark, the XML, and another file mark,
updates the self and back pointers and the MAM coherency attributes, and
clears the dirty flags. Which type a sync writes, when nobody asked for one
in particular (`LTFS_INDEX_AUTO`), follows the volume's
`full_index_interval` policy (`-o full_index_interval`); when the volume's
format version does not allow incremental indexes or the journal is not
usable, a full index is written instead.

The syncs that happen on their own are chosen by the `sync_type` mount
option in the bridge: `time` (the default, every 5 minutes by the thread of
`periodic_sync.c`), `close` (after a file written through was released) or
`unmount` (none until unmount). The `ltfs.sync` attribute and
`ltfs_fsops_volume_sync()` flush the scheduler and sync on request.

**Unmount** (`ltfs_unmount()`): with the volume locked for write, a full
index is written to the index partition if the index is dirty or the last
index went to the data partition, so that a cartridge always ends with its
newest index on the index partition when it leaves the drive. The MAM is
updated, the file system is released (`ltfs_release_medium()`) and the
drive is closed; `altfs` then ejects the cartridge when `-o eject` was
given (`altfs.c`, after `fuse_main()` returns).

## Plugins

`plugin.c` loads a plugin with `dlopen()` from the path that `altfs.conf`
gives for its type and name (`config_file.c`; `plugin tape sg <path>`,
`default tape sg`, and `altfs.conf.local` for site changes) and looks up
two symbols: `<type>_get_ops()`, which returns the operation table, and
`<type>_get_message_bundle_name()`, which names the plugin's message
catalog so that its messages join the program's. The four types and their
interfaces:

| Type | Interface | Operations | Used by |
|:--|:--|:--|:--|
| `tape` | `src/libltfs/tape_ops.h`, `struct tape_ops` | 56, from `open` and `load` to `read`, `write`, `locate`, MAM and encryption | every command |
| `iosched` | `src/libltfs/iosched_ops.h`, `struct iosched_ops` | 11 | `altfs` only |
| `kmi` | `src/libltfs/kmi_ops.h`, `struct kmi_ops` | 5: `init`, `destroy`, `get_key`, `help_message`, `parse_opts` | every command, when `-o kmi_backend` names one; the tape layer asks it for the key when the drive needs one (`tape_load_tape()`, `tape_read()`) |
| `dcache` | `src/libltfs/dcache_ops.h`, `struct dcache_ops` | dormant, see above | nothing |

`config_file.c` also accepts the types `changer` and `crepos` in a
configuration file; nothing in this tree loads them.

Each plugin parses its own `-o` options: libaltfs hands the FUSE option
list to `tape_parse_opts()` and `kmi_parse_opts()`, which call the
backend's `parse_opts`, and prints the backend's help through
`plugin_usage()`.

## Messages and tracing

Every message a component prints has an ID (`ltfsmsg(AFS0001I, ...)`,
`ltfslogging.c`) that selects a string from an ICU resource bundle under
`messages/`; the component code in the ID says which catalog
(`messages/README`). The libaltfs error codes (`LTFS_*`, `EDEV_*` in
`ltfs_error.h`) have message IDs of their own (`AEI`, `AED`) in
`messages/internal_error/`, derived from the code's number; they document
the codes, which the log messages carry as numbers (see the error handling
design document).

`ltfstrace.c` records every request at three points, the bridge, the
scheduler and the tape backend, into a ring buffer that
`ltfs.vendor.Aurora.trace` dumps, and when the profiler is on
(`ltfs.vendor.Aurora.profiler`) into `prof_*.dat` files in the work
directory, which is how the command counts and timings in this project's
measurements are taken.
