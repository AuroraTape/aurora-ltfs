#!/usr/bin/env python3
#
# Copyright 2026 Aurora LTFS project. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause
#
"""Offline, experimental IBM LTO5 H976 drive-dump SCSI trace reader.

The container and trace layouts were inferred from actual dumps, not an IBM
format specification. See README.md for the supported profile and limitations.
No device access and no third-party Python packages are required.
"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile


MAX_FILE = 64 * 1024 * 1024
MAX_SECTION = 16 * 1024 * 1024
MAX_EXPANDED = 256 * 1024 * 1024
PROFILE = (b"peamc011400 ", b"pf170907f   ")
END = b"End Of Dump!!!!\0"
# IDs are full 32-bit trace identifiers, not SCSI opcodes.
GROUPS = {
    "lun0": (0x00250000, 0x00260000, 0x00280000, 0x00450000),
    "lun1": (0x007B0000, 0x007C0000, 0x007D0000, 0x007E0000),
    "transient": (0x008D0000, 0x008E0000, 0x008F0000, 0x00900000),
}
NAMES = {
    0x00: "TUR", 0x01: "REWIND", 0x03: "REQUEST SENSE",
    0x05: "READ BLOCK LIMITS", 0x07: "INITIALIZE ELEMENT STATUS",
    0x08: "READ(6)", 0x0A: "WRITE(6)", 0x10: "WRITEFM(6)",
    0x11: "SPACE(6)", 0x12: "INQUIRY", 0x15: "MODE SELECT(6)",
    0x16: "RESERVE(6)", 0x17: "RELEASE(6)", 0x19: "ERASE(6)",
    0x1A: "MODE SENSE(6)", 0x1B: "LOAD UNLOAD", 0x1C: "RECEIVE DIAGNOSTIC RESULTS",
    0x1D: "SEND DIAGNOSTIC", 0x1E: "PREVENT ALLOW MEDIUM REMOVAL",
    0x2B: "LOCATE(10)", 0x34: "READPOS", 0x3B: "WRITE BUFFER",
    0x3C: "READ BUFFER", 0x4C: "LOG SELECT", 0x4D: "LOG SENSE",
    0x55: "MODE SELECT(10)", 0x5A: "MODE SENSE(10)",
    0x5E: "PERSISTENT RESERVE IN", 0x5F: "PERSISTENT RESERVE OUT",
    0x80: "WRITEFM(16)", 0x88: "READ(16)", 0x8A: "WRITE(16)",
    0x8C: "READ ATTRIBUTE", 0x8D: "WRITE ATTRIBUTE", 0x91: "SPACE(16)",
    0x92: "LOCATE(16)", 0x93: "ERASE(16)", 0xA0: "REPORT LUNS",
    0xA2: "SECURITY PROTOCOL IN", 0xA3: "MAINTENANCE IN",
    0xA5: "MOVE MEDIUM", 0xB5: "SECURITY PROTOCOL OUT", 0xB8: "READ ELEMENT STATUS",
}
NAMES = {opcode: name.replace(" ", "_").replace("(", "").replace(")", "")
         for opcode, name in NAMES.items()}
STATUS = {0: "GOOD", 2: "CHECK CONDITION", 4: "CONDITION MET", 8: "BUSY",
          0x18: "RESERVATION CONFLICT", 0x28: "TASK SET FULL",
          0x30: "ACA ACTIVE", 0x40: "TASK ABORTED"}
BULK_DATA = {0x08, 0x0A, 0x0F, 0x14, 0x81, 0x88, 0x8A}
DATA_IN = {0x03, 0x05, 0x12, 0x1A, 0x1C, 0x34, 0x3C, 0x4D, 0x5A, 0x5E, 0x8C, 0xA0, 0xA2, 0xA3, 0xB8}
DATA_OUT = {0x15, 0x1D, 0x3B, 0x4C, 0x55, 0x5F, 0x8D, 0xB5}
SENSE_KEYS = ("NO SENSE", "RECOVERED ERROR", "NOT READY", "MEDIUM ERROR",
              "HARDWARE ERROR", "ILLEGAL REQUEST", "UNIT ATTENTION", "DATA PROTECT",
              "BLANK CHECK", "VENDOR SPECIFIC", "COPY ABORTED", "ABORTED COMMAND",
              "RESERVED", "VOLUME OVERFLOW", "MISCOMPARE", "COMPLETED")


class DumpError(ValueError):
    """Malformed input or an unsupported layout."""


def u32(data, offset):
    return struct.unpack_from(">I", data, offset)[0]


def timestamp(data):
    seconds, nanoseconds = struct.unpack_from(">II", data)
    if nanoseconds >= 1_000_000_000:
        raise DumpError("invalid drive timestamp nanosecond field")
    return seconds * 1_000_000_000 + nanoseconds


def time_text(value):
    seconds, nanos = divmod(value, 1_000_000_000)
    return f"{seconds}.{nanos:09d}"


def uncompress(data, expected):
    """Use gzip's UNIX compress decoder, bounding output read into memory."""
    executable = shutil.which("gzip")
    if executable is None:
        raise DumpError("gzip is required to decode UNIX compress (.Z) sections")
    if not data.startswith(b"\x1f\x9d"):
        raise DumpError("compressed section is not a UNIX compress stream")
    # File-backed input prevents a pipe deadlock while output is read with a cap.
    with tempfile.TemporaryFile() as source, tempfile.TemporaryFile() as errors:
        source.write(data)
        source.seek(0)
        with subprocess.Popen([executable, "-dc"], stdin=source, stdout=subprocess.PIPE,
                              stderr=errors) as process:
            try:
                raw = process.stdout.read(expected + 1)
                if len(raw) > expected:
                    raise DumpError("section expands beyond its declared size")
                result = process.wait(timeout=10)
                if result or len(raw) != expected:
                    raise DumpError("invalid compressed section or decompressed size mismatch")
                return raw
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()


