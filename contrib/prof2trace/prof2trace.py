#!/usr/bin/env python3
#
#  OO_Copyright_BEGIN
#
#  Copyright 2026 Aurora LTFS project. All rights reserved.
#
#  Redistribution and use in source and binary forms, with or without
#   modification, are permitted provided that the following conditions
#  are met:
#  1. Redistributions of source code must retain the above copyright
#     notice, this list of conditions and the following disclaimer.
#  2. Redistributions in binary form must reproduce the above copyright
#     notice, this list of conditions and the following disclaimer in the
#  documentation and/or other materials provided with the distribution.
#  3. Neither the name of the copyright holder nor the names of its
#     contributors may be used to endorse or promote products derived from
#     this software without specific prior written permission.
#
#  THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS ``AS IS''
#  AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
#  IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
#  ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
#  LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
#  CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
#  SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
#  INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
#  CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
#  ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
#  POSSIBILITY OF SUCH DAMAGE.
#
#  OO_Copyright_END
#
"""Convert LTFS profiler data (prof_*.dat) to Chrome Trace Event JSON.

The LTFS profiler, enabled through the ``ltfs.vendor.<vendor>.profiler``
xattr, writes packed binary records to the work directory:

  prof_request.dat    - FUSE request layer
  prof_iosched_*.dat  - I/O scheduler layer
  prof_driver_*.dat   - tape driver layer
  prof_changer_*.dat  - changer layer

Each file starts with a 16-byte ``struct timer_info`` header
(``uint64_t type; uint64_t base;``, see src/libltfs/arch/time_internal.h)
identifying the recording platform's clock, followed by packed
``struct profiler_entry`` records (see src/libltfs/ltfstrace.h):

  uint64_t time;     /* timestamp (platform dependent, see timer_info) */
  uint32_t req_num;  /* 0xASSSTTTT: A=status, SSS=source, TTTT=type */
  uint32_t tid;      /* thread ID */

This script pairs ENTER/EXIT records into duration events and emits
Chrome Trace Event Format JSON, viewable with https://ui.perfetto.dev
or chrome://tracing.  It can also dump the raw records as CSV and print
a per-request aggregation summary.
"""

import argparse
import csv
import glob
import json
import os
import struct
import sys

# req_num field layout (src/libltfs/ltfstrace.h)
REQ_STAT_ENTER = 0x0
REQ_STAT_EVENT = 0x1
REQ_STAT_EXIT = 0x8

SOURCE_NAMES = {
    0x000: "fuse",
    0x010: "admin",
    0x111: "iosched",
    0x222: "driver",
    0x333: "changer",
}

# src/cmd/altfs/ltfs_fuse.h REQ_* (+ REQ_SYNC from src/libltfs/periodic_sync.c)
FUSE_REQ_NAMES = {
    0x0000: "mount",
    0x0001: "unmount",
    0x0002: "getattr",
    0x0003: "fgetattr",
    0x0004: "access",
    0x0005: "statfs",
    0x0006: "open",
    0x0007: "release",
    0x0008: "fsync",
    0x0009: "flush",
    0x000a: "utimens",
    0x000b: "chmod",
    0x000c: "chown",
    0x000d: "create",
    0x000e: "truncate",
    0x000f: "ftruncate",
    0x0010: "unlink",
    0x0011: "rename",
    0x0012: "mkdir",
    0x0013: "rmdir",
    0x0014: "opendir",
    0x0015: "readdir",
    0x0016: "releasedir",
    0x0017: "fsyncdir",
    0x0018: "write",
    0x0019: "read",
    0x001a: "setxattr",
    0x001b: "getxattr",
    0x001c: "listxattr",
    0x001d: "removexattr",
    0x001e: "symlink",
    0x001f: "readlink",
    0xfffe: "periodic_sync",
}

# src/libltfs/iosched_ops.h REQ_IOS_*
IOSCHED_REQ_NAMES = {
    0x0000: "open",
    0x0001: "close",
    0x0002: "read",
    0x0003: "write",
    0x0004: "flush",
    0x0005: "truncate",
    0x0006: "get_filesize",
    0x0007: "update_data_placement",
    0x0008: "io_scheduler",
    0x0009: "enqueue_ip",
    0x000a: "dequeue_ip",
    0x000b: "enqueue_dp",
    0x000c: "dequeue_dp",
}

