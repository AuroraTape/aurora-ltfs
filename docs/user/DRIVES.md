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

## Vendor notes

Drives are told apart by the vendor and product strings of INQUIRY. HP and
HPE drives, and the Tandberg LTO5 and LTO6 half-height drives, take the HP
code paths; Quantum has two product lines ("ULTRIUM-HHn", and "ULTRIUM n"
for LTO5 and LTO6). What differs per vendor, and what users of those drives
do not get:

**HP LTO5 and LTO6.** These drives have neither the Read/Write Control mode
page (0x25) nor the Device Configuration Extension sub-page (0x10, sub-page
0x01). The `sg` backend answers requests for them as unsupported, and
libltfs skips, silently, what depends on them:

- the density code update when a cartridge is formatted (the cartridge
  keeps the density the drive chooses);
- the programmable early warning setting (the drive's own early warning is
  still honoured);
- append-only mode, which cannot be enabled or read.

Encryption still works: the key is set without the mode page. These
adaptations exist in the `sg` backend only: on macOS (`iokit`) and FreeBSD
(`cam`) the mode page requests go to the drive as they are, and an HP LTO5 or
LTO6 is expected to fail there.

**HP LTO, all generations.** With the `sg` backend the `ltfs.mediaEncrypted`
attribute is answered from the Next Block Encryption Status page (SECURITY
PROTOCOL IN 0x21) and `ltfs.driveEncryptionState` from the Data Encryption
Status page (0x20); the other vendors read the Read/Write Control mode page
for both.

**Volume Coherency Information.** Some drives do not flush the volume
coherency information with a non-immediate WRITE FILEMARKS; HP LTO6 was
observed doing this, and the next mount then ran a full consistency check.
Aurora LTFS issues one more `WRITE FILEMARKS(0)` after every non-immediate
file mark write, on every drive; on drives that flush as specified the extra
command is short, since the data and the coherency information were already
flushed.

**Remaining capacity.** LTO5 drives of any vendor, HP LTO6 and the Quantum
"ULTRIUM 5" and "ULTRIUM 6" read the remaining capacity from the Tape
Capacity log page (0x31); the other drives from the Volume Statistics log
page (0x17). The `sg`, `iokit` and `cam` backends all do this.

**IBM only.** Logical block protection (the `scsi_lbprotect` option of the
`sg` backend) is set up on IBM drives only; on HP and Quantum drives the
option has no effect. Drive dumps on an error are taken from IBM drives only
(see [Troubleshooting](TROUBLESHOOTING.md#drive-and-host-problems)). The
minimum firmware level is checked for IBM drives only, which is why the
other rows of the table say "Not determined".

**Timeouts and sense codes.** Command timeouts come from the drive's own
REPORT SUPPORTED OPERATION CODES when it answers; otherwise from a table per
vendor (IBM, HP, Quantum), and failing that from the IBM table. Sense codes
are translated with a standard table plus a vendor table for IBM, HP and
Quantum.

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

**Hardware donations are welcome.** A donated or loaned drive moves its row
to "Maintained" and gets it tested for every release. Wanted most:

- IBM LTO8 and LTO9, the generations most sites run today
- HP and Quantum drives of any generation, to verify the vendor-specific
  paths described in "Vendor notes"
- IBM enterprise drives (TS1140 to TS1160)

The drive has to run on its own: an internal or an external (tabletop)
drive with a SAS interface; for Fibre Channel, ask first. A drive taken out
of a tape library, still in its library sled, usually cannot be powered or
connected without the library and cannot be used. A time-limited loan, or
remote access to a machine with the drive attached, helps as much as a
donation. Media are useful too. Running the real-drive checks on your own
drive and sending a report (see below) helps even without any hardware
changing hands.

Write to `auroratape@googlegroups.com`; only the maintainers can read the
messages sent to this address. Please do not post shipping addresses or
company details in an issue.

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
  `-o verbose=3` (from the terminal, or `/var/log/altfs.log` / the journal)

The scripts in [tests/realdrive](../../tests/realdrive/README.md) run a drive
through these steps and write a report you can attach.