def parse_dump(data):
    if not data or len(data) > MAX_FILE:
        raise DumpError("empty dump or dump exceeds 64 MiB input limit")
    snapshots = []
    expanded = 0
    sections = 0
    embedded_skipped = 0

    def visit(blob, path, depth, file_base):
        nonlocal expanded, sections, embedded_skipped
        if depth > 8:
            raise DumpError("embedded dump nesting exceeds limit")
        snap = {"id": len(snapshots), "path": path, "traces": {}, "sections": 0}
        snapshots.append(snap)
        offset = 0
        ended = False
        while offset < len(blob):
            if ended or len(blob) - offset < 20:
                raise DumpError(f"{path}: truncated header or data after end marker at {offset:#x}")
            magic, kind, size, packed, unpacked = struct.unpack_from(">5I", blob, offset)
            if size > len(blob) - offset - 20 or size > MAX_FILE:
                raise DumpError(f"{path}: section exceeds input at {offset:#x}")
            payload = blob[offset + 20:offset + 20 + size]
            source = {"container_offset": file_base + offset, "compressed": magic == 0xEFBEADDE}
            if magic == 0xEFBEADDE:
                if (kind != 0x00FE0000 or not 0 < packed <= size or size != ((packed + 3) & ~3)
                        or not 20 <= unpacked <= MAX_SECTION):
                    raise DumpError(f"{path}: invalid compression header at {offset:#x}")
                expanded += unpacked
                if expanded > MAX_EXPANDED:
                    raise DumpError("expanded dump exceeds 256 MiB limit")
                raw = uncompress(payload[:packed], unpacked)
                inner_magic, kind, inner_size, reserved1, reserved2 = struct.unpack_from(">5I", raw)
                if inner_magic or reserved1 or reserved2 or inner_size != len(raw) - 20:
                    raise DumpError("invalid decompressed section header")
                payload = raw[20:]
            elif magic == 0x33445566:
                if kind != 0x00FD0000 or packed != size or unpacked != size:
                    raise DumpError("unsupported opaque-section header")
            elif magic or packed or unpacked:
                raise DumpError(f"{path}: unsupported section header at {offset:#x}")
            sections += 1
            if sections > 20000:
                raise DumpError("too many sections")
            snap["sections"] += 1
            if offset == 0:
                if kind != 0 or len(payload) != 0xF8:
                    raise DumpError(f"{path}: unsupported dump header")
                profile = (payload[:12], payload[0x40:0x4C])
                snap["profile_supported"] = profile == PROFILE
                snap["build"] = [v.decode("ascii", errors="replace").strip() for v in profile]
                snap["drive_identity"] = payload[0x50:0x70].rstrip(b"\0 ").decode("ascii", errors="replace")
            elif kind == 0x001C0000:
                if len(payload) < 0x78:
                    raise DumpError("short trace header")
                trace_id = u32(payload, 0x5C)
                if trace_id in snap["traces"]:
                    raise DumpError("duplicate trace ID within snapshot")
                snap["traces"][trace_id] = (payload, source)
            elif kind == 0x001D0000:
                embedded_skipped += 1
            elif kind == 0x000B0000:
                if payload != END:
                    raise DumpError("invalid end-of-dump marker")
                ended = True
            offset += 20 + size
        if not ended:
            raise DumpError(f"{path}: end-of-dump marker missing")

    visit(data, "root", 0, 0)
    return snapshots, {"container_complete": True, "validation_scope": "outer_container_only",
                       "embedded_dumps_skipped": embedded_skipped,
                       "sections": sections, "expanded_bytes": expanded}


def read_ring(trace, expected_size):
    payload, source = trace
    capacity, size, cursor = struct.unpack_from(">3I", payload, 0x68)
    flags = int.from_bytes(payload[0x74:0x76], "big")
    data = payload[0x78:]
    if not capacity or size != expected_size or capacity * size != len(data):
        raise DumpError("unsupported SCSI ring dimensions")
    if cursor >= capacity:
        raise DumpError("ring cursor is out of bounds")
    records = []

    def record(raw, position):
        return {"time_ns": timestamp(raw), "raw_hex": raw.hex(),
                "source": {**source, "trace_id": f"0x{u32(payload, 0x5C):08x}",
                           "decoded_offset": 20 + 0x78 + position}}

    if expected_size != 4:
        if flags & 0xC000 != 0x8000:
            raise DumpError("unsupported fixed ring flags")
        for slot in range(capacity):
            index = (cursor + 1 + slot) % capacity
            raw = data[index * size:(index + 1) * size]
            # Unused rings initialize the last slot with an all-ones timestamp.
            if any(raw) and not (raw[:8] == b"\xff" * 8 and not any(raw[8:])):
                records.append(record(raw, index * size))
    else:
        if flags & 0xC000 != 0xC000:
            raise DumpError("unsupported variable ring flags")
        position = cursor * 4
        used = set()
        # The cursor points to the newest entry. Back-links are word offsets.
        # Old entries may be partly overwritten; never scan for plausible bytes.
        while True:
            if position in used:
                break
            header_positions = [(position + i) % len(data) for i in range(16)]
            if any(i in used for i in header_positions):
                break
            header = bytes(data[i] for i in header_positions)
            if not any(header):
                break
            previous, length = struct.unpack_from(">II", header, 8)
            if length < 16 or length > len(data) or length % 4:
                raise DumpError("invalid variable ring entry length")
            positions = [(position + i) % len(data) for i in range(length)]
            if any(i in used for i in positions):
                break
            raw = bytes(data[i] for i in positions)
            entry = record(raw, position)
            if records and entry["time_ns"] > records[-1]["time_ns"]:
                raise DumpError("variable ring back-link moves forward in time")
            records.append(entry)
            used.update(positions)
            if previous == 0xFFFFFFFF:
                break
            if previous >= capacity:
                raise DumpError("variable ring back-link out of bounds")
            position = previous * 4
        records.reverse()
    if records and max(r["time_ns"] for r in records) != timestamp(payload[0x60:0x68]):
        raise DumpError("ring timestamp does not match newest retained entry")
    return records