# src/libltfs/tape_ops.h REQ_TC_* (shared by the driver and changer layers)
DRIVER_REQ_NAMES = {
    0x0000: "open",
    0x0001: "reopen",
    0x0002: "close",
    0x0003: "close_raw",
    0x0004: "is_connected",
    0x0005: "inquiry",
    0x0006: "inquiry_page",
    0x0007: "test_unit_ready",
    0x0008: "read",
    0x0009: "write",
    0x000a: "writefm",
    0x000b: "rewind",
    0x000c: "locate",
    0x000d: "space",
    0x000e: "erase",
    0x000f: "load",
    0x0010: "unload",
    0x0011: "readpos",
    0x0012: "setcap",
    0x0013: "format",
    0x0014: "remaining_capacity",
    0x0015: "logsense",
    0x0016: "modesense",
    0x0017: "modeselect",
    0x0018: "reserve_unit",
    0x0019: "release_unit",
    0x001a: "prevent_medium_removal",
    0x001b: "allow_medium_removal",
    0x001c: "read_attribute",
    0x001d: "write_attribute",
    0x001e: "allow_overwrite",
    0x001f: "report_density",
    0x0020: "set_compression",
    0x0021: "set_default",
    0x0022: "get_cartridge_health",
    0x0023: "get_tape_alert",
    0x0024: "clear_tape_alert",
    0x0025: "getxattr",
    0x0026: "setxattr",
    0x0027: "get_parameters",
    0x0028: "get_eod_status",
    0x0029: "get_device_list",
    0x002a: "help_message",
    0x002b: "parse_opts",
    0x002c: "default_device_name",
    0x002d: "set_key",
    0x002e: "get_keyalias",
    0x002f: "takedump_drive",
    0x0030: "is_mountable",
    0x0031: "get_worm_status",
    0x0032: "getslots",
    0x0033: "inventory",
    0x0034: "movemedia",
    0x0035: "get_devmap",
    0x0036: "get_serialnumber",
    0x0037: "set_supported_changers",
}

TYPE_NAMES = {
    0x000: FUSE_REQ_NAMES,
    0x111: IOSCHED_REQ_NAMES,
    0x222: DRIVER_REQ_NAMES,
    0x333: DRIVER_REQ_NAMES,
}

# Changer records (source 0x333) are written into prof_driver_*.dat;
# there is no separate changer profiler file.
PROFILER_FILES = (
    ("prof_request", "request"),
    ("prof_iosched_", "iosched"),
    ("prof_driver_", "driver"),
)

RECORD = struct.Struct("<QII")

# struct timer_info at the head of every profiler file
# (src/libltfs/arch/time_internal.h)
HEADER = struct.Struct("<QQ")
TIMER_TYPE_LINUX = 0
TIMER_TYPE_OSX = 1
TIMER_TYPE_WINDOWS = 2


class Record:
    __slots__ = ("time_ns", "status", "source", "type", "tid")

    def __init__(self, time_ns, req_num, tid):
        self.time_ns = time_ns
        self.status = (req_num >> 28) & 0xF
        self.source = (req_num >> 16) & 0xFFF
        self.type = req_num & 0xFFFF
        self.tid = tid

    @property
    def source_name(self):
        return SOURCE_NAMES.get(self.source, "src_0x%03x" % self.source)

    @property
    def type_name(self):
        names = TYPE_NAMES.get(self.source, {})
        return names.get(self.type, "req_0x%04x" % self.type)

    @property
    def status_name(self):
        return {REQ_STAT_ENTER: "enter",
                REQ_STAT_EVENT: "event",
                REQ_STAT_EXIT: "exit"}.get(self.status,
                                           "stat_0x%x" % self.status)


def decode_time(raw, clock, tick_ns):
    """Convert the on-disk timestamp to nanoseconds since profiler start."""
    if clock == "packed":
        # Linux: (tv_sec << 32) | tv_nsec of a CLOCK_MONOTONIC delta
        return (raw >> 32) * 1000000000 + (raw & 0xFFFFFFFF)
    # macOS: mach_absolute_time() delta; scale with mach_timebase_info ratio
    return int(raw * tick_ns)


def resolve_clock(path, timer_type, timer_base, clock, tick_ns):
    """Pick the timestamp decoding from the timer_info header, unless
    overridden on the command line.  Returns (clock, tick_ns)."""
    if clock == "auto":
        if timer_type == TIMER_TYPE_LINUX:
            clock = "packed"
        elif timer_type == TIMER_TYPE_OSX:
            clock = "ticks"
        elif timer_type == TIMER_TYPE_WINDOWS:
            raise SystemExit("%s: Windows profiler traces are not supported"
                             % path)
        else:
            raise SystemExit("%s: unknown timer type %d in file header "
                             "(not a profiler file?)" % (path, timer_type))
    if clock == "ticks" and tick_ns is None:
        # macOS: base = (denom << 32) | numer of mach_timebase_info
        numer = timer_base & 0xFFFFFFFF
        denom = timer_base >> 32
        if denom:
            tick_ns = numer / denom
        else:
            print("%s: no timebase in file header, assuming 1 ns/tick"
                  % path, file=sys.stderr)
            tick_ns = 1.0
    return clock, tick_ns


