# Documentation

The [README](../README.md) covers what Aurora LTFS is, the supported platforms
and drives, installing the packages and a quick start. The documents here are
grouped by reader.

## User

- [Command reference](user/reference/README.md): the man pages of
  `altfs(8)`, `mkaltfs(8)`, `altfsck(8)`, `altfsindextool(8)`, `altfsctl(8)`
  (Linux only) and `altfs_ordered_copy(1)`, also installed with the commands
- [Running a drive as a service](user/SERVICE.md) (Linux): mounting with
  `altfs@<serial>.service`, set up by `altfsctl`; access, operation, logs,
  shutdown, troubleshooting
- [Configuration](user/CONFIGURATION.md): `altfs.conf` and
  `altfs.conf.local`, plugins and defaults, encryption keys, the mount
  options a site usually sets, logging
  - [conf/README.md](../conf/README.md): the syslog, logrotate and systemd
    files, and a syslog-ng example
- [Supported tape drives](user/DRIVES.md): the drive table with the minimum
  firmware levels, the testing policy, how to report a drive
- [tests/realdrive/README.md](../tests/realdrive/README.md): checking a real
  tape drive, and what to send when reporting one
- [LTFS format versions](user/FORMAT.md): the specification versions, what
  Aurora LTFS reads and writes, incremental indexes, interoperability with
  other implementations

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

### Design

- [Backend interfaces](developer/design/BACKENDS.md): the four plugin
  tables (tape backend, I/O scheduler, dentry cache, key manager), how a
  plugin is loaded, what each operation must do, what the dispatch layers
  in libaltfs add around them, the existing implementations

## Project

- [Governance](project/GOVERNANCE.md): roles and decisions
- [Platform support](project/PLATFORM_SUPPORT.md): the tiers, what the CI
  verifies on each platform, the Tier 1 selection policy, the support window
- [Release process](project/RELEASE.md): versioning, branches, backports,
  the release checklist, the package repositories and the Homebrew tap,
  branch protection