def decode_cdb(raw):
    opcode = raw[0]
    length = (6, 10, 10, None, 16, 12, None, None)[opcode >> 5]
    cdb = raw if length is None else raw[:length]
    info = {"opcode": opcode, "name": NAMES.get(opcode, f"OPCODE_0x{opcode:02x}"),
            "hex": cdb.hex(), "record_bytes_hex": raw.hex(), "length_known": length is not None}
    if opcode == 0x12:
        info.update(evpd=bool(cdb[1] & 1), page=cdb[2], allocation_length=int.from_bytes(cdb[3:5], "big"))
    elif opcode in (0x08, 0x0A):
        info.update(fixed=bool(cdb[1] & 1), transfer_length=int.from_bytes(cdb[2:5], "big"))
        info["transfer_unit"] = "blocks" if info["fixed"] else "bytes"
        if opcode == 0x08:
            info["sili"] = bool(cdb[1] & 2)
    elif opcode == 0x1B:
        info.update(load=bool(cdb[4] & 1), reten=bool(cdb[4] & 2), eot=bool(cdb[4] & 4),
                    hold=bool(cdb[4] & 8), immed=bool(cdb[1] & 1))
        info["action"] = "HOLD" if info["hold"] else "LOAD" if info["load"] else "UNLOAD"
    elif opcode == 0x01:
        info["immed"] = bool(cdb[1] & 1)
    elif opcode == 0x10:
        info.update(count=int.from_bytes(cdb[2:5], "big"), immed=bool(cdb[1] & 1))
    elif opcode in (0x11, 0x91):
        info.update(space_code=cdb[1] & (7 if opcode == 0x11 else 15),
                    count=int.from_bytes(cdb[2:5] if opcode == 0x11 else cdb[4:12], "big", signed=True))
    elif opcode in (0x2B, 0x92):
        info.update(change_partition=bool(cdb[1] & 2), immed=bool(cdb[1] & 1),
                    partition=cdb[8] if opcode == 0x2B else cdb[3],
                    logical_identifier=int.from_bytes(cdb[3:7] if opcode == 0x2B else cdb[4:12], "big"))
        if opcode == 0x92:
            info.update(destination_type=(cdb[1] >> 3) & 7, bam=bool(cdb[2] & 1))
        else:
            info["bt"] = bool(cdb[1] & 4)
    elif opcode == 0x34:
        info["service_action"] = cdb[1] & 0x1F
    elif opcode in (0x3B, 0x3C):
        info.update(mode=cdb[1] & 0x1F, buffer_id=cdb[2],
                    buffer_offset=int.from_bytes(cdb[3:6], "big"),
                    transfer_length=int.from_bytes(cdb[6:9], "big"))
    elif opcode in (0x1A, 0x5A, 0x4D):
        info.update(page=cdb[2] & 0x3F, page_control=cdb[2] >> 6, subpage=cdb[3])
        info["allocation_length"] = cdb[4] if opcode == 0x1A else int.from_bytes(cdb[7:9], "big")
    elif opcode in (0x15, 0x55):
        info.update(pf=bool(cdb[1] & 0x10), sp=bool(cdb[1] & 1),
                    parameter_length=cdb[4] if opcode == 0x15 else int.from_bytes(cdb[7:9], "big"))
    elif opcode == 0x1D:
        info.update(parameter_length=int.from_bytes(cdb[3:5], "big"), pf=bool(cdb[1] & 0x10))
    elif opcode == 0xA3:
        info.update(service_action=cdb[1] & 0x1F)
    elif opcode == 0x8C:
        info.update(service_action=cdb[1] & 0x1F, logical_volume=cdb[5], partition=cdb[7],
                    first_attribute_identifier=int.from_bytes(cdb[8:10], "big"),
                    allocation_length=int.from_bytes(cdb[10:14], "big"), cache=bool(cdb[14] & 1))
    info["name"] = command_name(info)
    return info


def command_name(info, compact=False):
    if compact and info["opcode"] == 0x8C:
        return "READ_ATTR"
    if info["opcode"] == 0xA3 and info["service_action"] == 0x0C:
        return "RSOC" if compact else "REPORT_SUPPORTED_OPERATION_CODES"
    if info["opcode"] == 0x1B and info["action"] in ("LOAD", "UNLOAD"):
        return info["action"]
    return info["name"]


def cdb_arguments(info):
    opcode = info["opcode"]
    if opcode in (0x08, 0x0A):
        text = f"FIXED blocks={info['transfer_length']}" if info["fixed"] else str(info["transfer_length"])
        return text + (f" SILI={int(info['sili'])}" if opcode == 0x08 else "")
    if opcode == 0x1B:
        text = f"IMMED={int(info['immed'])}"
        if info["hold"]:
            text = f"action=HOLD {text} LOAD={int(info['load'])} HOLD=1"
        if info["reten"]:
            text += " RETEN=1"
        if info["eot"]:
            text += " EOT=1(unsupported)"
        return text
    if opcode == 0x01:
        return f"IMMED={int(info['immed'])}"
    if opcode == 0x10:
        return f"count={info['count']} IMMED={int(info['immed'])}"
    if opcode in (0x11, 0x91):
        kind = {0: "BLOCKS", 1: "FILEMARKS", 3: "EOD"}.get(info["space_code"], f"0x{info['space_code']:x}")
        return f"type={kind}" + (" count=ignored" if info["space_code"] == 3 else f" count={info['count']}")
    if opcode in (0x2B, 0x92):
        destination = info.get("destination_type", 0)
        kind = {0: "OBJECT", 1: "FILE", 3: "EOD", 7: "PAST_READ_ERROR"}.get(destination, f"0x{destination:x}")
        identifier = "ignored" if destination in (3, 7) else str(info["logical_identifier"])
        partition = str(info["partition"]) if info["change_partition"] else "current"
        text = f"target={kind} id={identifier} partition={partition} IMMED={int(info['immed'])}"
        if opcode == 0x92:
            text += f" BAM={int(info['bam'])}"
        elif info["bt"]:
            text += " BT=1(unsupported)"
        return text
    if opcode == 0x34:
        form = {0: "SHORT", 6: "LONG", 8: "EXTENDED"}.get(info["service_action"], f"0x{info['service_action']:02x}")
        return form
    if opcode in (0x1A, 0x5A, 0x4D):
        return (f"page=0x{info['page']:02x} subpage=0x{info['subpage']:02x} "
                f"PC={info['page_control']} alloc={info['allocation_length']}")
    if opcode == 0x12:
        kind = f"VPD page=0x{info['page']:02x}" if info["evpd"] else "STANDARD"
        return f"{kind} alloc={info['allocation_length']}"
    if opcode in (0x3B, 0x3C):
        return (f"mode=0x{info['mode']:02x} buffer=0x{info['buffer_id']:02x} "
                f"offset={info['buffer_offset']} bytes={info['transfer_length']}")
    if opcode in (0x15, 0x55, 0x1D):
        text = f"PF={int(info['pf'])} parameter_bytes={info['parameter_length']}"
        return text + (f" SP={int(info['sp'])}" if "sp" in info else "")
    if opcode == 0xA3:
        return "" if info["service_action"] == 0x0C else f"service_action=0x{info['service_action']:02x}"
    if opcode == 0x8C:
        return (f"service_action=0x{info['service_action']:02x} "
                f"attribute=0x{info['first_attribute_identifier']:04x} partition={info['partition']} "
                f"volume={info['logical_volume']} alloc={info['allocation_length']} CACHE={int(info['cache'])}")
    return ""


