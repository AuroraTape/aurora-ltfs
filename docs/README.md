# Documentation

The [README](../README.md) covers what Aurora LTFS is, the supported platforms
and drives, installing the packages and a quick start. The documents here are
grouped by reader; an entry with an issue number is planned and not written
yet.

## User

- Command reference: the man pages, installed with the commands (sources in
  [man/sgml](../man/sgml)): `altfs(8)`, `mkaltfs(8)`, `altfsck(8)`,
  `altfsindextool(8)`, `altfsctl(8)` (Linux only), `altfs_ordered_copy(1)`.
  HTML pages come with the documentation site (#91).
- Configuration
  - Configuration guide: `altfs.conf`, plugins, keys, logging (#211)
  - Running a drive as a service: `altfs@.service` and `altfsctl` (#189)
  - [conf/README.md](../conf/README.md): the syslog, logrotate and systemd
    files, and a syslog-ng example
- Troubleshooting, including how to use `altfsck` (#212)
- [tests/realdrive/README.md](../tests/realdrive/README.md): checking a real
  tape drive, and what to send when reporting one

## Developer

- [How to build](developer/BUILDING.md): build dependencies, building on
  Linux, macOS, FreeBSD and NetBSD, running the test suites, building the
  packages
- [Contributing](../.github/CONTRIBUTING.md): how to propose a change
- [Coding style](developer/CODING_STYLE.md)
- [AI policy](developer/AI_POLICY.md)
- [Message IDs](../messages/README): the message catalogs and how IDs are
  allocated
- [Man pages](../man/README.md): maintaining the DocBook sources
- Writing tests, and using the `file` tape backend (#213)

### Design documents

- Components and layers (#214)
- Backend interfaces: tape, I/O scheduler, dcache, KMI (#215)
- Path failover and revalidation (#216)
- Error handling (#217)

## Project

- [Governance](project/GOVERNANCE.md): roles and decisions
- [Release process](project/RELEASE.md): versioning, branches, backports,
  the release checklist, the package repositories and the Homebrew tap,
  branch protection
