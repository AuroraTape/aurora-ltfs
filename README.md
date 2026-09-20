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
| Tier 2 | Best effort. Builds are verified in CI, but failures do not block releases. | macOS, Debian, FreeBSD |
| Tier 3 | Community-contributed. No guarantees from maintainers. | NetBSD, other platforms |

CI verifies that all Tier 2 platforms (macOS, Debian, FreeBSD) and NetBSD build successfully (build verification only — no functional tests, since CI has no tape hardware).

**Tier 1 selection policy:**

- One distribution per major Linux family (Debian-based and RHEL-based).
- Only the latest LTS or stable release of each distribution is selected.
- When a new LTS is released, a transition period of up to 6 months is provided before the previous version is dropped.
- When a Tier 1 distribution reaches EOL, it is replaced in the next release cycle.

Tier 2 and Tier 3 platforms may be promoted or added based on community demand and contributor availability.

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

Aurora LTFS reads volumes of any format version from 1.0 to 2.x and writes labels and indexes at version 2.5.0. The syncs that promise nothing about the state of the files (periodic sync, sync on close) write incremental indexes, the on-tape addition of version 2.5; an unmount and an explicit sync (`ltfs.sync`, `ltfs.vendor.Aurora.FullSync`) write a full index, and only full indexes are rollback points. After a failure `altfsck` replays the incremental indexes on top of the last full index, or leaves the volume at its last full index if they cannot be applied; other LTFS implementations recover to the last full index. When a volume written at an older version is modified, its next index is written at 2.5.0 (announced by `ALX0074W` at mount); other LTFS implementations may then refuse the volume. Preserving the version of existing volumes is tracked in [#66](https://github.com/AuroraTape/aurora-ltfs/issues/66).

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

On Linux the deb / rpm packages install and enable `altfs.service`, which unmounts every mounted LTFS volume this way at shutdown or reboot and waits for the indexes to be written. It does nothing while the system is running, and a package upgrade never stops it. When building from source with a prefix other than `/usr`, register the unit yourself: `systemctl enable --now <prefix>/lib/systemd/system/altfs.service`.

## The `altfs_ordered_copy` utility

[`altfs_ordered_copy`](src/cmd/altfs_ordered_copy/altfs_ordered_copy) is a Python utility to copy files with LTFS order optimization. It requires Python 3 and a Python `xattr` module, either `pyxattr` or `xattr` (both work). The deb package depends on `python3-pyxattr | python3-xattr`. On RHEL-likes both providers live in repositories that are not enabled by default (`python3-pyxattr` in CRB, `python3-xattr` in EPEL), so the rpm only recommends them: enable one of those repositories, or `pip install pyxattr`.

# Running with Docker

Release images are published to GHCR for x86_64. Images are tagged
`X.Y.Z` / `X.Y` / `X` only — there is deliberately no `latest` tag, so the
version you run never changes behind your back. Pick one explicitly:

```
# docker pull ghcr.io/auroratape/aurora-ltfs:1.0.0
```

The image has no entrypoint; it is a toolbox containing `altfs`, `mkaltfs`,
`altfsck` and `altfsindextool`. Tape access needs the SCSI generic device
passed through, and mounting additionally needs FUSE and `SYS_ADMIN`:

```
# List drives
docker run --rm ghcr.io/auroratape/aurora-ltfs:1.0.0 \
  altfs -o device_list

# Format a tape
docker run --rm --device /dev/sg0 ghcr.io/auroratape/aurora-ltfs:1.0.0 \
  mkaltfs -d /dev/sg0

# Mount a tape (foreground; Ctrl-C unmounts)
docker run --rm -it \
  --device /dev/fuse --device /dev/sg0 \
  --cap-add SYS_ADMIN --security-opt apparmor=unconfined \
  ghcr.io/auroratape/aurora-ltfs:1.0.0 \
  altfs -f -o devname=/dev/sg0 /ltfs
```

To make the mounted filesystem visible on the host instead of only inside
the container, bind-mount a host directory with shared propagation and
mount onto it: add `-v /mnt/ltfs:/ltfs:rshared` (the host path must be on a
mount with shared propagation).

# Building from Source

## Prerequisites

### Linux

Dev Container definitions are available for quick setup:

- [Rocky Linux 9](.devcontainer/rocky9/)
- [Ubuntu 24.04](.devcontainer/ubuntu2404/)

These Dockerfiles contain the full list of required packages. You can use them directly with VS Code Dev Containers or as a reference for setting up your local environment.

### macOS (Homebrew)

Install the following packages via Homebrew.

```
automake autoconf libtool pkg-config macfuse ossp-uuid libxml2 icu4c gnu-sed
```

The ICU tools (`genrb`/`pkgdata`) must be the Homebrew `icu4c` ones found
via `PATH` at configure time. A legacy `/Library/Frameworks/ICU.framework`
(e.g. ICU 4.8 from old LTFS SDE installs) is not supported and is ignored
by the build.

### FreeBSD

Install the following packages. FreeBSD 10.2 or later is required for sa(4) driver support.

```
automake autoconf libtool pkgconf gmake fusefs-libs libuuid libxml2 icu
```

### NetBSD

Install the following packages. NetBSD 7.0 or later is required for FUSE support.

```
automake autoconf libtool-base pkgconf gmake fuse libuuid libxml2 icu
```

## Linux

```bash
./autogen.sh
./configure
make
make install
```

`./configure --help` shows various options for build and install.

In some systems, you might need `sudo ldconfig -v` after `make install` to load the shared libraries correctly.

## macOS

Set up the environment:

```bash
export ICU_PATH="/usr/local/opt/icu4c/bin"
export LIBXML2_PATH="/usr/local/opt/libxml2/bin"
export PKG_CONFIG_PATH="/usr/local/opt/icu4c/lib/pkgconfig:/usr/local/opt/libxml2/lib/pkgconfig"
export PATH="$PATH:$ICU_PATH:$LIBXML2_PATH"
```

Build:

```bash
./autogen.sh
LDFLAGS="-framework CoreFoundation -framework IOKit" ./configure
make
make install
```

## FreeBSD

```bash
./autogen.sh
./configure --prefix=/usr/local --mandir=/usr/local/man
make
make install
```

## NetBSD

```bash
./autogen.sh
./configure
make
make install
```

## Contributing

Please read [CONTRIBUTING.md](.github/CONTRIBUTING.md) for details on our code of conduct and the process for submitting pull requests.

## License

This project is licensed under the BSD License - see the [LICENSE](LICENSE) file for details.