def decode_ibm_sense_extra(data):
    """LTO5 fixed-format Sense, GA32-0928-09 Table 134, bytes within declared length only."""
    extra = {}
    if len(data) >= 18:
        extra["sksv"] = bool(data[15] & 0x80)
        if extra["sksv"]:
            extra["field_pointer"] = {"location": "cdb" if data[15] & 0x40 else "parameter_data",
                                      "byte": int.from_bytes(data[16:18], "big"),
                                      "bit": data[15] & 7 if data[15] & 8 else None}
        else:
            extra["reporting_fsc"] = data[16:18].hex()
    if len(data) >= 20:
        extra["reporting_error_flags_hex"] = data[18:20].hex()
    if len(data) >= 21:
        extra["speed_index"] = data[20]
    if len(data) >= 22:
        extra["drive_flags"] = {"service_required": bool(data[21] & 0x10),
                               "cleaning_requested": bool(data[21] & 8),
                               "dump_present": bool(data[21] & 2),
                               "volume_label_valid": bool(data[21] & 1)}
    if len(data) >= 29:
        extra["volume_label"] = data[22:29].decode("ascii", errors="replace") if data[21] & 1 else None
    if len(data) >= 30:
        # This decoder targets LTO5. Byte 36 bit 3 is only a wrap bit for LTO9+.
        extra["physical_wrap"] = data[29]
        extra["physical_direction"] = "towards_beginning" if data[29] & 1 else "away_from_beginning"
    if len(data) >= 34:
        extra["relative_lpos"] = u32(data, 30)
    if len(data) >= 36:
        extra["rs422_information"] = data[35]
    if len(data) >= 37:
        extra["active_partition"] = data[36] & 7
    if len(data) >= 40:
        extra["reporting_port_identifier_hex"] = data[37:40].hex()
    if len(data) >= 41:
        extra["tape_directory_valid"] = bool(data[40] & 0x80)
        extra["tape_partitions_exist"] = bool(data[40] & 0x40)
        extra["relative_target_port"] = data[40] & 7
    if len(data) >= 42:
        extra["host_command"] = {"opcode": data[41], "name": NAMES.get(data[41], "unknown")}
    if len(data) >= 43:
        generation = data[42] >> 4
        extra["cartridge_generation_code"] = generation
        extra["cartridge_generation"] = generation + 1 if 1 <= generation <= 9 else None
        extra["media_type_vendor_code"] = data[42] & 15
    if len(data) >= 45:
        extra["volume_label_cartridge_type"] = data[43:45].decode("ascii", errors="replace") if data[21] & 1 else None
    if len(data) >= 49:
        extra["logical_block_number"] = u32(data, 45)
    if len(data) >= 53:
        extra["dataset_number"] = u32(data, 49)
    history = []
    for offset, name in ((53, "first"), (57, "second"), (61, "next_to_last"), (65, "last")):
        if len(data) >= offset + 4:
            history.append({"position": name, "fsc": data[offset:offset + 2].hex(),
                            "flags_hex": data[offset + 2:offset + 4].hex()})
    if history:
        extra["error_history"] = history
    if len(data) >= 70:
        extra["lpos_region"] = data[69]
    if len(data) >= 86:
        extra["erp_summary_hex"] = data[70:86].hex()
    if len(data) >= 96:
        extra["cartridge_serial_number"] = data[86:96].decode("ascii", errors="replace").strip()
    return extra


def decode_sense(raw, ibm_lto=False):
    code = raw[0] & 0x7F if raw else None
    result = {"hex": raw.hex(), "response_code": code}
    if code not in (0x70, 0x71, 0x72, 0x73) or len(raw) < 8:
        return result
    result.update(declared_length=8 + raw[7], truncated=8 + raw[7] > len(raw))
    data = raw[:result["declared_length"]]
    if code in (0x70, 0x71):
        result.update(sense_key=data[2] & 15, filemark=bool(data[2] & 0x80),
                      eom=bool(data[2] & 0x40), ili=bool(data[2] & 0x20), information_valid=bool(data[0] & 0x80))
        if result["information_valid"]:
            result["information_unsigned"] = int.from_bytes(data[3:7], "big")
            result["information_signed"] = int.from_bytes(data[3:7], "big", signed=True)
        if len(data) >= 12:
            result["command_specific_information_hex"] = data[8:12].hex()
        if len(data) >= 14:
            result.update(asc=data[12], ascq=data[13])
        if len(data) >= 15:
            result["fru_code"] = data[14]
        if ibm_lto:
            result["ibm_extra"] = decode_ibm_sense_extra(data)
    else:
        result.update(sense_key=data[1] & 15, asc=data[2], ascq=data[3])
    result["sense_key_name"] = SENSE_KEYS[result["sense_key"]]
    return result


