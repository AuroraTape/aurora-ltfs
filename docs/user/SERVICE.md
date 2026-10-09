# Running a drive as a service

On Linux with systemd, a tape drive can be mounted by a system service,
`altfs@<serial>.service`, instead of from a shell. This guide walks through
setting one up with `altfsctl`, running it day to day, reading its log and
taking it down again. The reference for the commands is
[altfsctl(8)](reference/altfsctl.md); the mount options are in
[altfs(8)](reference/altfs.md).

## When to use the service

A mount started from a login shell belongs to the login session. At shutdown,
systemd stops sessions with a short timeout (5 s for a desktop terminal on
Ubuntu) and then kills what is left. `altfs` writes the index to the tape when
it is told to stop, and that takes longer than 5 s on a large volume: a mount
from a shell can lose the files written since the last index.

The service avoids that, and does a few more things a shell cannot:

- An instance has its own stop timeout of 11 minutes, enough for the index
  write.
- At shutdown, the instances are stopped before `altfs.service` (the clean
  unmount of volumes mounted in other ways) and while the network is still up,
  which matters for drives attached over iSCSI or Fibre Channel over IP.
- The instance runs `altfs` as the unprivileged user `altfs`, not as root.
- It waits for the drive and for a cartridge when they are not ready, so it
  can be enabled at boot: an empty drive, or one that is powered on with the
  host and shows up late, does not make the instance fail.
- The instance is named after the serial number of the drive
  (`altfs@9A700L0077.service`), which does not change across reboots unlike
  `/dev/sgN`.

Use it for a drive that should be mounted all the time or at boot. For a
cartridge you mount for an hour from a terminal, `altfs` from the shell is
fine; just unmount it before you log out.

## Setup

The deb and rpm packages install everything the service needs: the unit
template `altfs@.service`, the user and group `altfs` (ID 5432 when it is
free, otherwise a free system ID) and `altfsctl`. Run the setup as root.

### 1. Find the drive

```
# altfs -o device_list
```

Use the "Serial Number" of the drive. That serial is the name of the
instance.

### 2. Check the environment

```
# altfsctl check 9A700L0077
```

Each item comes out as `OK` or `FAIL` with what to do. The checks are:

