# IBM drive-dump SCSI trace reader (experimental)

`ibm_dump.py` reads an **existing binary drive dump** offline. It never opens a
drive or mounts a tape. Python 3.9+ and `gzip` (with UNIX compress support) are
required; there are no third-party Python dependencies.

The implementation was derived from two dumps of an IBM ULT3580-TD5, firmware
H976. This is **not an IBM-supported decoder or a general IBM dump specification**.
The accepted trace profile is `peamc011400` / `pf170907f`. Other firmware profiles
can be inventoried but are not decoded. Only the outer snapshot is processed.
Historical embedded dumps are skipped without parsing or validating their contents.

## Usage

From the repository root:

```sh
python3 contrib/ibm-dump/ibm_dump.py /path/to/drive_f.dmp
python3 contrib/ibm-dump/ibm_dump.py /path/to/drive_f.dmp --format json > trace.json
python3 contrib/ibm-dump/ibm_dump.py /path/to/drive_f.dmp --one-line

# MODE SENSE(6)/(10), LOG SENSE, and READ POSITION, including captured data
python3 contrib/ibm-dump/ibm_dump.py /path/to/drive_f.dmp \
    --opcode 0x1a --opcode 0x5a --opcode 0x4d --opcode 0x34

# Only commands whose management transfer data is still retained
python3 contrib/ibm-dump/ibm_dump.py /path/to/drive_f.dmp --with-data

# Every Sense record, including records without a matched command
python3 contrib/ibm-dump/ibm_dump.py /path/to/drive_f.dmp --sense-only
python3 contrib/ibm-dump/ibm_dump.py /path/to/drive_f.dmp --sense-only --format json

# CHECK CONDITION commands and Sense data; --verbose adds source locations
python3 contrib/ibm-dump/ibm_dump.py /path/to/drive_f.dmp --check-condition --verbose

python3 contrib/ibm-dump/ibm_dump.py /path/to/drive_f.dmp --list-snapshots
```

Only the outer snapshot (`0`) is available. For compatibility, `--snapshot 0`
and `--snapshot all` are both accepted and both process only the outer snapshot.
`--lun`, repeatable `--opcode`,
`--with-data`, `--check-condition`, and `--limit` filter the displayed command
list. JSON retains the snapshot's event list even when the command list is
filtered, so unassociated Status and Sense records are not silently discarded.
Normal text output prints Sense Key/ASC/ASCQ, fixed-format FM/EOM/ILI flags,
IBM Extra Fields, and the entire captured Sense buffer as a hex dump.
Unassociated or ambiguous records are inserted at their event times, headed by
`-?-> time group kind [association]` (Status also includes its tag). Records older
than the earliest retained command in the **same ring group** are omitted from
normal text output; a group with no retained commands has no age cutoff.
These records remain in JSON. Unassociated transfers show metadata only, because
their payload might be READ/WRITE data. There is no trailing unassociated-event
summary. When command filters are used, unassociated records are omitted from
text because their relationship to the selected commands cannot be established.
`--sense-only` lists all Sense records, including older ones, in time order and cannot
be combined with command filters, because Sense records do not carry a command
key or reliable LUN. It works with `--snapshot`, `--format`, and `--verbose`.
No per-command Transfer line is printed when no associated payload is present.
Each command is grouped into a send (`-N->`) and response (`<-N-`) block,
where `N` is the decimal LUN. Both headers show the recorded event time and a
four-digit hexadecimal tag. The response uses the Status time, not the command
time. Send, response, and unassociated-event blocks are ordered by their header
timestamps, so overlapping commands may be interleaved. Associated DATA and
Sense stay inside their command's send/response block.
If Status is missing or ambiguous, no response header or timestamp is invented;
`STATUS NOT CAPTURED/AMBIGUOUS` is printed instead.
Host-to-device DATA appears with the send block; device-to-host DATA appears
with the response. Unknown-direction DATA is explicitly labelled as such.
CDB hex, DATA, Decoded, and Sense headings are indented two spaces; IBM Extra
Fields entries and raw Sense hex rows are indented four spaces.
`--verbose` adds ring group, source locations, association details, raw Status,
and Sense response code, lengths, Information and FRU fields.
Command names use underscores instead of spaces and omit parentheses around
CDB lengths (`READ6`, `LOCATE16`, `MODE_SENSE10`). WRITE FILEMARKS is shortened
to `WRITEFM6`/`WRITEFM16`, READ POSITION to `READPOS`, and TEST UNIT READY to `TUR`. This also
applies to JSON command names and IBM Sense host-command names. Status is displayed as
`GOOD (0x00)` or `CC (0x02)` (other statuses retain their names and codes).
Sense summaries use `Sense: 02/0412 FM=0 EOM=0 ILI=0`; a descriptive Sense Key
name is included only with `--verbose`. Descriptor-format Sense does not invent
fixed-format FM/EOM/ILI values.
Each record has its raw bytes and source location: the absolute container offset
in the dump, the trace ID, and the offset inside the **decompressed** trace
section (including its 20-byte section header).

