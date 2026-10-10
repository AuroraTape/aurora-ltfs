# Troubleshooting

What to do when a volume does not mount, when `altfs` was killed, when the
drive misbehaves, and how `altfsck` repairs a volume and rolls it back. The
mount service has its own section in [Running a drive as a
service](SERVICE.md#troubleshooting); the options named here are described
in [altfs(8)](reference/altfs.md), [altfsck(8)](reference/altfsck.md) and
[mkaltfs(8)](reference/mkaltfs.md).

## Where to look first

Every message has an ID such as `ALB0108E`: three letters for the component,
four digits, and a severity letter (`E` error, `W` warning, `I`
informational, `D` debug). The messages go to standard error and to syslog;
with the deb and rpm packages and rsyslog they are in `/var/log/altfs.log`,
otherwise in the journal or the system log. `-o trace` (`-o fulltrace` for
everything) makes `altfs` log what it does at each step; `altfsck` and
`mkaltfs` take `-t` and `--syslogtrace` for the same. See
[Configuration](CONFIGURATION.md#logging).

The first error in the log is the one that matters: what follows is usually
the consequence. Two lines to have at hand for every problem:

```
$ altfs -V
# altfs -o device_list
```

## The volume does not mount

A mount checks the cartridge before it exposes anything: the labels, the
end-of-data (EOD) marks of both partitions, the cartridge memory (MAM), and
whether the newest index on the tape is also the last thing written. What
fails tells you what to do.

| Message | Meaning | What to do |
|:--|:--|:--|
| `ALC0005E Cannot open device` | The drive is not there, not accessible, or busy. | Check `altfs -o device_list`, the device permissions and whether another `altfs` or another host holds the drive (see [Drive and host problems](#drive-and-host-problems)). |
| `AFS0141I` / `AFS0142I No medium in the drive` | `-o wait_medium` is set and `altfs` waits for a cartridge. Without the option an empty drive fails the mount. | Load a cartridge. |
| `ALB0028I Performing a full medium consistency check` | The pointers in the cartridge memory did not match the tape, so the whole tape is checked. This takes long and is not an error by itself. | Wait. If `ALB0029E` follows, run `altfsck`. |
| `ALB0108E Medium check failed: extra blocks detected. Run ltfsck` | Data was written after the newest index: the last session did not end with an index write (a crash, a kill, a power loss). | Run `altfsck` (below). |
| `ALB0236E EOD of ... is missing. A deep recovery operation is required`, `ALB0238E` | One partition has no EOD mark, typically after a power loss or a drive reset during a write. | Run `altfsck --deep-recovery` (below). |
| `ALB0232E Both EODs are missing` | Both partitions have lost their EOD mark. | `altfsck` cannot repair this. `altfs -o force_mount_no_eod` mounts the volume read-only without the EOD check, so the data can be copied off. |
| `ALB0154I A cartridge with write-perm error is detected` | The cartridge memory records a permanent write error from an earlier session. The volume is mounted read-only from the newest readable index. | Copy the data to another cartridge. The cartridge should not be written again. |
| `ALB0246E Cannot read volume: medium is not partitioned`, then `AFS0013E Cannot mount the volume from device` | The cartridge is not LTFS formatted. | A new cartridge needs `mkaltfs`. |
| `ALB0011E Cannot read volume: failed to read partition labels` | The cartridge is partitioned but its labels cannot be read: another file system, a damaged tape, or a block size the host cannot transfer (`ATG0108W`, see below). | Check the host transfer limit first and read the cartridge through a path that transfers its block size. For a cartridge that held LTFS data, do not format. |

## Using altfsck

`altfsck` is to an LTFS volume what `fsck` is to a disk file system, with one
difference: it always does a full check and it writes to the tape when the
volume needs a new index. There is no read-only check. Unmount the volume
first; `altfsck` needs the drive to itself.

```
# altfsck <device>
```

The device is the same name `altfs -o devname=` takes: the serial number or
`/dev/sgN` on Linux, a number on macOS. `altfsck` loads the cartridge, reads
the labels and the cartridge memory, mounts the volume internally with
recovery enabled, writes an index when the volume needs one, unmounts and
reports:

- `ACK0019I Volume is consistent`: the volume is usable. After a crash this
  means the recovery worked; the volume is at the state of the index that
  was written.
- `ACK0018E Volume is inconsistent and was not corrected`: the recovery
  failed; the lines before it say why (missing EOD, unreadable index).
- `ACK0077E Cannot recover the cartridge: found unsupported index version`:
  the index was written by a newer LTFS; use a newer version of the
  software.

### Exit codes

| Exit code | Meaning |
|--:|:--|
| 0 | Nothing was written to the cartridge (`-l`, `-g <gen> -n`, `--capture-index`). |
| 1 | The check succeeded and the cartridge was updated. **This is the normal result of a check**, also for a volume that needed no repair: every check mounts and unmounts the volume and refreshes the cartridge memory. |
| 4 | The volume could not be repaired. |
| 8 | A device error during the operation; the cartridge may have been modified. |
| 16 | Wrong arguments, or an operation the medium does not allow. |
| 32 | Cancelled. |
| 64 | A plugin could not be loaded. |

Scripts that run `altfsck` have to accept 0 and 1 as success.

### After a crash: what the check recovers

An LTFS volume is only as current as its newest index. Data blocks written
after it are on the tape, but no index names them. The check brings the
volume back to that newest index, and the files written after it are
gone. How much can be lost is set by `-o sync_type=` of `altfs`, which says
how often an index is written during a session (every 5 minutes by
default), see [Configuration](CONFIGURATION.md#mount-options-to-know-about).

- `altfsck -f <device>` (`--full-recovery`) keeps the blocks that no index
  names: they are collected into files under `_ltfs_lostandfound` at the
  root of the volume. Their names are not known, so this is for the case
  where the content is worth sorting out by hand.
- A volume whose newest index is an incremental one (format 2.5) is
  recovered by `altfsck` to that index, replaying the incremental indexes
  onto the last full one. Other LTFS implementations recover such a volume
  to its last full index only; see [LTFS format versions](FORMAT.md).

### Deep recovery: a missing EOD

When a write was cut short by a power loss or a drive reset, a partition can
be left without an end-of-data mark. The mount refuses such a cartridge
(`ALB0236E`), and a normal `altfsck` reports `ACK0018E`.

```
# altfsck -z <device>
```

`-z` (`--deep-recovery`) finds the end of the written data, rewrites the EOD
mark there and then runs the normal check. Blocks after the recovery point
can be erased by it: the last file written before the failure may lose its
tail. It is refused on WORM media (`ACK0086E`). When both partitions have
lost their EOD, `altfsck` reports `ACK0071E` and `ACK0072E`; the volume can
then only be mounted read-only with `altfs -o force_mount_no_eod`, to copy
the data off.

### Rollback points

Every index written to the tape is a generation, and every generation
written as a full index is a point the volume can be rolled back to, as long
as the data of that time is still on the tape (a format erases everything).
Incremental indexes, which the periodic and close-time syncs write by
default, are not rollback points and `altfsck -l` does not list them; an
unmount, an explicit `ltfs.sync` and a format write full indexes. See
[LTFS format versions](FORMAT.md).

```
# altfsck -l <device>
```

```
Generation: Date       Time               Zone     SelfPtr->BackPtr (Part, Pos)
           (UTC Date   UTC Time           UTC)
            Commit Message
-------------------------------------------------------------------------------
         2: 2026-10-10 20:34:04.950569450 JST      (0, 5)->(1, 10)
           (2026-10-10 11:34:04.950569450 Universal)
           Unmount - 2026-10-10T11:34:04.950416493Z
         2: 2026-10-10 20:34:04.950569450 JST      (1, 10)->(1, 5)
           (2026-10-10 11:34:04.950569450 Universal)
           Unmount - 2026-10-10T11:34:04.950416493Z
         1: 2026-10-10 20:28:56.296708044 JST      (1, 5) <<Initial Index>>
           (2026-10-10 11:28:56.296708044 Universal)
           Format - 2026-10-10T11:28:56.296695662Z
```

A generation is listed once per partition it was written to (partition 0 is
the index partition, 1 the data partition), with the position of the index
and its commit message: what wrote it (`Format`, `Unmount`, a sync) and when,
or the text set with the `ltfs.commitMessage` extended attribute. `-m` adds
the full index information; `-v forward` traverses the tape from the
beginning instead of backwards from the end. Listing writes nothing and exits
with 0.

### Rolling back

```
# altfsck -g 2 -n <device>    # verify generation 2 is a usable rollback point
# altfsck -g 2 -r <device>    # roll the volume back to generation 2
```

`-g <gen>` alone (or with `-n`) only verifies the generation and exits with
0; `ACK0047I` says the generation is already the current one. `-r` writes a
new index with the content of generation 2 at the end of the tape, so that
the volume mounts at that state: the files of later generations are no
longer in the tree. Their data stays on the tape, and the later generations
stay listed by `-l`, so the rollback itself can be rolled back (`-k`,
`--keep-history`, the default). `-j` (`--erase-history`) truncates the tape
after the rolled-back index instead, which frees the space and makes the
later generations unrecoverable. A rollback is refused on a read-only medium
(`ACK0041E`) and on a cartridge without EOD (`ACK0074E`).

To look at a generation without changing the tape, mount it instead (next
section).

## Reading an older generation or browsing without the tape

- `altfs -o devname=<dev> -o rollback_mount=<gen> <mountpoint>` mounts the
  volume read-only at that generation. Nothing is written; unmount and mount
  normally to get the current state back.
- `altfs -o devname=<dev> -o index_file=<file> <mountpoint>` mounts the tape
  read-only with the index in that file, which must be a full index of this
  volume (same volume UUID). The files are captured with `altfsindextool`
  or, at every index write, with `-o capture_index=<dir>`.
- `altfs -o index_file=<file> <mountpoint>` without a device mounts the
  directory tree of the index alone: names, sizes, timestamps and extended
  attributes, no file contents. This is how a cartridge that is not in a
  drive is browsed. See `-o index_file` in [altfs(8)](reference/altfs.md).

## After altfs was killed or crashed

A killed `altfs` leaves three things behind: a mount point without a file
system behind it, a cartridge the drive refuses to eject, and a tape without
a final index.

**The mount point.** On Linux, accessing it fails with "Transport endpoint
is not connected". Detach it:

```
# fusermount -u <mountpoint>      # or: umount -l <mountpoint>
```

On macOS with the macFUSE FSKit backend the `umount` of a dead volume hangs,
and so does everything that lists mounts (Finder, `mount`, System Settings)
until that volume's `io.macfuse.app.fsmodule.macfuse-local` process is
killed; the `umount` then completes.

**The cartridge.** While a volume is mounted, `altfs` has the drive prevent
a manual eject; the unmount lifts that. After a kill the eject button does
nothing. Mount the cartridge again and unmount it, which also runs the
consistency check, or release the drive without mounting:

```
# altfs -o devname=<dev> -o release_device <mountpoint>
```

`-o release_device` releases the reservation `altfs` holds on the drive and
unloads the cartridge. It is also the way to free a drive that another
`altfs` process on the same host left reserved; a reservation held by
another host is not touched (see below).

**The tape.** The next mount runs the consistency check. If it reports
`ALB0108E`, data was written after the newest index: run `altfsck`, and see
[After a crash](#after-a-crash-what-the-check-recovers) for what is kept.

For a volume mounted by the service (`altfs@<serial>.service`),
`systemctl status` shows how the instance ended, and `systemctl start`
mounts it again, which runs the check; see [Running a drive as a
service](SERVICE.md#troubleshooting).

## Drive and host problems

**The drive is not listed by `altfs -o device_list`.** On Linux, `altfs`
uses the `sg` device of the drive (`/dev/sgN`), not the `st` device. The
node has to be readable and writable by the user, and the kernel's sg
command filter rejects most tape commands (REWIND, LOCATE, SPACE, WRITE
FILEMARKS, READ POSITION, ...) unless the process is root or has
`CAP_SYS_RAWIO`. So a normal user cannot drive a tape; run as root, or use
the mount service, whose unit gives `altfs` that capability. On macOS the
drive is found through IOKit and named by its index (`0`); keep the Mac
awake while a tape is mounted (below).

**`ATG0067W The drive is already reserved`.** Another host, or another
process on this host, holds a reservation on the drive. `altfs` reserves the
drive for the whole session with a key of its own host. A reservation left
by a killed process on this host carries that key, and `-o release_device`
clears it. A reservation of another host is skipped (`ATG0094I`): release it
from that host, or reset or power cycle the drive.

**The host transfer limit.** A tape block is transferred with one command,
and the path between the host and the drive limits its size: an HBA behind a
Thunderbolt or USB4 port, for example, is limited to 256 KiB. At open, the
`sg` backend logs the limit (`ATG0107I`) and warns when it is below 512 KiB
(`ATG0108W`): volumes with a larger block size cannot be read or written
through that path. `mkaltfs` picks a block size within the limit
(`AMK0084I`, since 1.0.2), and refuses a larger `-b` (`ALB0057E`). A volume
written elsewhere with 512 KiB blocks has to be read on a host whose path
transfers 512 KiB.

**Write errors.** When a write to the tape fails, the volume drops to
read-only for the rest of the session (`ALP0051E`, `ALP0053E Dropping to
read-only mode`), so that what is on the tape stays consistent; the error
is recorded in the cartridge memory and the next mount is read-only too
(`ALB0154I`). Unmount, copy the data to another cartridge, and have a look
at the drive dump.

**Drive dumps.** When an IBM drive reports an error, the `sg` and `iokit`
backends save the drive's internal dump to `/tmp/ltfs_<drive serial>_<date>_<time>.dmp`
(and a forced dump as `..._f.dmp`), logging `ATG0054I Saving drive dump to
...`. The dumps are what the drive vendor reads; attach them to a drive
problem report. `-o noautodump` (a backend option, see
[Configuration](CONFIGURATION.md#plugins)) turns this off.

**The cartridge is write protected.** The volume is mounted read-only. A
volume can also be locked by its index (`ltfs.volumeLockState`); the lock is
part of the volume, not of the drive.

## macOS

- **Keep the Mac awake** while a tape is mounted, e.g. run the session under
  `caffeinate -i` on AC power. Apple's FC driver for LSI HBAs
  (`AppleLSIFusionMPT`) has been seen to panic when tape I/O arrives while
  the system is asleep.
- **FSKit backend** (`-o backend=fskit`): the FSKit module has to be enabled
  once in System Settings after launching `macfuse.app`; a dead `altfs`
  hangs the unmount as described above; and because FSKit does not check
  permissions, `altfs` itself refuses writes to a read-only file, for root
  as well. See the macOS section of the [README](../../README.md).
- Logs go to the system log; `altfs -f` keeps them on the terminal.

## Reporting a problem

Open an issue with the **Bug report** template, or the **Drive report**
template for a drive that does not behave (see [Supported tape
drives](DRIVES.md#reporting-a-drive)). Include:

- `altfs -V`, the OS and its version, and how Aurora LTFS was installed
- The line of `altfs -o device_list` that shows the drive (vendor, model,
  serial), and the firmware level
- The log around the first error, taken with `-o trace` for `altfs` or `-t`
  for `altfsck` / `mkaltfs` (from the terminal, `/var/log/altfs.log` or the
  journal)
- The output of `altfsck -l` when the volume is involved
- The drive dumps from `/tmp/ltfs_*.dmp`, for a drive error
- What was mounted and running at the time: the service, other LTFS volumes,
  other hosts on the same drive

The scripts in [tests/realdrive](../../tests/realdrive/README.md) run a
drive through format, mount, write, read, unmount, remount and `altfsck`,
and write a report you can attach.
