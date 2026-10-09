# Supported tape drives

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

- **Maintained** - the maintainers develop and test with this drive. Today
  that is the IBM LTO5 only.
- **Inherited** - listed as supported, with this minimum firmware level, by
  the reference implementation Aurora LTFS is based on, and handled by the
  same code. Not re-verified with Aurora LTFS, because the maintainers do not
  have the drive.
- **Community verified (version)** - a community member verified the drive on
  real hardware with that Aurora LTFS version. HP LTO6 was verified this way.
  The firmware level of the reporting drive is not a tested minimum, so the
  column stays "Not determined".
- **Untested** - the drive is recognized and its code path exists, but no
  minimum firmware level was ever established and nobody has reported a
  result with Aurora LTFS. It may work, work with limitations, or fail.

## Drive testing policy

The only tape drive available to the maintainers is an IBM LTO5. CI has no
tape hardware at all (it exercises the `file` backend), so:

- Releases are tested by the maintainers on the IBM LTO5.
- Every other row depends on reports from the community. Fixes for those
  drives are developed together with the reporter, who verifies them on the
  real drive.
- A "Community verified" status names the Aurora LTFS version that was
  verified. It is not re-verified for later versions unless someone reports
  again.

**Hardware donations are welcome.** A donated or loaned drive (a newer IBM
LTO generation, an IBM enterprise drive, HP or Quantum) moves its row to
"Maintained" and gets it tested for every release. Media are useful too. If
you can help, please open an issue.

## Reporting a drive

Reports are welcome for any row that is not "Maintained", whether the drive
works or not. Open an issue with the **Drive report** template and include:

- Drive vendor, model, generation and form factor, and the firmware level
- The line of `altfs -o device_list` that shows the drive
- HBA and interface (SAS, FC, ...), OS / distribution, Aurora LTFS version or
  commit hash
- What was tried: `mkaltfs`, mount, writing and reading files, unmount,
  remount, `altfsck`
- For a failure: the log around the first error, preferably with
  `-o loglevel=4` (from the terminal, or `/var/log/altfs.log` / the journal)

The scripts in [tests/realdrive](../../tests/realdrive/README.md) run a drive
through these steps and write a report you can attach.