def decode_response(cdb, data):
    """Interpret standard management responses, preserving partial captures."""
    opcode = cdb[0]
    result = {}
    if opcode == 0x34:
        action = cdb[1] & 0x1F
        result.update(service_action=action)
        if action == 6 and len(data) >= 32:
            result.update(form="long", flags_hex=f"{data[0]:02x}", partition=u32(data, 4),
                          logical_object=int.from_bytes(data[8:16], "big"),
                          logical_file=int.from_bytes(data[16:24], "big"),
                          obsolete_hex=data[24:32].hex(),
                          bop=bool(data[0] & 0x80), eop=bool(data[0] & 0x40),
                          logical_object_unknown=bool(data[0] & 0x04),
                          mark_position_unknown=bool(data[0] & 0x08))
        elif action == 0 and len(data) >= 20:
            result.update(form="short", flags_hex=f"{data[0]:02x}", partition=data[1],
                          first_block=u32(data, 4), last_block=u32(data, 8),
                          block_position_unknown=bool(data[0] & 0x04))
        elif action == 8 and len(data) >= 32:
            result.update(form="extended", flags_hex=f"{data[0]:02x}", partition=data[1],
                          first_object=int.from_bytes(data[8:16], "big"),
                          last_object=int.from_bytes(data[16:24], "big"))
        else:
            result["note"] = "short capture or unsupported READ POSITION service action"
    elif opcode in (0x1A, 0x5A):
        header = 4 if opcode == 0x1A else 8
        if len(data) < header:
            return {"truncated": True, "note": "partial mode parameter header"}
        total = data[0] + 1 if header == 4 else int.from_bytes(data[:2], "big") + 2
        descriptors = data[3] if header == 4 else int.from_bytes(data[6:8], "big")
        result.update(declared_bytes=total, truncated=len(data) < total,
                      medium_type=data[1 if header == 4 else 2],
                      device_specific=data[2 if header == 4 else 3],
                      block_descriptors_hex=data[header:min(header + descriptors, total)].hex(), pages=[])
        if header + descriptors > min(total, len(data)):
            result["note"] = "partial or inconsistent block descriptor area"
            return result
        position = header + descriptors
        end = min(total, len(data))
        while position < end:
            page = data[position:end]
            page_header = 4 if page[0] & 0x40 else 2
            if len(page) < page_header:
                result["partial_page_header_hex"] = page.hex()
                break
            length = int.from_bytes(page[2:4], "big") if page_header == 4 else page[1]
            result["pages"].append({"page": page[0] & 0x3F,
                                    "subpage": page[1] if page_header == 4 else 0,
                                    "parameters_savable": bool(page[0] & 0x80),
                                    "declared_bytes": length + page_header,
                                    "truncated": len(page) < length + page_header,
                                    "hex": page[:length + page_header].hex()})
            position += page_header + length
    elif opcode == 0x4D:
        if len(data) < 4:
            return {"truncated": True, "note": "partial log page header"}
        total = int.from_bytes(data[2:4], "big") + 4
        result.update(page=data[0] & 0x3F, subpage=data[1], declared_bytes=total,
                      truncated=len(data) < total)
        end = min(total, len(data))
        if result["page"] == 0:
            result["supported_pages_hex"] = data[4:end].hex()
            return result
        result["parameters"] = []
        position = 4
        while position < end:
            parameter = data[position:end]
            if len(parameter) < 4:
                result["partial_parameter_header_hex"] = parameter.hex()
                break
            length = parameter[3]
            result["parameters"].append({"code": int.from_bytes(parameter[:2], "big"),
                                         "control": parameter[2], "declared_bytes": length,
                                         "truncated": len(parameter) < 4 + length,
                                         "value_hex": parameter[4:4 + length].hex()})
            position += 4 + length
    elif opcode == 0x12 and not cdb[1] & 1 and len(data) >= 36:
        result.update(peripheral_type=data[0] & 0x1F,
                      vendor=data[8:16].decode("ascii", errors="replace").strip(),
                      product=data[16:32].decode("ascii", errors="replace").strip(),
                      revision=data[32:36].decode("ascii", errors="replace").strip())
    return result