def read_records(path, clock, tick_ns):
    records = []
    with open(path, "rb") as f:
        data = f.read()
    if len(data) < HEADER.size:
        print("%s: too short for the timer_info header, skipped" % path,
              file=sys.stderr)
        return records
    timer_type, timer_base = HEADER.unpack_from(data)
    clock, tick_ns = resolve_clock(path, timer_type, timer_base,
                                   clock, tick_ns)
    body = data[HEADER.size:]
    tail = len(body) % RECORD.size
    if tail:
        print("%s: %d trailing bytes ignored (truncated record)"
              % (path, tail), file=sys.stderr)
    for raw_time, req_num, tid in RECORD.iter_unpack(body[:len(body) - tail]):
        records.append(Record(decode_time(raw_time, clock, tick_ns),
                              req_num, tid))
    return records


def find_profiler_files(directory):
    found = []
    for prefix, _ in PROFILER_FILES:
        found.extend(sorted(glob.glob(os.path.join(directory,
                                                   prefix + "*.dat"))))
    return found


def layer_label(path):
    base = os.path.basename(path)
    for prefix, layer in PROFILER_FILES:
        if base.startswith(prefix):
            suffix = base[len(prefix):]
            if suffix.endswith(".dat"):
                suffix = suffix[:-len(".dat")]
            return layer + (" " + suffix if suffix else "")
    return base


def layer_rank(path):
    base = os.path.basename(path)
    for rank, (prefix, _) in enumerate(PROFILER_FILES):
        if base.startswith(prefix):
            return rank
    return len(PROFILER_FILES)


def pair_records(records):
    """Pair ENTER/EXIT records per (tid, source, type), innermost first.

    Returns (slices, instants, unfinished, unmatched_exit) where slices
    is a list of (enter, exit) Record pairs, instants the EVENT records,
    unfinished the ENTER records that never saw an EXIT and
    unmatched_exit the count of dropped EXIT records.
    """
    slices, instants, unfinished = [], [], []
    unmatched_exit = 0
    open_slices = {}  # (tid, source, type) -> [enter Record, ...]
    for rec in records:
        key = (rec.tid, rec.source, rec.type)
        if rec.status == REQ_STAT_ENTER:
            open_slices.setdefault(key, []).append(rec)
        elif rec.status == REQ_STAT_EXIT:
            stack = open_slices.get(key)
            if not stack:
                unmatched_exit += 1
                continue
            slices.append((stack.pop(), rec))
        else:  # EVENT and any unknown status: point-in-time marker
            instants.append(rec)
    for stack in open_slices.values():
        unfinished.extend(stack)
    return slices, instants, unfinished, unmatched_exit


def warn_pairing(unmatched_exit, unfinished):
    if unmatched_exit:
        print("warning: %d EXIT records without a matching ENTER (dropped)"
              % unmatched_exit, file=sys.stderr)
    if unfinished:
        print("warning: %d ENTER records without a matching EXIT"
              % unfinished, file=sys.stderr)


def to_trace_events(per_file_records):
    """Build Chrome Trace Event dicts.

    Each input file becomes one "process" so the layers stack up as
    separate tracks in the viewer.  Timestamps are microseconds (float).
    """
    events = []
    total_unmatched = 0
    total_unfinished = 0

    # Request layer on top, then iosched, then driver.  Perfetto orders
    # process groups by name, so bake the rank into the name; the
    # process_sort_index covers chrome://tracing.
    ordered = sorted(per_file_records,
                     key=lambda pr: (layer_rank(pr[0]), pr[0]))
    for pid, (path, records) in enumerate(ordered, start=1):
        events.append({"ph": "M", "pid": pid, "name": "process_name",
                       "args": {"name": "%d. %s" % (pid, layer_label(path))}})
        events.append({"ph": "M", "pid": pid, "name": "process_sort_index",
                       "args": {"sort_index": pid}})
        slices, instants, unfinished, unmatched = pair_records(records)
        total_unmatched += unmatched
        total_unfinished += len(unfinished)
        for enter, rec in slices:
            events.append({
                "ph": "X", "pid": pid, "tid": rec.tid,
                "name": "%s:%s" % (enter.source_name, enter.type_name),
                "cat": enter.source_name,
                "ts": enter.time_ns / 1000.0,
                "dur": (rec.time_ns - enter.time_ns) / 1000.0,
            })
        for rec in instants:
            events.append({
                "ph": "i", "pid": pid, "tid": rec.tid,
                "name": "%s:%s" % (rec.source_name, rec.type_name),
                "cat": rec.source_name,
                "ts": rec.time_ns / 1000.0,
                "s": "t",
            })
        for enter in unfinished:
            events.append({
                "ph": "B", "pid": pid, "tid": enter.tid,
                "name": "%s:%s (unfinished)"
                        % (enter.source_name, enter.type_name),
                "cat": enter.source_name,
                "ts": enter.time_ns / 1000.0,
            })

    warn_pairing(total_unmatched, total_unfinished)
    events.sort(key=lambda e: e.get("ts", 0))
    return events