Important CDB arguments appear after the command name, followed by the raw CDB:

```text
-0-> 519.526141156 06aa
LOCATE16 target=OBJECT id=11 partition=0 IMMED=0 BAM=0
  92020000000000000000000b00000000
<-0- 519.536141156 06aa
GOOD (0x00)
-0-> 519.540000000 06ab
READ6 262144 SILI=0
  080004000000
<-0- 519.550000000 06ab
GOOD (0x00)
```

The example times/tags above are illustrative. `READPOS LONG` selects the
long response form. `WRITE6 FIXED blocks=3` indicates a fixed-block write.
For variable READ, the bare number is the requested maximum byte count,
not the actual record length. For variable WRITE it is the byte count to write.
With FIXED set, transfer length is a block count; the block size is not in that
CDB. SILI is shown for READ only. LOAD/UNLOAD interprets LOAD and HOLD, and shows
IMMED and nonzero RETEN/EOT bits; HOLD requests a seated cartridge with MAM
accessible and the tape unthreaded. LOCATE shows the destination and optional
partition change; SPACE handles signed counts and the ignored count for EOD.
READPOS shows its response form; INQUIRY, MODE/LOG SENSE, READ/WRITE BUFFER,
MODE SELECT and SEND DIAGNOSTIC show their main selection/length fields. Fields
not implemented for an opcode remain available in the raw CDB.

READ/WRITE CDBs, Status, and Sense remain visible, but their transfer payloads are
intentionally omitted from **both text and JSON**, including raw event bytes.
Unassociated or ambiguous transfer payloads are also omitted because their
command type cannot be established. Their time, location, length, and suppression
reason remain available in JSON.

Management data handling:

| Command | Display |
| --- | --- |
| MODE SENSE(6)/(10) | Header, block descriptors, page/subpage IDs, lengths and page hex |
| LOG SENSE | Page/subpage, parameter codes, control bytes, lengths and value hex |
| READ POSITION | Short, long or extended form; partition and position fields |
| INQUIRY | Vendor, product, revision for standard responses; raw VPD bytes |
| Other management commands | Captured hex; direction inferred only for known opcodes |

MODE/LOG pages are structurally decoded; individual vendor-specific page fields
are not interpreted. READ POSITION's unknown-position flags must be checked
before treating its numeric fields as valid positions. Transfer logs are small:
an absent payload means **not retained/associated in this dump**, not a zero-byte
response. Even a present payload may be only a prefix and may include padding;
the reported captured byte count is not necessarily the SCSI transfer length.

### One-line output

`--one-line` prints only command summaries, with no file header, payload or raw
Sense dump. It accepts the normal command filters (`--lun`, `--opcode`,
`--with-data`, `--check-condition`, `--limit`). For example:

```text
519.526141156 LOCATE16 (0, 11)                  -0-> GOOD (0.010000000s)
519.540000000 READPOS LONG                     -0-> GOOD (0.003000000s)
519.550000000 READ6 262144 SILIOFF              -0-> 00/0000 (0.008000000s)
519.560000000 MODE_SENSE10 x0f/x00             -0-> GOOD (0.002000000s)
519.570000000 LOG_SENSE x17/x00                -0-> GOOD (0.002000000s)
524.601598243 SPACE16 F -1                     -0-> GOOD (0.004000000s)
```

