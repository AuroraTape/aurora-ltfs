[![BSD License](http://img.shields.io/badge/license-BSD-blue.svg?style=flat)](LICENSE)

# Aurora LTFS

Aurora LTFS is a filesystem implementation that allows mounting LTFS-formatted tapes as regular filesystems. Once mounted, users can access tape contents through standard filesystem APIs.

This project is based on the [Linear Tape File System (LTFS)](https://github.com/LinearTapeFileSystem/ltfs) reference implementation and aims to be compliant with the LTFS format specifications defined by [SNIA](https://www.snia.org/tech_activities/standards/curr_standards/ltfs).

The current target is the [LTFS Format Specification 2.5.1](https://www.snia.org/sites/default/files/technical-work/ltfs/release/SNIA-LTFS-Format-2-5-1-Standard.pdf).

## Goals

- **Modern development practices** — CI/CD, Dev Containers, and AI-assisted development to improve developer experience.
- **High-quality code through testing** — Expand automated test coverage to catch regressions early and deliver reliable software.
- **Up-to-date platform support** — Free from corporate politics, we continuously support modern operating systems that reflect the current landscape.
- **Community-driven development** — Open governance and transparent decision-making to encourage contributions from the broader tape storage community.

## Platform Support Policy

We use a tiered support model combined with OS lifecycle tracking.

| Tier | Definition | Platforms |
|:----:|:-----------|:----------|
| Tier 1 | CI tested. Build failures block releases. | Ubuntu 24.04 (x86\_64), Rocky Linux 9 (x86\_64) |
| Tier 2 | Best effort. Builds are verified but not in CI. | macOS, Debian, FreeBSD |
| Tier 3 | Community-contributed. No guarantees from maintainers. | NetBSD, other platforms |

**Tier 1 selection policy:**

- One distribution per major Linux family (Debian-based and RHEL-based).
- Only the latest LTS or stable release of each distribution is selected.
- When a new LTS is released, a transition period of up to 6 months is provided before the previous version is dropped.
- When a Tier 1 distribution reaches EOL, it is replaced in the next release cycle.

Tier 2 and Tier 3 platforms may be promoted or added based on community demand and contributor availability.

## Supported Tape Drives

  | Vendor  | Drive Type              | Minimum F/W Level |
  |:-------:|:-----------------------:|:-----------------:|
  | IBM     | LTO5                    | B170              |
  | IBM     | LTO6                    | None              |
  | IBM     | LTO7                    | None              |
  | IBM     | LTO8                    | HB81              |
  | IBM     | LTO9                    | None              |
  | IBM     | TS1140                  | 3694              |
  | IBM     | TS1150                  | None              |
  | IBM     | TS1155                  | None              |
  | IBM     | TS1160                  | None              |
  | HP      | LTO5                    | T.B.D.            |
  | HP      | LTO6                    | T.B.D.            |
  | HP      | LTO7                    | T.B.D.            |
  | HP      | LTO8                    | T.B.D.            |
  | HP      | LTO9                    | T.B.D.            |
  | Quantum | LTO5 (Only Half Height) | T.B.D.            |
  | Quantum | LTO6 (Only Half Height) | T.B.D.            |
  | Quantum | LTO7 (Only Half Height) | T.B.D.            |
  | Quantum | LTO8 (Only Half Height) | T.B.D.            |
  | Quantum | LTO9 (Only Half Height) | T.B.D.            |

## LTFS Format Specifications

LTFS Format Specification defines data placement, index structure, and extended attribute names. The specification is published by [SNIA](https://www.snia.org/tech_activities/standards/curr_standards/ltfs) and forwarded to [ISO](https://www.iso.org/home.html) as ISO/IEC 20919.

  | Version | Status of SNIA                                                                                                        | Status of ISO                                                        |
  |:-------:|:---------------------------------------------------------------------------------------------------------------------:|:--------------------------------------------------------------------:|
  | 2.2     | [Published](https://www.snia.org/sites/default/files/LTFS_Format_2.2.0_Technical_Position.pdf)                             | [Published as `20919:2016`](https://www.iso.org/standard/69458.html) |
  | 2.3.1   | [Published](https://www.snia.org/sites/default/files/technical-work/ltfs/release/SNIA-LTFS-Format-2.3.1-TechPosition.pdf)  | -                                                                    |
  | 2.4     | [Published](https://www.snia.org/sites/default/files/technical_work/LTFS/LTFS_Format_2.4.0_TechPosition.pdf)               | -                                                                    |
  | 2.5.1   | [Published](https://www.snia.org/sites/default/files/technical-work/ltfs/release/SNIA-LTFS-Format-2-5-1-Standard.pdf) | [Published as `20919:2021`](https://www.iso.org/standard/80598.html) |

# Quick Start

This section is for users who already have Aurora LTFS installed.

## Step 1: List tape drives

```
# ltfs -o device_list
```

The output shows available tape drives. Use the "Device Name" field (e.g., `/dev/sg43`) or the serial number as the argument to ltfs commands.

```
Tape Device list:
Device Name = /dev/sg43, Vender ID = IBM    , Product ID = ULTRIUM-TD5    , Serial Number = 9A700L0077, Product Name = [ULTRIUM-TD5]
Device Name = /dev/sg38, Vender ID = IBM    , Product ID = ULT3580-TD6    , Serial Number = 00013B0119, Product Name = [ULT3580-TD6]
Device Name = /dev/sg37, Vender ID = IBM    , Product ID = ULT3580-TD7    , Serial Number = 00078D00C2, Product Name = [ULT3580-TD7]
```

## Step 2: Format a tape

LTFS uses the partition feature of the tape drive, so tapes must be formatted before first use.

```
# mkltfs -d 9A700L0077
```

You can use either the serial number or the device name (e.g., `/dev/sg43`).

## Step 3: Mount a tape

```
# ltfs -o devname=9A700L0077 /ltfs
```

After successful mounting, access the tape contents through the `/ltfs` directory.

> **Note:** Do not access any `st` devices while ltfs is mounting a tape.

## Step 4: Unmount

```
# umount /ltfs
```

The unmount command triggers the ltfs process to write metadata and close the tape cleanly. The actual unmount completes when the ltfs process finishes.

## The `ltfs_ordered_copy` utility

[`ltfs_ordered_copy`](src/utils/ltfs_ordered_copy) is a Python utility to copy files with LTFS order optimization. It requires the `pyxattr` module.

# Building from Source

## Prerequisites

### Linux

Dev Container definitions are available for quick setup:

- [Rocky Linux 9](.devcontainer/rocky9/)
- [Ubuntu 24.04](.devcontainer/ubuntu2404/)

These Dockerfiles contain the full list of required packages. You can use them directly with VS Code Dev Containers or as a reference for setting up your local environment.

### macOS (Homebrew)

Install the following packages via Homebrew. Note that SNMP is not supported on macOS.

```
automake autoconf libtool osxfuse ossp-uuid libxml2 icu4c gnu-sed
```

### FreeBSD

Install the following packages. FreeBSD 10.2 or later is required for sa(4) driver support.

```
automake autoconf libtool fusefs-libs net-snmp e2fsprogs-libuuid libxml2 icu
```

### NetBSD

Install the following packages. NetBSD 7.0 or later is required for FUSE support.

```
automake autoconf libtool libfuse net-snmp libuuid libxml2 icu
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

Build (SNMP is not supported on macOS):

```bash
./autogen.sh
LDFLAGS="-framework CoreFoundation -framework IOKit" ./configure --disable-snmp
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
