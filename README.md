# Aurora LTFS

[![Build](https://github.com/AuroraTape/aurora-ltfs/actions/workflows/build.yml/badge.svg)](https://github.com/AuroraTape/aurora-ltfs/actions/workflows/build.yml)
[![Scenario tests](https://github.com/AuroraTape/aurora-ltfs/actions/workflows/scenario.yml/badge.svg)](https://github.com/AuroraTape/aurora-ltfs/actions/workflows/scenario.yml)
[![Coverage](https://codecov.io/gh/AuroraTape/aurora-ltfs/graph/badge.svg)](https://codecov.io/gh/AuroraTape/aurora-ltfs)
[![Code size](https://img.shields.io/github/languages/code-size/AuroraTape/aurora-ltfs)](https://github.com/AuroraTape/aurora-ltfs)
[![BSD License](https://img.shields.io/badge/license-BSD-blue.svg?style=flat)](LICENSE)

<details>
<summary>Coverage graph</summary>

[![Coverage sunburst](https://codecov.io/gh/AuroraTape/aurora-ltfs/graphs/sunburst.svg)](https://codecov.io/gh/AuroraTape/aurora-ltfs)

The inner ring is the whole project, moving outward through directories down to individual files. The size of a slice is proportional to the number of statements; the color shows coverage (green = covered, red = not).

</details>

Aurora LTFS is a filesystem implementation that allows mounting LTFS-formatted tapes as regular filesystems. Once mounted, users can access tape contents through standard filesystem APIs.

This project is based on the [Linear Tape File System (LTFS)](https://github.com/LinearTapeFileSystem/ltfs) reference implementation and aims to be compliant with the LTFS format specifications defined by [SNIA](https://www.snia.org/tech_activities/standards/curr_standards/ltfs).

The current target is the [LTFS Format Specification 2.5.1](https://www.snia.org/sites/default/files/technical-work/ltfs/release/SNIA-LTFS-Format-2-5-1-Standard.pdf).

## Goals

### Short term — Foundation

- **CI and unit testing infrastructure** — Build a reliable CI pipeline and unit testing framework to catch regressions early.
- **Package and Docker image distribution** — Provide official packages and container images for easy installation and deployment.
- **LTFS Format Specification 2.5.1 compliance** — Fully implement and validate compliance with the current SNIA standard.
- **Code modernization and refactoring** — Clean up the inherited codebase to improve readability, maintainability, and long-term development velocity.
- **Up-to-date platform support** — Continuously support modern operating systems, free from corporate politics.
- **Modern development practices** — Dev Containers, AI-assisted development, and streamlined workflows to improve developer productivity.

### Middle term — Expansion

- **Expanded test coverage** — Broaden automated tests across components to deliver reliable software with confidence.
- **Tape library support** — Enable automated operation with tape library devices (medium changers).
- **Community-driven development** — Open governance and transparent decision-making to grow the tape storage community.

### Long term — Growth

- **HSM (Hierarchical Storage Management) support** — Integrate with HSM workflows for automated data migration between disk and tape.
- **Windows support** — Bring LTFS to the Windows platform to broaden accessibility.


## Platform Support Policy

We use a tiered support model combined with OS lifecycle tracking.

| Tier | Definition | Platforms |
|:----:|:-----------|:----------|
| Tier 1 | CI tested. Build failures block releases. | Ubuntu 24.04 (x86\_64), Rocky Linux 9 (x86\_64) |
| Tier 2 | Best effort. Builds are verified in CI, but failures do not block releases. | Ubuntu 26.04, Rocky Linux 10, macOS, Debian, FreeBSD |
| Tier 3 | Community-contributed. No guarantees from maintainers. | NetBSD, other platforms |

CI verifies that all Tier 2 platforms (Ubuntu 26.04, Rocky Linux 10, macOS, Debian, FreeBSD) and NetBSD build successfully. On macOS, FreeBSD and NetBSD it also runs the tests that need no FUSE mount (command-line paths, plugin loading, `mkaltfs` / `altfsck` / `altfsindextool` on the file backend), and on macOS it checks and recovers volumes written by the Linux job. The tests that mount run on Linux, and experimentally on the FreeBSD VM, which has a full kernel; the hosted macOS runners cannot mount, the NetBSD VM hangs in puffs on some of them, and CI has no tape hardware. Test failures on Tier 2 and Tier 3 platforms do not block.

**Tier 1 selection policy:**

- One maintained LTS or stable release per major Linux family (Debian-based and RHEL-based). These are the releases the packages are built on.
- The move to a newer release is decided once per development cycle, not on a fixed clock. Criteria: GitHub-hosted runners for the new release, the build and test toolchain (FUSE, ICU, libxml2, pytest) confirmed on it, and the new release having become the mainstream deployment target. Tape systems are conservative, and packages built on the older release install on the widest range of systems, so the move is made when users are there, not when the release is.
- Until the move, the successor release (currently Ubuntu 26.04 and Rocky Linux 10) is a Tier 2 build target, so that toolchain regressions show up early.
- A Tier 1 distribution that reaches EOL is replaced in the next release cycle; that is the hard limit.

Tier 2 and Tier 3 platforms may be promoted or added based on community demand and contributor availability.

**Support window:** a minor release line (`X.Y`) receives fixes on its `release/X.Y` branch until six months after the next minor release. How releases are made is described in [docs/project/RELEASE.md](docs/project/RELEASE.md).

## Supported Tape Drives

  | Vendor  | Drive Type              | Minimum F/W Level | Status                     |
  |:-------:|:-----------------------:|:-----------------:|:---------------------------|
  | IBM     | LTO5                    | B170              | Maintained                 |
  | IBM     | LTO6                    | None              | Inherited                  |
  | IBM     | LTO7                    | None              | Inherited                  |
  | IBM     | LTO8                    | HB81              | Inherited                  |
  | IBM     | LTO9                    | None              | Inherited                  |
  | IBM     | TS1140                  | 3694              | Inherited                  |
  | IBM     | TS1150                  | None              | Inherited                  |
  | IBM     | TS1155                  | None              | Inherited                  |
  | IBM     | TS1160                  | None              | Inherited                  |
  | HP      | LTO5                    | Not determined    | Untested                   |
  | HP      | LTO6                    | Not determined    | Community verified (1.0.0) |
  | HP      | LTO7                    | Not determined    | Untested                   |
  | HP      | LTO8                    | Not determined    | Untested                   |
  | HP      | LTO9                    | Not determined    | Untested                   |
  | Quantum | LTO5 (Only Half Height) | Not determined    | Untested                   |
  | Quantum | LTO6 (Only Half Height) | Not determined    | Untested                   |
  | Quantum | LTO7 (Only Half Height) | Not determined    | Untested                   |
  | Quantum | LTO8 (Only Half Height) | Not determined    | Untested                   |
  | Quantum | LTO9 (Only Half Height) | Not determined    | Untested                   |

Status:

- **Maintained** - the maintainers develop and test with this drive. Today that is the IBM LTO5 only.
- **Inherited** - listed as supported, with this minimum firmware level, by the reference implementation Aurora LTFS is based on, and handled by the same code. Not re-verified with Aurora LTFS, because the maintainers do not have the drive.
- **Community verified (version)** - a community member verified the drive on real hardware with that Aurora LTFS version. HP LTO6 was verified through [#49](https://github.com/AuroraTape/aurora-ltfs/pull/49) and [#50](https://github.com/AuroraTape/aurora-ltfs/pull/50). The firmware level of the reporting drive is not a tested minimum, so the column stays "Not determined".
- **Untested** - the drive is recognized and its code path exists, but no minimum firmware level was ever established and nobody has reported a result with Aurora LTFS. It may work, work with limitations, or fail.

### Drive testing policy

The only tape drive available to the maintainers is an IBM LTO5. CI has no tape hardware at all (it exercises the `file` backend), so:

- Releases are tested by the maintainers on the IBM LTO5.
- Every other row depends on reports from the community. Fixes for those drives are developed together with the reporter, who verifies them on the real drive.
- A "Community verified" status names the Aurora LTFS version that was verified. It is not re-verified for later versions unless someone reports again.

**Hardware donations are welcome.** A donated or loaned drive (a newer IBM LTO generation, an IBM enterprise drive, HP or Quantum) moves its row to "Maintained" and gets it tested for every release. Media are useful too. If you can help, please open an issue.

### Reporting a drive

Reports are welcome for any row that is not "Maintained", whether the drive works or not. Open an issue with the **Drive report** template and include:

- Drive vendor, model, generation and form factor, and the firmware level
- The line of `altfs -o device_list` that shows the drive
- HBA and interface (SAS, FC, ...), OS / distribution, Aurora LTFS version or commit hash
- What was tried: `mkaltfs`, mount, writing and reading files, unmount, remount, `altfsck`
- For a failure: the log around the first error, preferably with `-o loglevel=4` (from the terminal, or `/var/log/altfs.log` / the journal)

## LTFS Format Specifications

LTFS Format Specification defines data placement, index structure, and extended attribute names. The specification is published by [SNIA](https://www.snia.org/tech_activities/standards/curr_standards/ltfs) and forwarded to [ISO](https://www.iso.org/home.html) as ISO/IEC 20919.

  | Version | Status of SNIA                                                                                                        | Status of ISO                                                        |
  |:-------:|:---------------------------------------------------------------------------------------------------------------------:|:--------------------------------------------------------------------:|
  | 2.2     | [Published](https://www.snia.org/sites/default/files/LTFS_Format_2.2.0_Technical_Position.pdf)                             | [Published as `20919:2016`](https://www.iso.org/standard/69458.html) |
  | 2.3.1   | [Published](https://www.snia.org/sites/default/files/technical-work/ltfs/release/SNIA-LTFS-Format-2.3.1-TechPosition.pdf)  | -                                                                    |
  | 2.4     | [Published](https://www.snia.org/sites/default/files/technical_work/LTFS/LTFS_Format_2.4.0_TechPosition.pdf)               | -                                                                    |
  | 2.5.1   | [Published](https://www.snia.org/sites/default/files/technical-work/ltfs/release/SNIA-LTFS-Format-2-5-1-Standard.pdf) | [Published as `20919:2021`](https://www.iso.org/standard/80598.html) |

Aurora LTFS reads volumes of any format version from 1.0 to 2.x and writes labels and indexes at version 2.5.0. Version 2.5 changes nothing in the label or the full index; its one on-tape addition is the incremental index. The syncs that promise nothing about the state of the files (periodic sync, sync on close) write incremental indexes by default; `-o full_index_interval=<num>` changes that (`0`: full indexes only, like the reference implementation; `N`: N incremental indexes, then a full one; negative: incremental only, the default). An unmount and an explicit sync (`ltfs.sync`, `ltfs.commitMessage`, `ltfs.vendor.Aurora.FullSync`) write a full index whatever the setting, `ltfs.vendor.Aurora.IncrementalSync` an incremental one, and only full indexes are rollback points. After a failure `altfsck` replays the incremental indexes on top of the last full index, or leaves the volume at its last full index if they cannot be applied.

Interoperability: the LTFS reference implementation and the products built on it (IBM, HPE, Quantum, the macOS LTFS applications) accept labels and indexes of any 2.x version, so a cleanly unmounted volume written by Aurora LTFS mounts there, with a warning that the index is newer than the software. That is what the specification intends: version 2.5.1 asks implementations to read volumes with a higher minor version than their own (section 2.2) and states that a consistent volume containing incremental indexes poses no problem for earlier implementations (Annex H.2). What they cannot use is an incremental index: a volume that a failure left with incremental indexes after its last full index is recovered by them to that last full index, and the changes recorded only incrementally are lost until `altfsck` has replayed them. For a tape that other implementations will read after a failure, mount with `-o full_index_interval=0`. Independent implementations that are not derived from the reference code may check the version string strictly; none has been verified. When a volume written at an older version is modified, its next index is written at 2.5.0 (announced by `ALX0074W` at mount).

# Installing packages

Packages of the final releases are served from apt and dnf repositories on GitHub Pages, built for the Tier 1 platforms, and from a Homebrew tap for macOS. The repository metadata is signed with the project key, fingerprint `0CDE88E44068BEE3E9E42A66077C8C2ED60935A6`. Release candidates are not published there, only as assets of their [GitHub Release](https://github.com/AuroraTape/aurora-ltfs/releases), which also carries the packages of every release. To build from source instead, see [docs/developer/BUILDING.md](docs/developer/BUILDING.md).

## Ubuntu 24.04

Check that `gpg --show-keys` prints the fingerprint above before installing the key:

```
# curl -fsSL https://auroratape.github.io/aurora-ltfs/aurora-ltfs.gpg -o /tmp/aurora-ltfs.gpg
# gpg --show-keys /tmp/aurora-ltfs.gpg
# install -D -m 0644 /tmp/aurora-ltfs.gpg /etc/apt/keyrings/aurora-ltfs.gpg
# curl -fsSL https://auroratape.github.io/aurora-ltfs/aurora-ltfs.sources -o /etc/apt/sources.list.d/aurora-ltfs.sources
# apt update
# apt install altfs
```

## Rocky Linux 9 / RHEL 9

dnf shows the fingerprint when it imports the key; compare it before answering yes:

```
# curl -fsSL https://auroratape.github.io/aurora-ltfs/aurora-ltfs.repo -o /etc/yum.repos.d/aurora-ltfs.repo
# dnf install aurora-ltfs
```

The Python `xattr` module that `altfs_ordered_copy` needs is in CRB or EPEL (see [below](#the-altfs_ordered_copy-utility)).

## macOS

Through the Homebrew tap [AuroraTape/homebrew-tap](https://github.com/AuroraTape/homebrew-tap); macFUSE comes first, as a cask:

```
$ brew install --cask macfuse
$ brew install auroratape/tap/aurora-ltfs
```

Apple silicon gets a pre-built bottle (Homebrew in its default prefix, `/opt/homebrew`); Intel Macs build from source. macOS is a Tier 2 platform: the formula is built and tested on CI without mounting, and mounting needs macFUSE set up as described [below](#macos-mounting-without-the-kernel-extension-fskit-experimental) or with its kernel extension allowed.

## Container image

Release images are published to GHCR for x86_64. Images are tagged
`X.Y.Z` / `X.Y` / `X` only — there is deliberately no `latest` tag, so the
version you run never changes behind your back. Pick one explicitly: `X.Y`
follows the newest patch release of that line, `X.Y.Z` never moves.

```
# docker pull ghcr.io/auroratape/aurora-ltfs:1.0
```

The image has no entrypoint; it is a toolbox containing `altfs`, `mkaltfs`,
`altfsck` and `altfsindextool`. Tape access needs the SCSI generic device
passed through, and mounting additionally needs FUSE and `SYS_ADMIN`:

```
# List drives
docker run --rm ghcr.io/auroratape/aurora-ltfs:1.0 \
  altfs -o device_list

# Format a tape
docker run --rm --device /dev/sg0 ghcr.io/auroratape/aurora-ltfs:1.0 \
  mkaltfs -d /dev/sg0

# Mount a tape (foreground; Ctrl-C unmounts)
docker run --rm -it \
  --device /dev/fuse --device /dev/sg0 \
  --cap-add SYS_ADMIN --security-opt apparmor=unconfined \
  ghcr.io/auroratape/aurora-ltfs:1.0 \
  altfs -f -o devname=/dev/sg0 /ltfs
```

To make the mounted filesystem visible on the host instead of only inside
the container, bind-mount a host directory with shared propagation and
mount onto it: add `-v /mnt/ltfs:/ltfs:rshared` (the host path must be on a
mount with shared propagation).

## Updates

Updates come with `apt upgrade` / `dnf upgrade` / `brew upgrade`. The apt and dnf repositories carry every release line, so an upgrade moves to the newest release, also to a new minor version. To stay on a line, e.g. 1.0.x:

- apt: create `/etc/apt/preferences.d/aurora-ltfs` with

  ```
  Package: altfs libaltfs0 libaltfs-dev
  Pin: version 1.0.*
  Pin-Priority: 990
  ```

  New installs and upgrades then take the newest 1.0.x; a newer version that is already installed is not downgraded.
- dnf: add `includepkgs=aurora-ltfs-1.0.* libaltfs-1.0.* libaltfs-devel-1.0.*` to `/etc/yum.repos.d/aurora-ltfs.repo`. The repository then offers 1.0.x only.
- Homebrew: the tap carries only the newest release; `brew pin aurora-ltfs` keeps the installed version.

When the signing key is renewed (announced in the release notes beforehand), fetch `aurora-ltfs.gpg` again for apt; dnf imports the renewed key by itself.

## Uninstalling

```
# apt remove altfs libaltfs0
# rm /etc/apt/sources.list.d/aurora-ltfs.sources /etc/apt/keyrings/aurora-ltfs.gpg
```

```
# dnf remove aurora-ltfs libaltfs
# rm /etc/yum.repos.d/aurora-ltfs.repo
```

```
$ brew uninstall aurora-ltfs
$ brew untap auroratape/tap
```

The `altfs` user that the deb / rpm packages create for the mount service stays.

# Quick Start

This section is for users who already have Aurora LTFS installed.

## Step 1: List tape drives

```
# altfs -o device_list
```

The output shows available tape drives. Use the "Device Name" field (e.g., `/dev/sg43`) or the serial number as the argument to altfs commands.

```
Tape Device list:
Device Name = /dev/sg43, Vender ID = IBM    , Product ID = ULTRIUM-TD5    , Serial Number = 9A700L0077, Product Name = [ULTRIUM-TD5]
Device Name = /dev/sg38, Vender ID = IBM    , Product ID = ULT3580-TD6    , Serial Number = 00013B0119, Product Name = [ULT3580-TD6]
Device Name = /dev/sg37, Vender ID = IBM    , Product ID = ULT3580-TD7    , Serial Number = 00078D00C2, Product Name = [ULT3580-TD7]
```

## Step 2: Format a tape

LTFS uses the partition feature of the tape drive, so tapes must be formatted before first use.

```
# mkaltfs -d 9A700L0077
```

You can use either the serial number or the device name (e.g., `/dev/sg43`).

## Step 3: Mount a tape

```
# altfs -o devname=9A700L0077 /altfs
```

After successful mounting, access the tape contents through the `/altfs` directory.

> **Note:** Do not access any `st` devices while altfs is mounting a tape.

## Step 4: Unmount

```
# umount /altfs
```

The unmount command triggers the altfs process to write metadata and close the tape cleanly. The actual unmount completes when the altfs process finishes.

Messages of `altfs`, `mkaltfs`, `altfsck` and `altfsindextool` go to syslog. With the deb / rpm packages and rsyslog they are written to `/var/log/altfs.log` (RFC 3339 timestamps, rotated by logrotate) instead of the system log; see [conf/README.md](conf/README.md), which also has a syslog-ng example.

On Linux the deb / rpm packages install and enable `altfs.service`, which unmounts every mounted LTFS volume this way at shutdown or reboot and waits for the indexes to be written. It does nothing while the system is running, and a package upgrade never stops it. A build from source installs it too; see [docs/developer/BUILDING.md](docs/developer/BUILDING.md) for registering it.

## Mounting as a service (Linux)

A mount started from a login shell is part of the login session, and systemd stops sessions with a short timeout at shutdown (5 s for a desktop terminal on Ubuntu), which can kill `altfs` before the index is on the tape. For a drive that should be mounted all the time, or at boot, run the mount as a service instead: `altfs@<serial>.service` runs `altfs` as the unprivileged user `altfs` (created by the packages, ID 5432 when free) with its own stop timeout, and waits for the drive and for a cartridge when they are not ready, for example at boot. `altfsctl` sets it up:

```
# altfsctl check 9A700L0077
# altfsctl add --gid tapeusers --umask 007 --enable 9A700L0077 /mnt/ltfs
# systemctl start altfs@9A700L0077.service
```

`altfsctl check` tells you what is missing. Other users can only see the volume when `/etc/fuse.conf` contains `user_allow_other`, which lets every local user make such mounts; `altfsctl` adds it only with `--fix-fuse-conf`. LTFS stores no owners or permissions: without `--gid` / `--umask` every local user can read and write the volume. Stop the service with `systemctl stop`, which writes the index and unmounts. See `altfsctl(8)`.

## Browsing a tape without the tape

The directory tree of a cartridge can be mounted from an index file, with no drive and no cartridge: names, sizes, timestamps and extended attributes are there, file contents are not. Capture the index while the tape is available, either all the indexes on a partition with `altfsindextool`, or the latest one at every mount with `-o capture_index=<dir>`:

```
# altfsindextool -d 9A700L0077 --partition=1 --output-dir=/srv/catalog/9A700L0077
# altfs -o devname=9A700L0077 -o capture_index=/srv/catalog /altfs
```

Then mount the captured file:

```
# altfs -o index_file=/srv/catalog/9A700L0077.schema /mnt/9A700L0077
```

The mount is read-only. Reading a file fails with `ENODATA`; `ltfs.*` attributes that come from the index (`ltfs.volumeUUID`, `ltfs.indexGeneration`, `ltfs.startblock`, ...) are available, those that need the cartridge or the drive fail with `ENODATA`. The file must hold a full index; an incremental index alone does not describe the tree and is rejected. With `-o devname` as well, the tape is mounted read-only with that index and file contents can be read. See `-o index_file` in `altfs(8)`.

## macOS: mounting without the kernel extension (FSKit, experimental)

By default macFUSE mounts through its kernel extension, which on Apple silicon has to be enabled by booting into Recovery and lowering the startup security policy. macFUSE 5 (5.4 or later, macOS 15.4 or later) can mount through Apple's FSKit instead, with no kernel extension and no security change:

```
# altfs -o devname=0 -o backend=fskit /path/to/mountpoint
```

- Enable the FSKit module once: launch `/Library/Filesystems/macfuse.fs/Contents/Resources/macfuse.app`, then turn macFUSE on under System Settings > General > Login Items & Extensions > File System Extensions. Installing or upgrading the macfuse cask alone does not register it.
- Use a build that includes the fix for [#180](https://github.com/AuroraTape/aurora-ltfs/issues/180). Earlier builds silently lose data written through FSKit.
- Intel Macs: with macFUSE 5.4.0 the FSKit backend does not mount there. It crashes inside macFUSE when the file system binary is unsigned ([macfuse/macfuse#1205](https://github.com/macfuse/macfuse/issues/1205), fixed for macFUSE 5.5.0), and even with an ad-hoc signed binary the volume did not come up in our tests. Use the kernel extension there; on Intel it needs no security change.
- If the altfs process dies while mounted, unmounting that volume can hang and block Finder and anything else that lists mounts. Killing that volume's `io.macfuse.app.fsmodule.macfuse-local` process releases it.
- The evaluation is tracked in [#142](https://github.com/AuroraTape/aurora-ltfs/issues/142).

Keep the Mac awake while a tape is mounted, whichever backend you use, e.g. by running the session under `caffeinate -i` on AC power. Apple's FC driver for LSI HBAs (`AppleLSIFusionMPT`) has been seen to panic when tape I/O arrives while the system is asleep.

## The `altfs_ordered_copy` utility

[`altfs_ordered_copy`](src/cmd/altfs_ordered_copy/altfs_ordered_copy) is a Python utility to copy files with LTFS order optimization. It requires Python 3 and a Python `xattr` module, either `pyxattr` or `xattr` (both work). The deb package depends on `python3-pyxattr | python3-xattr`. On RHEL-likes both providers live in repositories that are not enabled by default (`python3-pyxattr` in CRB, `python3-xattr` in EPEL), so the rpm only recommends them: enable one of those repositories, or `pip install pyxattr`.

# Building from source

See [docs/developer/BUILDING.md](docs/developer/BUILDING.md) for the build dependencies, the build on Linux, macOS, FreeBSD and NetBSD, the test suites, and building the packages.

# Documentation

[docs/README.md](docs/README.md) is the index, grouped by reader:

- User: the man pages (`altfs(8)`, `mkaltfs(8)`, `altfsck(8)`, `altfsindextool(8)`, `altfsctl(8)` on Linux, `altfs_ordered_copy(1)`), configuration, troubleshooting
- Developer: [building from source](docs/developer/BUILDING.md), coding style, message IDs, tests, design documents
- Project: governance, the [release process](docs/project/RELEASE.md)

## Contributing

Please read [CONTRIBUTING.md](.github/CONTRIBUTING.md) for details on our code of conduct and the process for submitting pull requests.

## License

This project is licensed under the BSD License - see the [LICENSE](LICENSE) file for details.