def decode_snapshot(snap):
    if not snap["profile_supported"]:
        return {"id": snap["id"], "path": snap["path"], "build": snap["build"],
                "drive_identity": snap["drive_identity"], "decode_status": "unsupported_profile",
                "available_rings": [], "commands": [], "events": []}
    commands = []
    events = []
    available = []
    for group, ids in GROUPS.items():
        decoded = []
        for kind, trace_id, size in zip(("cdb", "status", "sense", "transfer"), ids, (32, 20, 104, 4)):
            trace = snap["traces"].get(trace_id)
            ring = read_ring(trace, size) if trace else []
            if trace:
                available.append({"group": group, "kind": kind, "trace_id": f"0x{trace_id:08x}",
                                  "records": len(ring)})
            for r in ring:
                r.update(group=group, kind=kind)
                raw = bytes.fromhex(r["raw_hex"])
                if kind in ("cdb", "status"):
                    r.update(key=raw[8:16].hex(), lun=int.from_bytes(raw[8:10], "big"),
                             tag=int.from_bytes(raw[10:12], "big"), nexus_hex=raw[12:16].hex())
                if kind == "cdb":
                    r.update(cdb=decode_cdb(raw[16:32]), status=None, sense=[], transfer=[])
                elif kind == "status":
                    r.update(value=raw[16], name=STATUS.get(raw[16], f"STATUS 0x{raw[16]:02x}"))
                elif kind == "sense":
                    r["sense"] = decode_sense(raw[8:], ibm_lto=group == "lun0")
                else:
                    r["data_hex"] = raw[16:].hex()
                    r["captured_bytes"] = len(raw) - 16
                    r["direction"] = "unknown"
            decoded.append(ring)
        cdbs, statuses, senses, transfers = decoded
        cdbs.sort(key=lambda r: r["time_ns"])
        for i, command in enumerate(cdbs):
            next_time = next((c["time_ns"] for c in cdbs[i + 1:] if c["key"] == command["key"]), None)
            candidates = [s for s in statuses if s["key"] == command["key"]
                          and s["time_ns"] >= command["time_ns"]
                          and (next_time is None or s["time_ns"] < next_time)]
            if len(candidates) == 1:
                status = candidates[0]
                command["status"] = {**status, "association": "key_and_time_interval"}
                status["matched"] = True
            command["status_candidates"] = len(candidates)
            command["next_same_key_time_ns"] = next_time
        for event in senses + transfers:
            # These records lack tags. Only infer an association if exactly one
            # command in this ring group was active. Always disclose inference.
            candidates = [c for c in cdbs if c["time_ns"] <= event["time_ns"]
                          and (c["status"] is None or event["time_ns"] <= c["status"]["time_ns"])
                          and (c["next_same_key_time_ns"] is None
                               or event["time_ns"] < c["next_same_key_time_ns"])]
            sense_compatible = (len(candidates) == 1 and
                                (event["kind"] != "sense" or candidates[0]["status"] is None
                                 or candidates[0]["status"]["value"] == 2))
            if len(candidates) == 1 and sense_compatible:
                event["association"] = "inferred_unique_command_interval"
                command = candidates[0]
                event["command_key"] = command["key"]
                event["completion_missing"] = command["status"] is None
                if event["kind"] == "sense" and command["lun"] == 0:
                    event["sense"] = decode_sense(bytes.fromhex(event["sense"]["hex"]), ibm_lto=True)
                if event["kind"] == "transfer":
                    opcode = command["cdb"]["opcode"]
                    if opcode in BULK_DATA:
                        event.pop("raw_hex")
                        event.pop("data_hex")
                        event["suppressed_reason"] = "READ/WRITE payload intentionally omitted"
                        continue
                    if opcode in DATA_IN:
                        event["direction"] = "device_to_host_inferred_from_cdb"
                        event["decoded"] = decode_response(bytes.fromhex(command["cdb"]["hex"]),
                                                           bytes.fromhex(event["data_hex"]))
                    elif opcode in DATA_OUT:
                        event["direction"] = "host_to_device_inferred_from_cdb"
                command[event["kind"]].append(event)
            else:
                event["association"] = "ambiguous" if len(candidates) > 1 else "unmatched"
                if event["kind"] == "transfer":
                    event.pop("raw_hex")
                    event.pop("data_hex")
                    event["suppressed_reason"] = "unassociated transfer payload omitted (may be READ/WRITE)"
        commands.extend(cdbs)
        events.extend(statuses + senses + transfers)
    commands.sort(key=lambda r: (r["time_ns"], r["group"], r["key"]))
    return {"id": snap["id"], "path": snap["path"], "build": snap["build"],
            "decode_status": "experimental_profile",
            "drive_identity": snap["drive_identity"], "available_rings": available,
            "commands": commands, "events": sorted(events, key=lambda r: r["time_ns"])}


def sense_code(sense):
    key = f"{sense['sense_key']:02x}" if "sense_key" in sense else "??"
    asc = f"{sense['asc']:02x}" if "asc" in sense else "??"
    ascq = f"{sense['ascq']:02x}" if "ascq" in sense else "??"
    return f"{key}/{asc}{ascq}"


def print_sense(event, verbose=False, standalone=False):
    sense = event["sense"]
    raw = bytes.fromhex(sense["hex"])
    summary = sense_code(sense)
    if "sense_key" in sense:
        if "filemark" in sense:
            summary += (f" FM={int(sense['filemark'])} EOM={int(sense['eom'])}"
                        f" ILI={int(sense['ili'])}")
    print(f"  Sense: {summary}")
    if verbose or standalone:
        print(f"    @{time_text(event['time_ns'])} group={event['group']} "
              f"[{event.get('association', 'unmatched')}]")
    if verbose and "sense_key_name" in sense:
        print(f"    Key: {sense['sense_key_name']}")
    if verbose:
        code = f"0x{sense['response_code']:02x}" if sense["response_code"] is not None else "unknown"
        print(f"    Response={code}; captured={len(raw)} bytes; "
              f"declared={sense.get('declared_length', 'unknown')}; "
              f"truncated={sense.get('truncated', 'unknown')}")
        if "information_valid" in sense:
            print(f"    Information: valid={sense['information_valid']}, "
                  f"unsigned={sense.get('information_unsigned')}, signed={sense.get('information_signed')}")
        if "fru_code" in sense:
            print(f"    FRU=0x{sense['fru_code']:02x}")
    if sense.get("ibm_extra"):
        print("  IBM Extra Fields (GA32-0928-09 Table 134; LTO5 layout):")
        for key, value in sense["ibm_extra"].items():
            print(f"    {key}: {json.dumps(value)}")
    print("  RAW (entire captured Sense buffer, including any padding):")
    for offset in range(0, len(raw), 16):
        print(f"    {offset:04x}: {raw[offset:offset + 16].hex(' ')}")
    if verbose:
        print(f"    Source: {json.dumps(event['source'])}")


def print_transfer(transfer, verbose=False):
    label = "DATA (direction unknown)" if transfer["direction"] == "unknown" else "DATA"
    print(f"  {label}: {transfer['data_hex']}")
    if transfer.get("decoded"):
        print(f"  Decoded: {json.dumps(transfer['decoded'])}")
    if verbose:
        print(f"    Transfer: @{time_text(transfer['time_ns'])}, {transfer['captured_bytes']} captured bytes, "
              f"{transfer['direction']} [association inferred; may include padding/truncation]")
        print(f"    Source: {json.dumps(transfer['source'])}")