def write_csv(per_file_records, out):
    writer = csv.writer(out)
    writer.writerow(["file", "time_ns", "layer", "status", "request", "tid"])
    rows = []
    for path, records in per_file_records:
        base = os.path.basename(path)
        for rec in records:
            rows.append([base, rec.time_ns, rec.source_name,
                         rec.status_name, rec.type_name, rec.tid])
    rows.sort(key=lambda r: r[1])
    writer.writerows(rows)


def print_summary(per_file_records, out):
    stats = {}  # (layer, source_name, type_name) -> [count, total, min, max]
    total_unmatched = 0
    total_unfinished = 0
    for path, records in per_file_records:
        layer = layer_label(path)
        slices, _, unfinished, unmatched = pair_records(records)
        total_unmatched += unmatched
        total_unfinished += len(unfinished)
        for enter, rec in slices:
            dur = rec.time_ns - enter.time_ns
            skey = (layer, rec.source_name, rec.type_name)
            st = stats.setdefault(skey, [0, 0, dur, dur])
            st[0] += 1
            st[1] += dur
            st[2] = min(st[2], dur)
            st[3] = max(st[3], dur)
    warn_pairing(total_unmatched, total_unfinished)

    header = "%-20s %-8s %-24s %8s %12s %12s %12s %12s" % (
        "layer", "source", "request", "count",
        "total(ms)", "avg(us)", "min(us)", "max(us)")
    print(header, file=out)
    print("-" * len(header), file=out)
    for (layer, source, name), (count, total, dmin, dmax) in sorted(
            stats.items(), key=lambda kv: kv[1][1], reverse=True):
        print("%-20s %-8s %-24s %8d %12.3f %12.1f %12.1f %12.1f" % (
            layer, source, name, count, total / 1e6,
            total / count / 1e3, dmin / 1e3, dmax / 1e3), file=out)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Convert LTFS profiler .dat files to "
                    "Chrome Trace Event JSON (for Perfetto UI).")
    parser.add_argument("inputs", nargs="+", metavar="PATH",
                        help="prof_*.dat file(s), or a directory to scan "
                             "(e.g. the LTFS work directory)")
    parser.add_argument("-o", "--output", default="-",
                        help="output file (default: stdout)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--csv", action="store_true",
                      help="dump raw records as CSV instead of trace JSON")
    mode.add_argument("--summary", action="store_true",
                      help="print per-request aggregation instead of "
                           "trace JSON")
    parser.add_argument("--clock", choices=["auto", "packed", "ticks"],
                        default="auto",
                        help="timestamp format: 'packed' for traces from "
                             "Linux ((sec<<32)|nsec), 'ticks' for traces "
                             "from macOS (mach_absolute_time delta); "
                             "default: auto-detect from the file header")
    parser.add_argument("--tick-ns", type=float, default=None,
                        help="nanoseconds per tick for --clock ticks; "
                             "default: mach_timebase_info ratio from the "
                             "file header")
    args = parser.parse_args(argv)

    paths = []
    for p in args.inputs:
        if os.path.isdir(p):
            found = find_profiler_files(p)
            if not found:
                parser.error("no prof_*.dat files found in %s" % p)
            paths.extend(found)
        elif os.path.isfile(p):
            paths.append(p)
        else:
            parser.error("%s: no such file or directory" % p)

    per_file_records = []
    total = 0
    for path in paths:
        records = read_records(path, args.clock, args.tick_ns)
        print("%s: %d records" % (path, len(records)), file=sys.stderr)
        total += len(records)
        per_file_records.append((path, records))
    if not total:
        print("no records found", file=sys.stderr)
        return 1

    if args.output == "-":
        out = sys.stdout
    else:
        # newline="" keeps the csv module in charge of CSV line endings
        out = open(args.output, "w", newline="" if args.csv else None)
    try:
        if args.csv:
            write_csv(per_file_records, out)
        elif args.summary:
            print_summary(per_file_records, out)
        else:
            json.dump({"traceEvents": to_trace_events(per_file_records),
                       "displayTimeUnit": "ms"}, out)
            out.write("\n")
    finally:
        if out is not sys.stdout:
            out.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
