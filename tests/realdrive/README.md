# Real-drive checks

CI has no tape hardware: it exercises Aurora LTFS through the `file` backend
only. The scripts in this directory are run by hand on a host with a real tape
drive, before a release and when a change touches the drive or the system
integration.

They are **not** run by the test runners (`tests/fsapi`, `tests/scenarios`).
`tests/scenarios/test_realdrive_scripts.py` runs them in their dry-run modes
against the `file` backend, so that CI notices when they stop working.

## Before you start

- Run as **root** (`sudo`). Without `CAP_SYS_RAWIO` the kernel's sg command
  filter rejects most tape commands (REWIND, LOCATE, SPACE, WRITE FILEMARKS,
  READ POSITION, ...), so a real drive cannot be driven as a normal user.
- Use a **scratch cartridge**. The tape phases format it (`--erase-tape`,
  `--format`).
- Find the drive's serial number with `sudo altfs -o device_list`. Prefer it
  over `/dev/sgN`, which can change after a reboot.
- Nothing else may be mounted from LTFS: stopping `altfs.service` sends SIGTERM
  to every `altfs` process on the host, so `host-check.sh` refuses to run while
  other LTFS volumes are mounted.
- **Host transfer limit.** A tape block is transferred with one command, so the
  host path limits the usable block size. An HBA behind a Thunderbolt or USB4
  port, for example, is limited to 256 KiB (see #148). The sg backend reports
  the limit at open (`ATG0107I`, `ATG0108W` below 512 KiB); since #149
  `mkaltfs` picks a block size within it. With older builds, format with
  `-b 262144` on such a host.

Which build is tested:

| Mode | Option | What is checked |
|:--|:--|:--|
| Packages | `--deb-dir DIR` (install) or `--skip-install` | the installed deb packages, including the system integration |
| Build tree | `--prefix DIR` | the commands in `DIR/bin` (a `make install` with `--prefix=DIR`) |

## `host-check.sh`

Checks an installation on a systemd host (Debian / Ubuntu) and, with
`--device`, runs a sniff test on the drive.

```bash
# packages of a release candidate, then the drive
sudo ./host-check.sh --deb-dir ./rc --expect-version '1.0.2~rc.1' \
    --device <serial> --erase-tape

# upgrade from the previous release
sudo ./host-check.sh --old-deb-dir ./old --deb-dir ./rc

# a build tree on the drive (no package or systemd checks)
sudo ./host-check.sh --prefix ~/altfs-build --device <serial> --erase-tape
```

Package mode checks: package installation (and upgrade with `--old-deb-dir`),
`altfs.service` enabled and active, the rsyslog rule and the logrotate
configuration, log lines in `/var/log/altfs.log` and not in the system log,
`ltfs.softwareProduct`, `altfs_ordered_copy`, a package reinstall with a volume
mounted (it must stay mounted), `systemctl stop altfs.service` with a volume
mounted (clean unmount, index written), and a log rotation.

Tape phase (`--device ... --erase-tape`): `mkaltfs`, mount, 200 small files
and a large file (`--big-size`, default 2G), unmount, remount **without** a
full consistency check (`ALB0028I` would mean the VCR / VCI were not in sync),
checksums, stop with the tape mounted (`systemctl stop altfs.service` in
package mode, a plain unmount in `--prefix` mode), clean remount, `altfsck`.
`altfsck` returns 1 (`LTFSCK_CORRECTED`) with `ACK0019I Volume is consistent`
for a consistent volume: it always runs a full check and updates the MAM.

Not covered: a reboot with a volume mounted. Do that by hand from a root
console or ssh session (a mount started from a desktop terminal lives under
`user@UID.service`, which is stopped after 5 s on Ubuntu, see #105).

## `wait-medium-check.sh`

Checks `altfs -o wait_medium` (#104) on a real drive. The drive must be
**empty** at the start (`--format` formats the cartridge that is in the drive
first and then asks you to eject it).

```bash
sudo ./wait-medium-check.sh --device <serial> [--prefix DIR] --format
```

| Step | Drive | Expected |
|:--|:--|:--|
| A | empty, no option | fails at once, exit status 1; the drive dump taken on the failed LOAD is readable |
| B | empty, `wait_medium=20` | `AFS0142I`, gives up with `AFS0145E`, exit 1 |
| C | empty, `wait_medium`, SIGTERM | `AFS0144I`, exit 0, drive released |
| D1 | cartridge **pushed fully in** while waiting | the drive loads it by itself ("becoming ready"), `AFS0143I`, mount, write, clean unmount and remount |
| D2 | cartridge stopped at the **lock position** while waiting | altfs issues the LOAD, same checks as D1 |

**Insert the cartridge only when the script tells you to.** Before that,
`altfs` is still in its initial load attempt (a real drive takes 10-15 s,
including a drive dump), and the cartridge would be loaded through the regular
path instead of the wait.

## Safety rules the scripts follow

- A mounted or mounting `altfs` is never killed with SIGKILL except as a last
  resort. A killed `altfs` leaves the medium locked (PREVENT MEDIUM REMOVAL)
  and a dead mount behind. If that happens: `sudo umount -l <mnt>`, mount the
  cartridge once more and unmount it normally, which releases the lock.
- The mount point has to be empty; a failed mount must not make later steps
  write to the local disk.
- Logs and a report are kept in `/var/tmp/altfs-host-check.*` /
  `/var/tmp/wait-medium-check.*` when a check fails.

## Reporting

Attach the summary and, for a failure, the matching part of `/var/log/altfs.log`
(or the work directory) to the pull request or issue, together with the drive
(vendor, model, firmware from `altfs -o device_list`), the HBA and the kernel.
For a drive not yet listed as maintained, use the **Drive report** issue
template.
