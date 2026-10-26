# Copyright 2026 Aurora LTFS project. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause
#
"""Synthetic fixtures only: no drive dumps or tape contents in the repository."""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest

import ibm_dump as m


def section(kind, payload):
    return struct.pack(">5I", 0, kind, len(payload), 0, 0) + payload


def dump_header(profile=m.PROFILE):
    data = bytearray(0xF8)
    data[:12], data[0x40:0x4C] = profile
    return section(0, data)


def container(*sections):
    return dump_header() + b"".join(sections) + section(0xB0000, m.END)


def tick(seconds):
    return struct.pack(">II", seconds, 0)


def trace(tid, size, buffer, cursor, newest):
    payload = bytearray(120)
    struct.pack_into(">I", payload, 0x5C, tid)
    payload[0x60:0x68] = tick(newest)
    struct.pack_into(">IIIH", payload, 0x68, len(buffer) // size, size, cursor,
                     0xC002 if size == 4 else 0x8002)
    return bytes(payload) + buffer, {"container_offset": 100, "compressed": True}


def fixed(tid, size, records):
    # Reserve an unused marker slot exactly as seen in the captured drive.
    marker = b"\xff" * 8 + bytes(size - 8)
    return trace(tid, size, b"".join(records) + bytes(size) + marker,
                 max(0, len(records) - 1), int.from_bytes(records[-1][:4], "big") if records else 0)


def cdb(seconds, tag=1, opcode=0x12):
    return tick(seconds) + struct.pack(">HHI", 0, tag, 0x01000000) + bytes([opcode]) + bytes(15)


def status(seconds, tag=1, value=0):
    return tick(seconds) + struct.pack(">HHI", 0, tag, 0x01000000) + bytes([value, 0, 0, 0])


def variable(seconds, payload, previous=0xFFFFFFFF):
    payload += bytes((-len(payload)) % 4)
    return tick(seconds) + struct.pack(">II", previous, 16 + len(payload)) + payload


def snapshot(traces):
    return {"id": 0, "path": "root", "profile_supported": True, "build": ["test"],
            "drive_identity": "test", "traces": traces}