def one_line_arguments(info):
    opcode = info["opcode"]
    if opcode == 0x8C:
        if info["service_action"] != 0:
            return f"SA=x{info['service_action']:02x}"
        text = f"({info['partition']}, x{info['first_attribute_identifier']:04x})"
        if info["logical_volume"]:
            text += f" V{info['logical_volume']}"
        if info["cache"]:
            text += " CACHE"
        return text
    if opcode == 0xA3:
        return "" if info["service_action"] == 0x0C else f"x{info['service_action']:02x}"
    if opcode == 0x1B and not info["hold"]:
        return " ".join(label for flag, label in (("immed", "IMMED"), ("reten", "RETEN"),
                                                  ("eot", "EOT(unsupported)")) if info[flag])
    if opcode == 0x10:
        return str(info["count"]) + (" IMMED" if info["immed"] else "")
    if opcode == 0x12:
        return f"0x{info['page']:02x}" if info["evpd"] else ""
    if opcode in (0x15, 0x55, 0x1D):
        return ""
    if opcode == 0x3C:
        return f"0x{info['mode']:02x}"
    if opcode in (0x1A, 0x5A, 0x4D):
        return f"x{info['page']:02x}/x{info['subpage']:02x}"
    if opcode in (0x11, 0x91):
        kind = {0: "B", 1: "F", 3: "EOD"}.get(info["space_code"])
        if kind is not None:
            return kind if kind == "EOD" else f"{kind} {info['count']}"
    if opcode in (0x08, 0x0A):
        text = f"FIXED blocks={info['transfer_length']}" if info["fixed"] else str(info["transfer_length"])
        return text + (" SILION" if info["sili"] else " SILIOFF") if opcode == 0x08 else text
    if opcode in (0x2B, 0x92) and info.get("destination_type", 0) == 0:
        partition = str(info["partition"]) if info["change_partition"] else "cur"
        identifier = ("EOD" if opcode == 0x92 and info["logical_identifier"] == 0xFFFFFFFFFFFFFFFF
                      else str(info["logical_identifier"]))
        text = f"({partition}, {identifier})"
        for flag in ("immed", "bam", "bt"):
            if info.get(flag):
                text += f" {flag.upper()}=1"
        return text
    return cdb_arguments(info)


def one_line_report(report):
    for snap in report["snapshots"]:
        if snap["decode_status"] == "unsupported_profile":
            print(f"Unsupported firmware profile {snap['build']}; SCSI decoding skipped")
            continue
        for command in snap["commands"]:
            arguments = one_line_arguments(command["cdb"])
            label = command_name(command["cdb"], compact=True) + (f" {arguments}" if arguments else "")
            status = command["status"]
            if status is None:
                state = "STATUS NOT CAPTURED/AMBIGUOUS"
            elif status["value"] == 2:
                state = ", ".join(sense_code(s["sense"]) for s in command["sense"]) or "CC"
            else:
                state = status["name"]
            elapsed = f" ({time_text(status['time_ns'] - command['time_ns'])}s)" if status is not None else ""
            print(f"{time_text(command['time_ns'])} {label:<32} -{command['lun']}-> {state}{elapsed}")


def status_text(status):
    if status is None:
        return "STATUS NOT CAPTURED/AMBIGUOUS"
    name = "CC" if status["value"] == 2 else status["name"]
    return f"{name} (0x{status['value']:02x})"


def print_command_response(command, verbose=False):
    status = command["status"]
    if status:
        print(f"<-{status['lun']}- {time_text(status['time_ns'])} {status['tag']:04x}")
    print(status_text(status))
    for transfer in command["transfer"]:
        if transfer["direction"] != "host_to_device_inferred_from_cdb":
            print_transfer(transfer, verbose)
    for sense in command["sense"]:
        print_sense(sense, verbose)
    if verbose and status:
        print(f"  Status RAW: {status['raw_hex']}; Source: {json.dumps(status['source'])}")


def print_unassociated(event, verbose=False):
    tag = f" {event['tag']:04x}" if "tag" in event else ""
    print(f"-?-> {time_text(event['time_ns'])} {event['group']}{tag} "
          f"{event['kind']} [{event.get('association', 'unmatched')}]")
    if event["kind"] == "sense":
        print_sense(event, verbose)
    elif event["kind"] == "status":
        print(status_text(event))
        if verbose:
            print(f"  RAW: {event['raw_hex']}; Source: {json.dumps(event['source'])}")
    else:
        print(f"  Transfer: {event['captured_bytes']} captured bytes; "
              f"{event.get('suppressed_reason', 'payload unavailable')}")
        if verbose:
            print(f"  Source: {json.dumps(event['source'])}")


