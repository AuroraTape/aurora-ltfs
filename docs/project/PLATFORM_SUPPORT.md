# Platform support

Aurora LTFS uses a tiered support model combined with OS lifecycle tracking.

| Tier | Definition | Platforms |
|:----:|:-----------|:----------|
| Tier 1 | CI tested. Build failures block releases. | Ubuntu 24.04 (x86\_64), Rocky Linux 9 (x86\_64) |
| Tier 2 | Best effort. Builds are verified in CI, but failures do not block releases. | Ubuntu 26.04, Rocky Linux 10, macOS, Debian, FreeBSD |
| Tier 3 | Community-contributed. No guarantees from maintainers. | NetBSD, other platforms |

On macOS, mounting is supported through the FSKit backend of macFUSE 5
(macOS 15.4 or later, `-o backend=fskit`); the macFUSE kernel extension
backend is not supported.

## What the CI verifies

CI verifies that all Tier 2 platforms (Ubuntu 26.04, Rocky Linux 10, macOS,
Debian, FreeBSD) and NetBSD build successfully. On macOS, FreeBSD and NetBSD
it also runs the tests that need no FUSE mount (command-line paths, plugin
loading, `mkaltfs` / `altfsck` / `altfsindextool` on the file backend), and
on macOS it checks and recovers volumes written by the Linux job. The tests
that mount run on Linux, and experimentally on the FreeBSD VM, which has a
full kernel; the hosted macOS runners cannot mount, the NetBSD VM hangs in
puffs on some of them, and CI has no tape hardware. Test failures on Tier 2
and Tier 3 platforms do not block.

The tests themselves, and how to run them, are described in
[How to build](../developer/BUILDING.md). Tape drives are covered separately:
the CI exercises the `file` backend only, and releases are tested on real
hardware by the maintainers, see [Supported tape drives](../user/DRIVES.md).

## Tier 1 selection policy

- One maintained LTS or stable release per major Linux family (Debian-based
  and RHEL-based). These are the releases the packages are built on.
- The move to a newer release is decided once per development cycle, not on a
  fixed clock. Criteria: GitHub-hosted runners for the new release, the build
  and test toolchain (FUSE, ICU, libxml2, pytest) confirmed on it, and the new
  release having become the mainstream deployment target. Tape systems are
  conservative, and packages built on the older release install on the widest
  range of systems, so the move is made when users are there, not when the
  release is.
- Until the move, the successor release (currently Ubuntu 26.04 and Rocky
  Linux 10) is a Tier 2 build target, so that toolchain regressions show up
  early.
- A Tier 1 distribution that reaches EOL is replaced in the next release
  cycle; that is the hard limit.

Tier 2 and Tier 3 platforms may be promoted or added based on community demand
and contributor availability.

## Support window

A minor release line (`X.Y`) receives fixes on its `release/X.Y` branch until
six months after the next minor release. How releases are made is described in
[Release process](RELEASE.md).
