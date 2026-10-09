<!-- Generated from man/altfs.8 by man/make-markdown.sh: edit man/sgml/altfs.sgml instead -->

# altfs(8)

## NAME

altfs - File system based on a linear tape drive

## SYNOPSIS

**altfs** *mount_point* \[ **-o** *mount_option ...* \] \[ **-V** \] \[ **-h** \] \[ **-a** \]

## DESCRIPTION

**altfs** is a file system for linear tape drive.

## GENERAL OPTIONS

**-V, --version**  
Version information

**-h, --help**  
Show help information

**-a**  
Full help, including advanced options

## LTFS OPTIONS (MOUNT OPTIONS)

**-o devname=** *name*  
Tape device name. On Linux, *name* is like '/dev/IBMtape0', on OSX, *name* is like '0'(default: )

**-o work_directory=** *dir*  
LTFS work directory (default: )

**-o trace**  
Enable diagnostic output (same as verbose=3)

**-o eject**  
Eject the cartridge after unmount

**-o sync_type=** *type*  
Specify sync type (default: time@5).

*type* should be specified as follows:

> **time@min**  
> LTFS attempts to write an index each 'min' minutes. min should be a decimal number from 1 to 153722867280912930. It is equivalent to "-o sync_type=unmount" when 0 is specified
>
> **close**  
> LTFS attempts to write an index when a file is closed
>
> **unmount**  
> LTFS attempts to write an index when the medium is unmounted

**-o full_index_interval=** *num*  
Type of the indexes written by the periodic sync and the sync on close (default: -1). These syncs promise nothing about the state of the files, they only bring the volume back to a recent index after a failure. An incremental index (format specification 2.5) records the changes since the previous index and is much smaller than a full index on a volume with many files, but a volume whose last index is incremental has to be repaired with altfsck after a failure, and other LTFS implementations recover it to its last full index only.

**negative**  
Incremental indexes only. A full index is written at unmount and on request (ltfs.sync, ltfs.commitMessage, ltfs.vendor.Aurora.FullSync).

**0**  
Full indexes only, the behaviour of the LTFS reference implementation. Use it for a volume that other LTFS implementations will read after a failure: they recover such a volume to its last full index.

**N**  
N incremental indexes, then a full index. Every full index starts the count again, and an incremental index written on request (ltfs.vendor.Aurora.IncrementalSync) counts as well.

The sync extended attributes always write the type they name, whatever the value. An incremental index is replaced by a full index, with a warning, when the change cannot be described incrementally.

A volume keeps the format version it was written at. On a volume below format specification 2.5 (a tape formatted by another LTFS implementation at 2.4) the indexes are written at that version and no incremental index is ever written, whatever this option says; writing ltfs.vendor.Aurora.IncrementalSync fails there with EINVAL.

**-o force_mount_no_eod**  
Skip EOD existence check when mounting (read-only mount). Only use for a CM corrupted medium

**-o device_list**  
Show available tape devices

**-o rollback_mount=** *gen*  
Attempt to mount on previous index generation on tape by read-only mode. To mount with an index file, use -o index_file.

**-o index_file=** *file*  
Mount with the index recorded in an index file, read-only, instead of the latest index on the tape. The file must hold a full index; an incremental index is rejected. Cannot be used with -o rollback_mount.

With -o devname, the tape is mounted with that index and file contents can be read. The index must belong to the volume: its volume UUID must match the label.

Without -o devname, only the directory tree of the index is mounted, without a tape. No tape device is opened and no tape backend is loaded. Use it to browse the contents of a cartridge that is not in a drive, from an index captured by altfsindextool or by -o capture_index. Names, sizes, timestamps and extended attributes are available. Reading file contents fails with ENODATA; an empty file reads as empty. Virtual extended attributes that come from the index (e.g. ltfs.volumeUUID, ltfs.indexGeneration, ltfs.indexLocation, ltfs.startblock) are available; those that need the tape (e.g. ltfs.volumeSerial, ltfs.mediaStorageAlert, ltfs.mam\*, ltfs.vendor.Aurora.referencedBlocks) fail with ENODATA. statfs reports no capacity: the size and the free space are 0.

