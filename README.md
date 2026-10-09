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

| Tier | Definition | Platforms |
|:----:|:-----------|:----------|
| Tier 1 | CI tested. Build failures block releases. | Ubuntu 24.04 (x86\_64), Rocky Linux 9 (x86\_64) |
| Tier 2 | Best effort. Builds are verified in CI, but failures do not block releases. | Ubuntu 26.04, Rocky Linux 10, macOS, Debian, FreeBSD |
| Tier 3 | Community-contributed. No guarantees from maintainers. | NetBSD, other platforms |

A minor release line (`X.Y`) receives fixes until six months after the next minor release. How the tiers are chosen, what the CI verifies on each platform and when Tier 1 moves to a newer release: [docs/project/PLATFORM_SUPPORT.md](docs/project/PLATFORM_SUPPORT.md).

## Supported Tape Drives

The maintainers develop and test with an IBM LTO5. IBM LTO6 to LTO9 and TS1140 to TS1160 are handled by the same code and listed as supported by the reference implementation, but not re-verified with Aurora LTFS; HP and Quantum LTO5 to LTO9 drives are recognized but untested, except HP LTO6, verified by a community member. The drive table with the minimum firmware levels, the testing policy and how to report a drive: [docs/user/DRIVES.md](docs/user/DRIVES.md). Hardware donations are welcome.

## LTFS Format Specifications

Aurora LTFS targets the [LTFS Format Specification 2.5.1](https://www.snia.org/sites/default/files/technical-work/ltfs/release/SNIA-LTFS-Format-2-5-1-Standard.pdf) (ISO/IEC 20919:2021). It reads volumes of any format version from 1.0 to 2.x and writes labels and indexes at version 2.5.0, which the other LTFS implementations mount. The specification versions, incremental indexes and interoperability with other implementations: [docs/user/FORMAT.md](docs/user/FORMAT.md).

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

A mount started from a login shell is stopped with the login session at shutdown, with a timeout too short for the index write. For a drive that should be mounted all the time, or at boot, run the mount as a service instead: `altfs@<serial>.service` runs `altfs` as the unprivileged user `altfs`, with its own stop timeout, and waits for the drive and for a cartridge when they are not ready. `altfsctl` sets it up:

```
# altfsctl check 9A700L0077
# altfsctl add --gid tapeusers --umask 007 --enable 9A700L0077 /mnt/ltfs
# systemctl start altfs@9A700L0077.service
```

[docs/user/SERVICE.md](docs/user/SERVICE.md) walks through the setup, who can access the volume, day-to-day operation, the logs and troubleshooting.

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
- Use version 1.0.2 or later. Earlier versions silently lose data written through FSKit: a write request larger than a tape block lost its tail.
- Intel Macs: with macFUSE 5.4.0 the FSKit backend does not mount there. It crashes inside macFUSE when the file system binary is unsigned ([macfuse/macfuse#1205](https://github.com/macfuse/macfuse/issues/1205), fixed for macFUSE 5.5.0), and even with an ad-hoc signed binary the volume did not come up in our tests. Use the kernel extension there; on Intel it needs no security change.
- If the altfs process dies while mounted, unmounting that volume can hang and block Finder and anything else that lists mounts. Killing that volume's `io.macfuse.app.fsmodule.macfuse-local` process releases it.

Keep the Mac awake while a tape is mounted, whichever backend you use, e.g. by running the session under `caffeinate -i` on AC power. Apple's FC driver for LSI HBAs (`AppleLSIFusionMPT`) has been seen to panic when tape I/O arrives while the system is asleep.

## The `altfs_ordered_copy` utility

[`altfs_ordered_copy`](src/cmd/altfs_ordered_copy/altfs_ordered_copy) is a Python utility to copy files with LTFS order optimization. It requires Python 3 and a Python `xattr` module, either `pyxattr` or `xattr` (both work). The deb package depends on `python3-pyxattr | python3-xattr`. On RHEL-likes both providers live in repositories that are not enabled by default (`python3-pyxattr` in CRB, `python3-xattr` in EPEL), so the rpm only recommends them: enable one of those repositories, or `pip install pyxattr`.

# Building from source

See [docs/developer/BUILDING.md](docs/developer/BUILDING.md) for the build dependencies, the build on Linux, macOS, FreeBSD and NetBSD, the test suites, and building the packages.

# Documentation

[docs/README.md](docs/README.md) is the index, grouped by reader:

- User: the [command reference](docs/user/reference/README.md) (the man pages), [running a drive as a service](docs/user/SERVICE.md), [supported tape drives](docs/user/DRIVES.md), the [LTFS format versions](docs/user/FORMAT.md), configuration, checking a real drive
- Developer: [building from source](docs/developer/BUILDING.md), coding style, AI policy, message IDs, man pages
- Project: governance, [platform support](docs/project/PLATFORM_SUPPORT.md), the [release process](docs/project/RELEASE.md)

## Contributing

Please read [CONTRIBUTING.md](.github/CONTRIBUTING.md) for details on our code of conduct and the process for submitting pull requests.

## License

This project is licensed under the BSD License - see the [LICENSE](LICENSE) file for details.
