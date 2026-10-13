# Security policy

## Supported versions

Security fixes go to `main` and to every release line that is still in its
support window: a minor release line (`X.Y`) receives fixes until six months
after the next minor release (see
[Platform support](https://github.com/AuroraTape/aurora-ltfs/blob/main/docs/project/PLATFORM_SUPPORT.md#support-window)). A fix is
released as a patch release of each of those lines.

## Reporting a vulnerability

Please do not report a vulnerability in a public issue, pull request or
discussion.

- Preferred: GitHub's private vulnerability reporting, with **Report a
  vulnerability** on the
  [Security tab](https://github.com/AuroraTape/aurora-ltfs/security) of the
  repository. The report and the discussion of the fix stay private until an
  advisory is published.
- By e-mail: `auroratape@googlegroups.com`. Only the maintainers can read
  the messages sent to this address.

Include what you can of:

- The affected version (`altfs --version`) or commit, the OS and the tape
  backend (e.g. `sg`, `iokit`, `cam`, `file`)
- What an attacker controls (a crafted cartridge or index file, a local
  user, a configuration file) and what they gain
- Steps or a file that reproduce it

## What counts

Aurora LTFS runs as root with raw access to the tape drive and reads data
it did not write: a cartridge, an index file, a configuration file.
Examples of what to report privately:

- A crafted LTFS label, index or extended attribute on a cartridge, or an
  index file given with `-o rollback_mount`, that crashes `altfs`, `altfsck`
  or `altfsindextool`, corrupts memory, or makes them write outside the
  volume
- A way for an unprivileged user to reach data or operations on a mounted
  volume that its permissions do not allow
- Problems in the signed package repositories or the release artifacts

A crash or a data loss caused by a faulty drive, cartridge or host, with
no attacker involved, is an ordinary bug: open an issue.