- `user_allow_other` is set in `/etc/fuse.conf`. The instance mounts with
  `-o allow_other` so that users other than `altfs` can see the volume, and
  `fusermount` refuses that option to a non-root user unless this line is
  present. See [Access](#access) before adding it.
- The user `altfs` and the group `tape` exist.
- `altfs` is installed.
- The drive is listed by `altfs -o device_list`, and its device node
  (`/dev/sgN`) is readable and writable by the group `tape`. The instance
  reaches the drive through that group; the default udev rules of systemd
  give SCSI tape devices to it.

`check` without a serial checks the host only. It also notes when systemd is
not running (a container, for example): the settings can be written, but no
instance can start.

### 3. Add the instance

```
# altfsctl add --gid tapeusers --umask 007 --enable 9A700L0077 /mnt/ltfs
```

`add` runs the checks again and changes nothing when one fails. Otherwise it:

- creates the mount point and gives it to the user `altfs`. The path has to be
  absolute. An existing directory is used only when it is empty, not mounted,
  and already belongs to `altfs`: `altfsctl` does not take over a directory
  such as `/mnt`. To use one you made, `chown altfs:altfs` it first. A
  symbolic link is refused: give the real path;
- writes `/etc/altfs/9A700L0077.conf` with `MOUNTPOINT=` and `OPTIONS=`,
  the options the instance passes to `altfs`;
- with `--enable`, enables the instance so that it starts at boot.

An instance that is already set up is refused unless you give `--force`,
which replaces its settings.

`--gid` and `--umask` decide who can use the volume; see [Access](#access).
Further mount options go in with `-o`, without the `-o` that `altfs` takes:

```
# altfsctl add -o sync_type=time@10 -o eject 9A700L0077 /mnt/ltfs
```

### 4. Start it

```
# systemctl start altfs@9A700L0077.service
```

`systemctl start` returns as soon as `altfs` is running; it does not wait for
the mount, so a drive without a cartridge does not hold up anything. The
volume is mounted a little later:

```
# systemctl status altfs@9A700L0077.service
# mountpoint /mnt/ltfs
# altfsctl list
SERIAL      ENABLED  ACTIVE  MOUNTPOINT
9A700L0077  enabled  active  /mnt/ltfs
```

`ACTIVE` says whether the instance runs, not whether the volume is mounted: an
instance waiting for a cartridge is `active` too. The log tells which (see
[Logs](#logs)).

## Access

LTFS stores no owners and no permissions. The volume shows every file with the
owner and the permissions `altfs` was told to use at mount time, for everybody,
and three settings decide who gets in.

**`user_allow_other` in `/etc/fuse.conf`.** The instance always mounts with
`allow_other`, and `fusermount` refuses that option to the non-root user
`altfs` unless the line is set: without it the volume cannot be mounted at
all, and `altfsctl check` fails on it.
The line applies to the whole host: it allows every local user to create FUSE
mounts with `allow_other`, not just this service. That is why `altfsctl` does
not add it by itself. Add it by hand, or let `altfsctl` do it with
`--fix-fuse-conf`, which uncomments the line when the file has it commented
out and appends it otherwise.

**`--gid`** sets the group shown as the owner of all files and directories.
Without it, they belong to the user and group `altfs`.

**`--umask`** removes permission bits from all files and directories. Without
it, they are `0777`: every local user can read, write and delete everything on
the volume. `--gid tapeusers --umask 007` limits the volume to the members of
`tapeusers`. `--umask 022` makes it readable for everybody and writable for
the owner only; the owner is `altfs`, so then nobody but root can write. To
show one user as the owner instead, add `-o uid=<number>`.

The settings apply to the whole volume; there is no way to give one directory
other permissions than another. They are `-o gid=`, `-o umask=` and `-o uid=`
of `altfs`, and they end up in `OPTIONS=` of the instance's configuration
file.

## Day-to-day operation

Starting and stopping are `systemctl`'s job; `altfsctl` only keeps the
settings.

**Stop.** `systemctl stop` sends SIGTERM to `altfs`, which writes the index to
the tape, unmounts the volume and exits. `stop` returns when that is done; with
many files written since the last index it can take minutes. The instance has
11 minutes before systemd gives up on it.

```
# systemctl stop altfs@9A700L0077.service
```

**Change the cartridge.** Stop the instance, change the cartridge, start it
again. The instance mounts whatever is in the drive: it is not tied to the
cartridge it was set up with. With `-o eject` among the options the cartridge
is ejected at unmount, so a stop leaves the drive ready for the next one.

**Empty drive.** Without a cartridge, the instance waits (`-o wait_medium`,
which `altfsctl add` puts in unless you say `--no-wait-medium`). The log shows
AFS0141I, "No medium in the drive. Waiting for a cartridge to be loaded",
and the drive is polled about every 5 seconds. Once a cartridge is loaded, the
mount continues as usual (AFS0143I). The drive stays reserved while the
instance waits, so `mkaltfs` or `altfsck` cannot use it until the instance is
stopped; a stop while waiting ends the wait and releases the drive
(AFS0144I).

**A drive that is not ready.** A drive that cannot be opened is waited for in
the same way: at boot, the device node may not be usable for a moment, and a
drive powered on with the host shows up late. A serial that matches no drive
at all looks the same and is waited for too, without end. With
`--no-wait-medium`, the instance fails instead in all these cases.

**Restart after the volume was unmounted.** An instance ends when the volume is
unmounted, for example by `umount` or after an error. It does not start again
by itself. To make it, for example to wait for the next cartridge after every
unmount, add a drop-in:

```
# systemctl edit altfs@9A700L0077.service
[Service]
Restart=always
```

**Boot.** An enabled instance starts at boot after the local and remote file
systems and the network. Whether the volume is mounted afterwards depends on
the drive: an empty drive leaves the instance waiting.

## Logs

The messages of `altfs` go to syslog, and so to the journal. With the packages
and rsyslog, they are also written to `/var/log/altfs.log` (RFC 3339
timestamps, rotated by logrotate) and kept out of the system log
(`/var/log/syslog`, `/var/log/messages`). The instance also writes its errors
to standard error, which lands in the journal, so an error appears there
twice:

```
# journalctl -u altfs@9A700L0077.service
# tail -f /var/log/altfs.log
```

The messages to look for are AFS0025I, "Ready to receive file system
requests", once the volume is mounted, and ALB0035I, "Volume unmounted
successfully", after a stop. ALB0028I, "Performing a full medium consistency
check", means the volume was not unmounted cleanly the last time.

The unit starts `altfs` with `-o verbose=200`: informational messages to
syslog (level 2), errors only to standard error (level 0). For debugging,
`-o verbose=300` sends the diagnostic messages to syslog as well, and
`-o verbose=303` to both. The option goes in with the others of the
instance, where it overrides the unit's: either add it to `OPTIONS=` in
`/etc/altfs/9A700L0077.conf` and restart the instance, or stop the instance
and set it up again with `--force`, giving all its options again (`--force`
replaces them all, and is refused while the volume is mounted):

```
# systemctl stop altfs@9A700L0077.service
# altfsctl add --force --gid tapeusers --umask 007 -o verbose=300 9A700L0077 /mnt/ltfs
# systemctl start altfs@9A700L0077.service
``` How the syslog rule and logrotate are set up is in
[conf/README.md](../../conf/README.md), with an example for syslog-ng.

## Shutdown and reboot

At shutdown, systemd stops the instances in the reverse of their start order:
after everything that was started later, and before the file systems and the
network they were started after. Each instance writes its index and unmounts,
with the 11-minute timeout. `altfs.service`, the clean unmount of LTFS volumes
mounted in other ways, runs after the instances, so it finds nothing of theirs
left to do.

An enabled instance starts again at boot. A volume stopped cleanly mounts
without a full consistency check.

## Customising the instance

- Mount options go through `altfsctl add -o` (`--force` replaces the
  settings of a stopped instance),
  or directly in `OPTIONS=` of `/etc/altfs/<serial>.conf`, as `-o name=value`
  pairs. The unit passes them to `altfs` after its own options, so `-o
  verbose=` and others override the defaults of the unit.
- `DEVICE=` in the same file, written by `altfsctl add --device`, makes the
  instance open that device instead of looking the drive up by its serial,
  for example a symlink of your own to the drive's `/dev/sgN`, made with a
  udev rule. The links udev makes under `/dev/tape/by-id/` point to the `st`
  devices, which the instance cannot use.
- Everything else about the unit (`Restart=`, the stop timeout, dependencies)
  is a drop-in made with `systemctl edit altfs@<serial>.service`, or
  `systemctl edit altfs@.service` for all instances. Do not edit the unit
  template in `/usr/lib/systemd/system`: a package upgrade replaces it.

The unit runs `altfs -f -o devname=<device> -o allow_other -o
work_directory=/var/lib/altfs/<serial> -o verbose=200 $OPTIONS <mountpoint>`
as `altfs` with the supplementary group `tape` and the capability
`CAP_SYS_RAWIO`.

## Troubleshooting

**`altfsctl check` fails on the device node.** The instance reaches the drive
as a member of the group `tape`, so `/dev/sgN` has to be readable and
writable by that group. Check the udev rules of the distribution, and the
group of the node with `ls -l /dev/sgN`. The drive also has to be listed by
`altfs -o device_list` run as root.

**The user `altfs` does not exist.** The packages create it with
`systemd-sysusers` when they are installed. In a container, or on a system
without systemd, there is no systemd-sysusers and no service either, so the
user is not created. After a build from source, create it with
`systemd-sysusers <prefix>/lib/sysusers.d/altfs.conf`.

**The instance starts but nothing is mounted.** Look at the log. AFS0141I
means it is waiting for a cartridge; an error shows which command failed. An
error from `fusermount` about `user_allow_other` means the line has gone from
`/etc/fuse.conf` since the setup. The tape commands need `CAP_SYS_RAWIO`,
which the unit gives the instance; a copy of the unit without
`AmbientCapabilities=` makes the kernel's sg command filter reject most of
them (REWIND, LOCATE, READ POSITION, ...), even for a member of the group
`tape`.

**Other users cannot see the volume.** They are not in the group given with
`--gid`, and the umask shuts them out. `ls -ld /mnt/ltfs` shows the owner,
group and permissions the volume is mounted with.

**The instance will not start.** `systemctl status` shows the last lines of
the log and the exit status. A mount point that has gone missing or is
already mounted stops `altfs` early, and so does a wrong option in `OPTIONS=`
of the settings file (`altfs` prints its usage in that case).

**`systemctl stop` takes long.** It waits for the index write. Stopping takes
longer after many files were written since the last index; `-o sync_type=`
of `altfs` writes indexes more often during operation, which spreads the work
out.

**`altfsctl remove` is refused.** The instance is running; `systemctl stop`
it first.

## Removing an instance

```
# systemctl stop altfs@9A700L0077.service
# altfsctl remove 9A700L0077
```

`remove` disables the instance and deletes `/etc/altfs/9A700L0077.conf`. The
mount point is left in place; remove it yourself. `altfsctl disable` keeps
the settings and only stops the instance from starting at boot; a running
instance keeps running.

Uninstalling the package removes the unit template and `altfsctl`. The
settings in `/etc/altfs/` and the user `altfs` stay: a reinstall finds them
again, and files on local disks owned by `altfs` keep a known owner.