def z_literals(data):
    """Small valid .Z stream using only 9-bit literal codes (no width switch)."""
    assert len(data) < 250
    bits = sum(byte << (9 * i) for i, byte in enumerate(data))
    return b"\x1f\x9d\x90" + bits.to_bytes((len(data) * 9 + 7) // 8, "little")


class ContainerTests(unittest.TestCase):
    def test_embedded_dump_is_skipped_without_parsing_its_contents(self):
        snapshots, result = m.parse_dump(container(section(0x1D0000, b"unparsed historical dump")))
        self.assertEqual([s["id"] for s in snapshots], [0])
        self.assertTrue(result["container_complete"])
        self.assertEqual(result["validation_scope"], "outer_container_only")
        self.assertEqual(result["embedded_dumps_skipped"], 1)

    def test_truncated_and_trailing_data_rejected(self):
        data = container()
        for broken in (data[:-1], data[:-36], data + b"x", data[:10]):
            with self.subTest(length=len(broken)), self.assertRaises(m.DumpError):
                m.parse_dump(broken)

    def test_declared_length_cannot_run_past_file(self):
        with self.assertRaises(m.DumpError):
            m.parse_dump(dump_header() + struct.pack(">5I", 0, 1, 0xFFFFFF, 0, 0))

    def test_compressed_section_and_wrong_expansion_size(self):
        raw = section(0x10000, b"abc\0")
        packed = z_literals(raw)
        padded = packed + bytes((-len(packed)) % 4)
        good = struct.pack(">5I", 0xEFBEADDE, 0xFE0000, len(padded), len(packed), len(raw)) + padded
        self.assertEqual(m.parse_dump(container(good))[1]["sections"], 3)
        bad = struct.pack(">5I", 0xEFBEADDE, 0xFE0000, len(padded), len(packed), len(raw) - 1) + padded
        with self.assertRaises(m.DumpError):
            m.parse_dump(container(bad))

    def test_unsupported_profile_is_never_decoded(self):
        data = dump_header((b"unknown     ", b"unknown     ")) + section(0xB0000, m.END)
        s = m.parse_dump(data)[0][0]
        self.assertEqual(m.decode_snapshot(s)["decode_status"], "unsupported_profile")


class RingTests(unittest.TestCase):
    def test_unused_sentinel_and_cursor(self):
        records = m.read_ring(fixed(0x250000, 32, [cdb(1), cdb(2)]), 32)
        self.assertEqual([r["time_ns"] for r in records], [10**9, 2 * 10**9])

    def test_fixed_ring_wrap(self):
        buffer = cdb(4) + cdb(5) + cdb(3)
        records = m.read_ring(trace(0x250000, 32, buffer, 1, 5), 32)
        self.assertEqual([r["time_ns"] // 10**9 for r in records], [3, 4, 5])

    def test_variable_ring_stops_at_overwritten_header(self):
        buffer = bytearray(variable(1, b"AAAA") + bytes(12))
        newest = variable(2, b"BBBBBBBB", previous=0)
        for i, byte in enumerate(newest):
            buffer[(20 + i) % len(buffer)] = byte
        records = m.read_ring(trace(0x450000, 4, bytes(buffer), 5, 2), 4)
        self.assertEqual(len(records), 1)
        self.assertEqual(bytes.fromhex(records[0]["raw_hex"])[16:], b"BBBBBBBB")

    def test_bad_variable_length_and_cursor_rejected(self):
        malformed = tick(1) + struct.pack(">II", 0xFFFFFFFF, 0)
        with self.assertRaises(m.DumpError):
            m.read_ring(trace(0x450000, 4, malformed, 0, 1), 4)
        with self.assertRaises(m.DumpError):
            m.read_ring(trace(0x250000, 32, cdb(1), 1, 1), 32)

    def test_reused_command_tag_pairs_by_time_interval(self):
        result = m.decode_snapshot(snapshot({
            0x250000: fixed(0x250000, 32, [cdb(1), cdb(3)]),
            0x260000: fixed(0x260000, 20, [status(2, value=2), status(4)]),
        }))
        self.assertEqual([c["status"]["value"] for c in result["commands"]], [2, 0])

    def test_ambiguous_payload_is_not_assigned(self):
        transfer = variable(3, b"DATA")
        result = m.decode_snapshot(snapshot({
            0x250000: fixed(0x250000, 32, [cdb(1, 1), cdb(2, 2)]),
            0x260000: fixed(0x260000, 20, [status(4, 1), status(5, 2)]),
            0x450000: trace(0x450000, 4, transfer, 0, 3),
        }))
        self.assertFalse(any(c["transfer"] for c in result["commands"]))
        event = next(e for e in result["events"] if e["kind"] == "transfer")
        self.assertEqual(event["association"], "ambiguous")
        self.assertNotIn("data_hex", event)

    def test_read_payload_is_omitted_but_status_kept(self):
        transfer = variable(2, b"PRIVATE-DATA")
        result = m.decode_snapshot(snapshot({
            0x250000: fixed(0x250000, 32, [cdb(1, opcode=8)]),
            0x260000: fixed(0x260000, 20, [status(3)]),
            0x450000: trace(0x450000, 4, transfer, 0, 2),
        }))
        self.assertEqual(result["commands"][0]["status"]["value"], 0)
        self.assertFalse(result["commands"][0]["transfer"])
        self.assertNotIn(b"PRIVATE-DATA".hex(), str(result))

    def test_missing_read_status_prevents_management_payload_misattribution(self):
        transfer = variable(3, b"PRIVATE-DATA")
        result = m.decode_snapshot(snapshot({
            0x250000: fixed(0x250000, 32, [cdb(1, 1, 0x5A), cdb(2, 2, 8)]),
            0x260000: fixed(0x260000, 20, [status(4, 1)]),
            0x450000: trace(0x450000, 4, transfer, 0, 3),
        }))
        self.assertFalse(any(c["transfer"] for c in result["commands"]))
        self.assertNotIn(b"PRIVATE-DATA".hex(), str(result))


class ResponseTests(unittest.TestCase):
    def test_command_arguments_preserve_units_and_control_bits(self):
        cases = [
            ("1b0000000100", "IMMED=0"),
            ("1b0100000000", "IMMED=1"),
            ("1b0000000900", "action=HOLD IMMED=0 LOAD=1 HOLD=1"),
            ("080004000000", "262144 SILI=0"),
            ("080204000000", "262144 SILI=1"),
            ("080100000300", "FIXED blocks=3 SILI=0"),
            ("0a0004000000", "262144"),
            ("0a0100000300", "FIXED blocks=3"),
            ("1101fffffe00", "type=FILEMARKS count=-2"),
            ("1103ffffff00", "type=EOD count=ignored"),
            ("100000000000", "count=0 IMMED=0"),
            ("92020001000000000000002a00000000", "target=OBJECT id=42 partition=1 IMMED=0 BAM=0"),
            ("92180001000000000000002a00000000", "target=EOD id=ignored partition=current IMMED=0 BAM=0"),
            ("34060000000000000000", "LONG"),
            ("5a003f0000000000ff00", "page=0x3f subpage=0x00 PC=0 alloc=255"),
            ("4d007100000000ffff00", "page=0x31 subpage=0x00 PC=1 alloc=65535"),
        ]
        for raw_hex, expected in cases:
            with self.subTest(cdb=raw_hex):
                raw = bytes.fromhex(raw_hex)
                decoded = m.decode_cdb(raw + bytes(16 - len(raw)))
                self.assertEqual(m.cdb_arguments(decoded), expected)
                self.assertNotIn(" ", decoded["name"])
        self.assertTrue(all(not any(char in name for char in " ()") for name in m.NAMES.values()))
    def test_inquiry_16bit_allocation_length(self):
        result = m.decode_cdb(bytes.fromhex("120000123400") + bytes(10))
        self.assertEqual(result["allocation_length"], 0x1234)

    def test_read_position_long(self):
        data = bytes(4) + struct.pack(">IQQQ", 1, 123456789012, 7, 0)
        result = m.decode_response(bytes.fromhex("34060000000000000000"), data)
        self.assertEqual((result["partition"], result["logical_object"], result["logical_file"]),
                         (1, 123456789012, 7))

    def test_mode_sense_pages_and_partial_subpage(self):
        data = bytes.fromhex("00100000000000001002abcd50010004aabb")
        result = m.decode_response(bytes.fromhex("5a003f0000000000ff00"), data)
        self.assertEqual(result["pages"][0]["page"], 0x10)
        self.assertEqual(result["pages"][1]["subpage"], 1)
        self.assertTrue(result["pages"][1]["truncated"])

    def test_logsense_parameters_and_partial_value(self):
        data = bytes.fromhex("3100000c0001000201020002000403")
        result = m.decode_response(bytes.fromhex("4d007100000000ffff00"), data)
        self.assertEqual(result["page"], 0x31)
        self.assertEqual(result["parameters"][0]["value_hex"], "0102")
        self.assertTrue(result["parameters"][1]["truncated"])

    def test_fixed_sense_filemark_and_ili_are_distinct(self):
        data = bytes.fromhex("f000a000000001580000000000003000") + bytes(80)
        result = m.decode_sense(data)
        self.assertTrue(result["filemark"])
        self.assertTrue(result["ili"])
        self.assertFalse(result["eom"])

    def test_ibm_extra_fields_and_validity(self):
        data = bytearray(96)
        data[0], data[2], data[7] = 0xF0, 0x20, 88
        data[3:7] = bytes.fromhex("fffffffe")
        data[16:20] = bytes.fromhex("14130001")
        data[20:22] = bytes([3, 0x1B])
        data[22:29] = b"TAPE001"
        data[29] = 5
        data[30:34] = bytes.fromhex("12345678")
        data[36] = 0x09  # LTO5: bit 3 must not extend physical wrap.
        data[37:40] = bytes.fromhex("000026")
        data[40:45] = bytes([0xC1, 8, 0x40]) + b"L5"
        data[45:49] = bytes.fromhex("00123456")
        data[49:53] = bytes.fromhex("00001234")
        data[53:57] = bytes.fromhex("43218001")
        data[86:96] = b"SERIAL1234"
        result = m.decode_sense(data, ibm_lto=True)
        extra = result["ibm_extra"]
        self.assertEqual(result["information_signed"], -2)
        self.assertEqual(extra["reporting_fsc"], "1413")
        self.assertEqual(extra["logical_block_number"], 0x123456)
        self.assertEqual(extra["relative_lpos"], 0x12345678)
        self.assertEqual(extra["physical_wrap"], 5)
        self.assertEqual(extra["active_partition"], 1)
        self.assertEqual(extra["volume_label"], "TAPE001")
        self.assertEqual(extra["volume_label_cartridge_type"], "L5")
        self.assertEqual(extra["cartridge_serial_number"], "SERIAL1234")
        self.assertEqual(extra["error_history"][0]["fsc"], "4321")
        data[0], data[21] = 0x70, 0
        invalid = m.decode_sense(data, ibm_lto=True)
        self.assertNotIn("information_signed", invalid)
        self.assertIsNone(invalid["ibm_extra"]["volume_label"])
        self.assertIsNone(invalid["ibm_extra"]["volume_label_cartridge_type"])

    def test_short_declared_sense_does_not_decode_stale_extra_bytes(self):
        data = bytearray(b"\xff" * 96)
        data[0], data[2], data[7], data[15] = 0x70, 0x20, 10, 0
        result = m.decode_sense(data, ibm_lto=True)
        self.assertEqual(result["declared_length"], 18)
        self.assertEqual(set(result["ibm_extra"]), {"sksv", "reporting_fsc"})
        self.assertFalse(result["truncated"])

    def test_sksv_pointer_is_not_reporting_fsc(self):
        data = bytearray(18)
        data[0], data[2], data[7], data[15] = 0x70, 5, 10, 0xCB
        data[16:18] = bytes.fromhex("0123")
        extra = m.decode_sense(data, ibm_lto=True)["ibm_extra"]
        self.assertEqual(extra["field_pointer"], {"location": "cdb", "byte": 0x123, "bit": 3})
        self.assertNotIn("reporting_fsc", extra)

    def test_partial_capture_and_descriptor_sense(self):
        data = bytearray(49)
        data[0], data[7] = 0x70, 88
        result = m.decode_sense(data, ibm_lto=True)
        self.assertTrue(result["truncated"])
        self.assertIn("logical_block_number", result["ibm_extra"])
        self.assertNotIn("dataset_number", result["ibm_extra"])
        descriptor = m.decode_sense(bytes.fromhex("7205240000000000"), ibm_lto=True)
        self.assertEqual(descriptor["asc"], 0x24)
        self.assertNotIn("ibm_extra", descriptor)
        self.assertNotIn("filemark", descriptor)
        for short in (b"", b"\x70", bytes.fromhex("7000060000000000")):
            self.assertNotIn("asc", m.decode_sense(short, ibm_lto=True))


class SenseDisplayTests(unittest.TestCase):
    def test_unassociated_events_are_interleaved_and_old_events_hidden_per_group(self):
        sense = bytes.fromhex("700000000000000a00000000000100000000") + bytes(78)
        transfer = variable(16, b"PRIVATE-DATA")
        traces = [
            fixed(0x250000, 32, [cdb(10, 1), cdb(11, 2)]),
            fixed(0x260000, 20, [status(7, 3), status(18, 4), status(20, 1), status(21, 2)]),
            fixed(0x280000, 104, [tick(t) + sense for t in (5, 15, 25)]),
            trace(0x450000, 4, transfer, 0, 16),
            # A different group's older history must not extend lun0's cutoff.
            fixed(0x8D0000, 32, [cdb(1)]),
            fixed(0x8E0000, 20, [status(2)]),
        ]
        data = container(*(section(0x1C0000, t[0]) for t in traces))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.dmp"
            path.write_bytes(data)

            def render(*options):
                output = io.StringIO()
                with redirect_stdout(output):
                    self.assertEqual(m.main([str(path), *options]), 0)
                return output.getvalue()

            text = render()
            headers = [line.split()[:2] for line in text.splitlines()
                       if line.startswith(("-0->", "<-0-", "-?->"))]
            self.assertEqual(headers, [[arrow, f"{t}.000000000"] for arrow, t in (
                ("-0->", 1), ("<-0-", 2), ("-0->", 10), ("-0->", 11),
                ("-?->", 15), ("-?->", 16), ("-?->", 18),
                ("<-0-", 20), ("<-0-", 21), ("-?->", 25))])
            self.assertIn("-?-> 15.000000000 lun0 sense [ambiguous]", text)
            self.assertIn("-?-> 18.000000000 lun0 0004 status [unmatched]\nGOOD (0x00)", text)
            self.assertNotIn("Unassociated events:", text)
            self.assertNotIn(b"PRIVATE-DATA".hex(), text)
            self.assertNotIn("-?->", render("--opcode", "0x12"))
            self.assertEqual(render("--sense-only").count("  Sense:"), 3)
            events = json.loads(render("--format", "json"))["snapshots"][0]["events"]
            self.assertTrue(any(e["time_ns"] == 5 * 10**9 for e in events))
            self.assertTrue(any(e["time_ns"] == 7 * 10**9 for e in events))

    def test_one_line_status_sense_and_missing_completion(self):
        sense = bytes.fromhex("700000000000000a00000000000000000000") + bytes(78)
        for value, include_sense, expected in ((0, False, "GOOD"), (2, True, "00/0000"),
                                              (2, False, "CC"), (8, False, "BUSY"),
                                              (None, True, "STATUS NOT CAPTURED/AMBIGUOUS")):
            with self.subTest(value=value, include_sense=include_sense):
                record = cdb(1, opcode=8)[:16] + bytes.fromhex("080004000000") + bytes(10)
                traces = [fixed(0x250000, 32, [record])]
                if value is not None:
                    traces.append(fixed(0x260000, 20, [status(3, value=value)]))
                if include_sense:
                    traces.append(fixed(0x280000, 104, [tick(2) + sense]))
                data = container(*(section(0x1C0000, t[0]) for t in traces))
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "test.dmp"
                    path.write_bytes(data)
                    output = io.StringIO()
                    with redirect_stdout(output):
                        self.assertEqual(m.main([str(path), "--one-line"]), 0)
                self.assertEqual(output.getvalue().splitlines(),
                                 [f"1.000000000 {'READ6 262144 SILIOFF':<32} -0-> {expected}"
                                  + (" (2.000000000s)" if value is not None else "")])

    def test_one_line_arrow_and_elapsed_use_command_lun_and_exact_event_times(self):
        commands = []
        cases = ((0, 0, "0.000000000"), (1, 1234567, "0.001234567"),
                 (12, 2000000005, "2.000000005"))
        for lun, duration, _ in cases:
            commands.append({"time_ns": 10**9, "lun": lun, "group": "transient",
                             "cdb": m.decode_cdb(bytes(16)), "sense": [],
                             "status": {"value": 0, "name": "GOOD", "time_ns": 10**9 + duration}})
        output = io.StringIO()
        with redirect_stdout(output):
            m.one_line_report({"snapshots": [{"decode_status": "experimental_profile",
                                              "commands": commands}]})
        self.assertEqual(output.getvalue().splitlines(),
                         [f"1.000000000 {'TUR':<32} -{lun}-> GOOD ({elapsed}s)"
                          for lun, _, elapsed in cases])

    def test_compact_arguments_preserve_partition_fixed_mode_and_controls(self):
        for raw_hex, expected in (
                ("92020000000000000000000b00000000", "(0, 11)"),
                ("92000100000000000000000b00000000", "(cur, 11) BAM=1"),
                ("92020001ffffffffffffffff00000000", "(1, EOD)"),
                ("92020001fffffffffffffffe00000000", "(1, 18446744073709551614)"),
                ("92180000000000000000000000000000", "target=EOD id=ignored partition=current IMMED=0 BAM=0"),
                ("080300000300", "FIXED blocks=3 SILION"),
                ("1a004f000000", "x0f/x00"),
                ("5a008f0000000000ff00", "x0f/x00"),
                ("4d005700000000ffff00", "x17/x00"),
                ("4d005701000000ffff00", "x17/x01"),
                ("151100001000", ""),
                ("55110000000000001000", ""),
                ("3c010200001000002000", "0x01"),
                ("1d1000001000", ""),
                ("12018000ff00", "0x80"),
                ("12010000ff00", "0x00"),
                ("12000000ff00", ""),
                ("a30c000000000000ffff0000", ""),
                ("a30d000000000000ffff0000", "x0d"),
                ("8c000000000000000800000000110000", "(0, x0800)"),
                ("8c00000000000001080c0000004f0000", "(1, x080c)"),
                ("8c010000000000000800000000110000", "SA=x01"),
                ("1b0000000100", ""),
                ("1b0100000000", "IMMED"),
                ("100000000000", "0"),
                ("100100000100", "1 IMMED"),
                ("91010000ffffffffffffffff00000000", "F -1"),
                ("1101ffffff00", "F -1"),
                ("110000000300", "B 3"),
                ("1103ffffff00", "EOD"),
                ("34060000000000000000", "LONG")):
            with self.subTest(cdb=raw_hex):
                raw = bytes.fromhex(raw_hex)
                self.assertEqual(m.one_line_arguments(m.decode_cdb(raw + bytes(16 - len(raw)))), expected)

        for raw_hex, full, compact in (
                ("a30c000000000000ffff0000", "REPORT_SUPPORTED_OPERATION_CODES", "RSOC"),
                ("a30d000000000000ffff0000", "MAINTENANCE_IN", "MAINTENANCE_IN"),
                ("8c000000000000000800000000110000", "READ_ATTRIBUTE", "READ_ATTR"),
                ("100100000100", "WRITEFM6", "WRITEFM6"),
                ("34060000000000000000", "READPOS", "READPOS"),
                ("80000000000000000000000000000000", "WRITEFM16", "WRITEFM16"),
                ("1b0000000100", "LOAD", "LOAD"),
                ("1b0000000000", "UNLOAD", "UNLOAD"),
                ("1b0000000900", "LOAD_UNLOAD", "LOAD_UNLOAD")):
            with self.subTest(command_name=raw_hex):
                raw = bytes.fromhex(raw_hex)
                info = m.decode_cdb(raw + bytes(16 - len(raw)))
                self.assertEqual(info["name"], full)
                self.assertEqual(m.command_name(info, compact=True), compact)

    def test_exchange_headers_use_event_times_and_data_direction(self):
        for opcode in (0x12, 0x15, 0x08):
            for complete in (True, False):
                with self.subTest(opcode=opcode, complete=complete):
                    transfer = variable(2, b"DATA")
                    traces = {
                        0x250000: fixed(0x250000, 32, [cdb(1, tag=0x6AA, opcode=opcode)]),
                        0x450000: trace(0x450000, 4, transfer, 0, 2),
                    }
                    if complete:
                        traces[0x260000] = fixed(0x260000, 20, [status(3, tag=0x6AA)])
                    data = container(*(section(0x1C0000, t[0]) for t in traces.values()))
                    with tempfile.TemporaryDirectory() as directory:
                        path = Path(directory) / "test.dmp"
                        path.write_bytes(data)
                        output = io.StringIO()
                        with redirect_stdout(output):
                            self.assertEqual(m.main([str(path)]), 0)
                    text = output.getvalue()
                    self.assertIn("-0-> 1.000000000 06aa\n", text)
                    self.assertIn("\n  " + bytes([opcode]).hex() + "00" * 5 + "\n", text)
                    state = "GOOD (0x00)" if complete else "STATUS NOT CAPTURED/AMBIGUOUS"
                    self.assertIn(state, text)
                    if complete:
                        self.assertIn("<-0- 3.000000000 06aa\nGOOD (0x00)\n", text)
                    else:
                        self.assertNotIn("<-", text)
                    if opcode == 0x08:
                        self.assertNotIn("DATA:", text)
                        self.assertNotIn(b"DATA".hex(), text)
                    elif opcode == 0x15:
                        self.assertLess(text.index("\n  DATA: 44415441\n"), text.index(state))
                    else:
                        self.assertGreater(text.index("\n  DATA: 44415441\n"), text.index(state))

    def test_default_and_sense_only_show_raw_and_unassociated_sense(self):
        sense = bytes.fromhex("700006000000005800000000290000001022") + bytes(78)
        command_trace = fixed(0x250000, 32, [cdb(1)])
        status_trace = fixed(0x260000, 20, [status(3, value=2)])
        sense_trace = fixed(0x280000, 104, [tick(2) + sense, tick(4) + sense])
        data = container(*(section(0x1C0000, t[0]) for t in (command_trace, status_trace, sense_trace)))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.dmp"
            path.write_bytes(data)
            for options in ([], ["--sense-only"]):
                output = io.StringIO()
                with redirect_stdout(output):
                    self.assertEqual(m.main([str(path)] + options), 0)
                text = output.getvalue()
                self.assertEqual(text.count("Sense: 06/2900 FM=0 EOM=0 ILI=0"), 2)
                self.assertEqual(text.count("0000: 70 00 06"), 2)
                self.assertIn("[unmatched]", text)
                self.assertIn('\n    reporting_fsc: "1022"\n', text)
                self.assertIn('\n  IBM Extra Fields ', text)
                self.assertIn('\n  RAW (entire captured Sense buffer, including any padding):\n    0000:', text)
                self.assertNotIn("Transfer: not recorded/associated in this dump", text)
                if not options:
                    self.assertIn("CC (0x02)", text)
                    self.assertIn("INQUIRY STANDARD alloc=0", text)
                    self.assertNotIn("LUN=", text)
                    self.assertIn("<-0- 3.000000000 0001\nCC (0x02)\n  Sense:", text)
                    self.assertNotIn("Response=", text)
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(m.main([str(path), "--sense-only", "--format", "json"]), 0)
            report = json.loads(output.getvalue())["snapshots"][0]
            self.assertFalse(report["commands"])
            self.assertEqual([e["kind"] for e in report["events"]], ["sense", "sense"])

    def test_changer_sense_does_not_assume_tape_extra_layout(self):
        sense = bytes.fromhex("700006000000005800000000290000001022") + bytes(78)
        result = m.decode_snapshot(snapshot({0x7D0000: fixed(0x7D0000, 104, [tick(2) + sense])}))
        self.assertNotIn("ibm_extra", result["events"][0]["sense"])


if __name__ == "__main__":
    unittest.main()