def text_report(report, verbose=False, sense_only=False, command_filtered=False):
    print(f"File: {report['file']} ({report['size']} bytes)")
    print(f"SHA256: {report['sha256']}")
    print("Profile: experimental IBM LTO5 H976; outer container/section lengths and end marker verified")
    if report["validation"]["embedded_dumps_skipped"]:
        print("Embedded dumps: skipped")
    print("Times: drive-relative seconds.nanoseconds (inferred clock units; not wall clock)")
    for snap in report["snapshots"]:
        print(f"\nSnapshot {snap['id']}: {snap['path']} / {snap['drive_identity']}")
        if snap["decode_status"] == "unsupported_profile":
            print(f"Unsupported firmware profile {snap['build']}; SCSI decoding skipped")
            continue
        if sense_only:
            senses = [e for e in snap["events"] if e["kind"] == "sense"]
            print(f"Sense records: {len(senses)} (including unassociated/ambiguous records)")
            for event in senses:
                print_sense(event, verbose, standalone=True)
            continue
        print(f"Commands: {snap['total_commands']}; displayed: {len(snap['commands'])}")
        print("Transfer logs are sparse; READ/WRITE payloads omitted. Missing data does not mean an empty response.")
        print("Sense/DATA association and DATA direction are inferred; captured bytes may include padding/truncation.")
        timeline = []
        earliest = {}
        for index, command in enumerate(snap["commands"]):
            group, start = command["group"], command["time_ns"]
            earliest[group] = min(earliest.get(group, start), start)
            timeline.append((start, 0, index, "send", command))
            if command["status"]:
                timeline.append((command["status"]["time_ns"], 2, index, "response", command))
        # Untagged events cannot be attributed to a command filter. The complete
        # event list remains available in JSON and via --sense-only for Sense.
        if not command_filtered:
            for index, event in enumerate(snap["events"]):
                unmatched = (not event.get("matched") if event["kind"] == "status" else
                             event.get("association") != "inferred_unique_command_interval")
                cutoff = earliest.get(event["group"])
                if unmatched and (cutoff is None or event["time_ns"] >= cutoff):
                    timeline.append((event["time_ns"], 1, index, "unassociated", event))
        for _, _, _, kind, c in sorted(timeline, key=lambda row: row[:3]):
            if kind == "unassociated":
                print_unassociated(c, verbose)
                continue
            if kind == "response":
                print_command_response(c, verbose)
                continue
            arguments = cdb_arguments(c["cdb"])
            command = command_name(c["cdb"]) + (f" {arguments}" if arguments else "")
            print(f"-{c['lun']}-> {time_text(c['time_ns'])} {c['tag']:04x}")
            print(command)
            print(f"  {c['cdb']['hex']}")
            if verbose:
                print(f"  Group: {c['group']}; Source: {json.dumps(c['source'])}")
            for transfer in c["transfer"]:
                if transfer["direction"] == "host_to_device_inferred_from_cdb":
                    print_transfer(transfer, verbose)
            if c["status"] is None:
                print_command_response(c, verbose)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dump", type=Path)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--snapshot", default="0", choices=("0", "all"),
                        help="compatibility option; only outer snapshot 0 is processed, embedded dumps are skipped")
    parser.add_argument("--list-snapshots", action="store_true")
    parser.add_argument("--lun", type=lambda s: int(s, 0))
    parser.add_argument("--opcode", action="append", type=lambda s: int(s, 0), help="opcode filter; repeatable")
    parser.add_argument("--with-data", action="store_true", help="only commands with captured management transfer data")
    parser.add_argument("--check-condition", action="store_true")
    parser.add_argument("--sense-only", action="store_true",
                        help="show every Sense record, including records without a matched command")
    parser.add_argument("--one-line", action="store_true",
                        help="one line per command: start time, compact arguments, Status or Sense code")
    parser.add_argument("--limit", type=int, help="maximum number of displayed commands per snapshot")
    parser.add_argument("--verbose", action="store_true", help="include source locations, association details and raw Status")
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 0:
        parser.error("--limit must be nonnegative")
    if args.one_line and (args.sense_only or args.verbose or args.format != "text" or args.list_snapshots):
        parser.error("--one-line cannot be combined with --sense-only, --verbose, --format json or --list-snapshots")
    if args.sense_only and (args.lun is not None or args.opcode is not None or args.with_data
                           or args.check_condition or args.limit is not None):
        parser.error("--sense-only cannot be combined with command filters (--lun/--opcode/--with-data/--check-condition/--limit)")
    try:
        with args.dump.open("rb") as stream:
            data = stream.read(MAX_FILE + 1)
        snapshots, validation = parse_dump(data)
        if args.list_snapshots:
            for s in snapshots:
                print(f"{s['id']}: {s['path']}, {s['drive_identity']}, {len(s['traces'])} trace sections, "
                      f"{s['build']}, profile_supported={s['profile_supported']}")
            return 0
        if args.snapshot != "all" and args.snapshot not in {str(s["id"]) for s in snapshots}:
            raise DumpError("unknown snapshot; use --list-snapshots")
        if args.snapshot != "all" and not snapshots[int(args.snapshot)]["profile_supported"]:
            raise DumpError("selected snapshot has an unsupported firmware profile; no SCSI decoding attempted")
        report = {"schema_version": 1, "file": str(args.dump), "size": len(data),
                  "sha256": hashlib.sha256(data).hexdigest(), "validation": validation,
                  "profile": "experimental-lto5-h976", "timestamp_units": "inferred seconds/nanoseconds",
                  "limitations": ["Trace layouts inferred from two dumps of one drive/firmware.",
                                  "Transfer logs are sparse; READ/WRITE and unassociated payloads are omitted.",
                                  "Sense/transfer association is inferred, not tag-based.",
                                  "Transfer bytes may be padded or incomplete; direction is inferred from CDB.",
                                  "Ring buffers retain only part of the command history.",
                                  "Structural verification is not a firmware checksum verification."],
                  "snapshots": []}
        for s in snapshots:
            if args.snapshot != "all" and args.snapshot != str(s["id"]):
                continue
            decoded = decode_snapshot(s)
            decoded["total_commands"] = len(decoded["commands"])
            decoded["commands"] = [c for c in decoded["commands"]
                                   if (args.lun is None or c["lun"] == args.lun)
                                   and (args.opcode is None or c["cdb"]["opcode"] in args.opcode)
                                   and (not args.with_data or c["transfer"])
                                   and (not args.check_condition or c["status"] and c["status"]["value"] == 2)]
            if args.limit is not None:
                decoded["commands"] = decoded["commands"][:args.limit]
            if args.sense_only:
                decoded["commands"] = []
                decoded["events"] = [e for e in decoded["events"] if e["kind"] == "sense"]
            report["snapshots"].append(decoded)
        if args.format == "json":
            print(json.dumps(report, indent=2))
        elif args.one_line:
            one_line_report(report)
        else:
            command_filtered = (args.lun is not None or args.opcode is not None or args.with_data
                                or args.check_condition or args.limit is not None)
            text_report(report, args.verbose, args.sense_only, command_filtered)
        return 0
    except (OSError, DumpError, subprocess.TimeoutExpired) as error:
        print(f"ibm_dump: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