Time is command start time. The trailing `(0.010000000s)` is elapsed time from
the CDB record to its matched Status record, in seconds with nine fractional
digits, calculated using integer timestamp differences. It is also shown for
CC and other matched statuses; it is omitted when Status is missing/ambiguous.
This measures the logged command-to-Status interval, not completion of a tape
operation that continues after an IMMED command returns. Clock units remain
inferred from the dump. The times above are illustrative.
The arrow contains the command's decimal LUN
(`-0->`, `-1->`, etc.). LOCATE's pair means `(partition, logical identifier)`;
`cur` means no partition change was requested. Nonzero IMMED/BAM/BT flags
are retained, and non-object destinations keep their explicit names. READ uses
`SILION`/`SILIOFF`; fixed transfers keep `FIXED blocks=N` to distinguish units.
MODE SENSE(6)/(10) and LOG SENSE show only `xPP/xSS` (page/subpage) as two-digit hexadecimal values;
page control and allocation length remain available in normal output and JSON.
MODE SELECT(6)/(10) and SEND DIAGNOSTIC show only the command name, with no arguments.
READ BUFFER shows only its mode (for example, `READ_BUFFER 0x01`).
MAINTENANCE IN service action `0x0c` is named `REPORT_SUPPORTED_OPERATION_CODES`
in normal output and JSON, and `RSOC` in one-line output. Other service actions
keep `MAINTENANCE_IN xNN` in one-line output.
LOAD/UNLOAD uses `LOAD` or `UNLOAD` as the command name. One-line output omits
zero flags and shows `IMMED` only when set; HOLD retains the explicit combined
command and its flags. WRITE FILEMARKS(6) shows the count and optional `IMMED`
(for example, `WRITEFM6 1 IMMED`).
For an object-target LOCATE(16), logical identifier `0xffffffffffffffff` is
shown as `EOD` in one-line output, for example `(1, EOD)`. JSON retains the
original numeric identifier.
READ ATTRIBUTE is shortened to `READ_ATTR`, followed by `(partition, first attribute ID)`
(for example, `READ_ATTR (0, x0800)` or `READ_ATTR (1, x080c)`). For attribute-value
requests, nonzero volume and CACHE are retained as `V1` and `CACHE`.
Service actions other than ATTRIBUTE VALUES show
`SA=xNN` instead of treating the unused first attribute ID as a requested page.
INQUIRY shows only its VPD page when EVPD is set (for example, `INQUIRY 0x80`);
standard INQUIRY has no arguments in one-line output.
SPACE(6)/(16) uses `B count` for blocks, `F count` for filemarks, and `EOD`
without the ignored count. Counts remain signed (for example, `F -1`).
GOOD is shown without its numeric status code in this mode. CC is replaced by
the associated `SK/ASCASCQ` code(s), or shown as `CC` when no Sense was associated.
A missing/ambiguous Status remains `STATUS NOT CAPTURED/AMBIGUOUS`, even if Sense
was captured. Unassociated events are omitted; use normal output or `--sense-only`
to inspect them. `--one-line` cannot be combined with `--verbose`, `--sense-only`,
`--format json` or `--list-snapshots`.

### IBM Sense Extra Fields

For tape LUN 0 fixed-format Sense, the decoder also displays the additional
fields defined in **GA32-0928-09, section 5.2.31.1, Table 134, printed pages
160–166** (PDF pages 190–196). This was checked against the supplied local IBM
reference dated 11 May 2026.

The decoded fields include Information/VALID, FRU, SKSV and field/bit pointer
or reporting FSC, error flag data, speed index, drive service/cleaning/dump flags,
volume-label validity, physical wrap/direction, relative LPOS, active partition,
reporting port, host opcode, cartridge generation, logical block and dataset
numbers, error-history FSCs/flags, LPOS region, ERP summary hex, and cartridge
serial number. FSCs and vendor flag/ERP values are reported as codes, not assigned
an undocumented meaning.

Every field is bounded by **both** captured length and Additional Sense Length.
In particular, an 18-byte Sense inside a 96-byte ring slot never supplies fields
past byte 17. When SKSV is set, bytes 16–17 are a field pointer rather than FSC.
Information is interpreted only with VALID; label and cartridge-type strings
are interpreted only with VOLVALID. For this LTO5 profile, physical wrap uses
byte 29 only: the byte-36 high wrap bit defined for LTO9+ is not used. The IBM
tape layout is not applied to changer Sense or descriptor-format Sense.

## Format evidence and correlation rules

The container consists of big-endian five-word headers (20 bytes). Plain records
have zero in word 0; word 1 is the record type and word 2 is the payload length.
The `EF BE AD DE` / `00FE0000` wrapper holds padded length, compressed length,
and expanded length; its body is a UNIX compress stream containing a complete
plain record. `33 44 55 66` / `00FD0000` is retained as an opaque record.
`001D0000` contains a historical dump; only its outer record boundary is checked,
and the payload is skipped. The outer snapshot ends with record `000B0000`
and `End Of Dump!!!!\0`. Its boundaries, expanded section lengths, and end marker
are checked. JSON marks this as `validation_scope: outer_container_only` and
records `embedded_dumps_skipped`. This is structural validation, **not a firmware
checksum check**. Opaque memory regions are not decoded.

