# prof2trace

Convert LTFS profiler data (`prof_*.dat`) into Chrome Trace Event JSON so it
can be explored on a timeline with [Perfetto UI](https://ui.perfetto.dev)
(or the legacy `chrome://tracing`). It can also dump the raw records as CSV
and print a per-request aggregation summary.

## Background

When profiling is enabled through the `ltfs.vendor.<vendor>.profiler` xattr,
LTFS writes packed binary records to the work directory
(see `src/libltfs/ltfstrace.h`):

| File | Layer |
|:-----|:------|
| `prof_request.dat` | FUSE request layer |
| `prof_iosched_*.dat` | I/O scheduler layer |
| `prof_driver_*.dat` | Tape driver layer (changer records are mixed in here) |

Each file starts with a 16-byte `struct timer_info` header
(`uint64_t type; uint64_t base;`, see `src/libltfs/arch/time_internal.h`)
that identifies the recording platform's clock, followed by little-endian
packed `struct profiler_entry` records:

```c
struct profiler_entry {
    uint64_t time;     /* timestamp since profiler start (platform dependent) */
    uint32_t req_num;  /* 0xASSSTTTT: A=status, SSS=source, TTTT=request type */
    uint32_t tid;      /* thread ID */
};
```

`prof2trace.py` decodes `req_num`, pairs ENTER/EXIT records per thread into
duration slices, and maps EVENT records to instant markers. Each input file
becomes its own "process" track in the viewer, so the request → iosched →
driver interaction can be read top to bottom on a shared time axis.

## Usage

```bash
# Convert everything in the work directory and open trace.json in Perfetto UI
./prof2trace.py /var/ltfs/work_dir -o trace.json

# Individual files work too
./prof2trace.py prof_request.dat prof_driver_0123456789.dat -o trace.json

# Quick aggregation (count / total / avg / min / max per request type)
./prof2trace.py /var/ltfs/work_dir --summary

# Raw record dump
./prof2trace.py prof_request.dat --csv -o records.csv
```

Then load `trace.json` at <https://ui.perfetto.dev> ("Open trace file").
Perfetto's query engine can be used for further aggregation, e.g.:

```sql
SELECT name, COUNT(*) AS cnt, SUM(dur) / 1e6 AS total_ms
FROM slice GROUP BY name ORDER BY total_ms DESC;
```

## Timestamps

The on-disk timestamp format depends on the platform that recorded the
trace and is auto-detected from the `timer_info` header:

- **Linux** (`timer type 0`): a `CLOCK_MONOTONIC` delta packed as
  `(tv_sec << 32) | tv_nsec`.
- **macOS** (`timer type 1`): a `mach_absolute_time()` delta in ticks;
  the `mach_timebase_info` ratio stored in the header is applied
  automatically.
- **Windows** (`timer type 2`): not supported.

`--clock packed|ticks` and `--tick-ns` override the auto-detection if a
file has a damaged or missing header.

Timestamps are relative to profiler start, not wall-clock time.

## Notes

- Requires Python 3 (standard library only).
- Request-type name tables are maintained by hand from
  `src/cmd/altfs/ltfs_fuse.h` (FUSE), `src/libltfs/iosched_ops.h` (iosched)
  and `src/libltfs/tape_ops.h` (driver/changer). Unknown codes are shown as
  `req_0x....` instead of failing, so the tool stays usable if the tables
  lag behind.
- EXIT records without a matching ENTER (e.g. profiling switched on
  mid-request) are dropped with a warning; ENTER records without EXIT are
  kept as unfinished slices.