**-o release_device**  
Clear device reservation (should be specified with -o devname

**-o wait_medium\[=** *sec* **\]**  
Wait for a cartridge when the drive is empty at startup, instead of failing. The drive is polled until a cartridge is loaded, then the mount continues as usual. With *sec* (1 or more), give up after that many seconds; without it, wait without a limit. The drive is polled about every 5 seconds.

altfs waits before it goes to the background: also without -f the command does not return until a cartridge is loaded and the mount is set up, or until the wait ends.

A drive that cannot be opened yet is waited for the same way, before the cartridge: at boot the device node may not be usable for a moment, a drive powered on together with the host shows up late, and another process may have the drive open. A device name or serial number that matches no drive looks the same and is waited for too; give a time limit to fail on it. The time limit covers both waits.

Only an empty drive, or one that cannot be opened, is waited for. Any other error, and a cartridge that cannot be mounted (unformatted, inconsistent, medium error), ends altfs as without this option. The drive stays reserved while altfs is waiting, so other commands cannot use it until the waiting altfs is stopped. SIGTERM or SIGINT ends the wait; altfs releases the drive and exits with status 0 because nothing has failed.

**-o symlink_type=** *type*  
Specify symbolic link type (default: posix)

*type* should be specified with one of the following values:

> **posix**  
> LTFS behavior is same as standard symbolic link
>
> **live**  
> LTFS replaces mount point path by current mount point

## FUSE OPTIONS (MOUNT OPTIONS)

**-o umask=** *M*  
Set file permissions (octal)

**-o uid=** *N*  
Set file owner

**-o gid=** *N*  
Set file group

## ADVANCED LTFS OPTIONS (EXPERIMENTAL MOUNT OPTIONS)

The options described here is experimental functions.

**-o config_file=** *file*  
Configuration file (default: )

**-o atime**  
Update index if only access times have changed

**-o noatime**  
Do not update index if only access times have changed (default)

**-o tape_backend=** *name*  
tape backend to use (default: )

**-o iosched_backend=** *name*  
I/O scheduler implementation to use (default: , use "none" to disable)

**-o kmi_backend=** *name*  
Key manager interface implementation to use (default: none, use "none" to disable)

**-o umask=** *mode*  
Override default permission mask (3 octal digits, default: 000)

**-o fmask=** *mode*  
Override file permission mask (3 octal digits, default: 000)

**-o dmask=** *mode*  
Override directory permission mask (3 octal digits, default: 000)

**-o min_pool_size=** *num*  
Minimum write cache pool size. Cache objects are 1 MB each (default: 25)

**-o max_pool_size=** *num*  
Maximum write cache pool size. Cache objects are 1 MB each (default: 50)

**-o rules=** *rules*  
Rules for choosing files to write to the index partition. The syntax of the rule argument is:

size=1M

size=1M/name=pattern

size=1M/name=pattern1:pattern2:pattern3

A file is written to the index partition if it is no larger than the given size AND matches at least one of the name patterns (if specified). The size argument accepts K, M, and G suffixes. Name patterns might contain the special characters '?' (match any single character) and '\*' (match zero or more characters).

**-o quiet**  
Disable informational messages (same as verbose=1)

**-o syslogtrace**  
Enable diagnostic output to stderr and syslog(same as verbose=303)

**-o fulltrace**  
Enable full call tracing (same as verbose=4)

**-o verbose=** *num*  
Override output verbosity directly (default: 2). A number below 100 sets the level of the standard error output; syslog gets the same messages, up to informational ones. *syslog level* \* 100 + *stderr level* sets the two separately: verbose=200 sends informational messages to syslog and errors only to the standard error output.

**-o noeject**  
Do not eject the cartridge after unmount (default)

**-o capture_index=** *dir*  
Capture index to the specified directory by dir when index is updated. File name of each index is \[BARCODE\]-\[GEN\]-\[PARTITION\].xml if tape serial (barcode) is specified at format time. Otherwise it is \[VOL_UUID\]-\[GEN\]-\[PARTITION\].xml.

**-o scsi_append_only_mode=** *on\|off*  
Set the tape device append-only mode (default=on)

## SEE ALSO

mkaltfs(8), altfsck(8), mount.fuse(8), fusermount(1).