In a decoded `001C0000` trace, offsets relative to the section including its
20-byte header are:

| Offset | Field |
| --- | --- |
| `0x70` | 32-bit trace identifier |
| `0x74` | Latest entry time (two big-endian 32-bit words) |
| `0x7c`, `0x80`, `0x84` | Capacity, entry size, newest entry index |
| `0x88` | Ring flags |
| `0x8c` | Ring data |

Observed SCSI rings:

| Group | CDB (32 bytes) | Status (20 bytes) | Sense (104 bytes) | Variable transfer data |
| --- | --- | --- | --- | --- |
| LUN 0 | `00250000` | `00260000` | `00280000` | `00450000` |
| LUN 1 | `007B0000` | `007C0000` | `007D0000` | `007E0000` |
| Transient | `008D0000` | `008E0000` | `008F0000` | `00900000` |

Fixed CDB/Status records contain time at bytes 0–7 and an eight-byte correlation
key at bytes 8–15 (observed LUN, tag, and nexus fields). CDB starts at byte 16;
Status is byte 16. The matching key and time interval must identify exactly one
Status. Reused tags are bounded by the next CDB with the same key. Missing Status
stays missing; it is never filled with GOOD. Fixed Sense records contain 96
captured Sense bytes following the time.

Variable records contain time, a back-link in four-byte units, record length,
and payload. The newest-entry cursor and back-links define the valid chain.
Traversal stops before an entry overwritten by a newer one. Byte-pattern scans
are not used to invent records in stale ring contents.

Sense and transfer records lack the CDB key. Their association is **inferred**
only when exactly one command in that group could be active at the event time.
Commands without Status remain possible candidates, preventing a missing READ
completion from making its data look like a management response. The JSON
`association` and `completion_missing` fields expose this uncertainty.

Time words are interpreted as drive-relative seconds and nanoseconds, based on
the observed field ranges and command sequence. The clock epoch/units have not
been independently verified against IBM's private dump format. Embedded
snapshots do not contribute to the timeline.

Standard response layouts were checked against the project's `sg_readpos()` and
`sg_get_next_block_to_xfer()` and the
[IBM LTO SCSI Reference](https://www.ibm.com/support/pages/system/files/inline-files/LTO%20SCSI%20Reference%20GA32-0928-08%20%28EXTERNAL%29.pdf).
The public reference documents SCSI commands, not the private dump ring format.

## Verification

```sh
python3 -m unittest discover -s contrib/ibm-dump -v
```

Tests use synthetic containers and rings, covering truncation, compressed size
mismatches, wrapping/overwritten rings, unused sentinels, repeated tags,
ambiguous and missing-status associations, management response truncation, and
READ/WRITE payload suppression. Real drive dumps are not committed.
The `IBM dump reader` GitHub Actions workflow runs these synthetic tests for
changes to this tool; it does not require tape hardware.

Additional real-drive validation used a 100 MiB write, unmount, remount, and
read-back cycle on the same IBM LTO5/H976, both with and without `-o eject`.
Read-back size and SHA-256 matched. Dumps captured after mounting, writing,
remounting (in the eject run), and reading were decoded offline; the tests and
repository contain no tape payload or drive-dump binaries.

For the 2026-10-24 capture from drive `10WT019481`, the outer containers of both
original files passed structural validation. The embedded historical dump in
each file is skipped.
The outer forced dump contains 139 CDBs, 138 matching Status records and 15 Sense
records. Its last CDB is the dump-triggering SEND DIAGNOSTIC; its completion is
not in that snapshot. The outer saved dump contains 128 CDBs and 127 Status
records. These counts characterize these files, not all H976 dumps.

Dump fingerprints:

| Capture | Size | SHA-256 |
| --- | ---: | --- |
| Saved | 2,534,096 | `a6c99857ed7dd6171b010607adad9d1d495c6c6fbf1681d9b4837366e2da9d13` |
| Forced | 2,503,632 | `d42c4f273e1869cd217827354e187d0efb39fc69757af2123bf5a3cde113f2cc` |
