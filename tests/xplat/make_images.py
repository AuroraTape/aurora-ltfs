#!/usr/bin/env python3
"""Build the volume images for the cross-platform volume check (issue #141).

The macOS CI runner cannot mount (see tests/conftest.py, marker ``mount``),
so it cannot create volumes with content either. This script runs where a
mount is possible (the Linux scenario job) and writes file-backend volumes
plus what an independent check has to find in them; test_images.py then
runs ``altfsck`` and ``altfsindextool`` against the images on any platform
and compares.

Layout of OUTDIR::

    manifest.json                  who built the images, with which altfs
    populated/tape/                a volume with several index generations
    populated/expected.json        {"altfsck": "consistent", "index": {...}}
    crash/<case>/tape/             crash state of an incremental index case
    crash/<case>/expected.json     {"altfsck": "corrected", "index": {...}}

``index`` holds, per partition ("0" = index partition, "1" = data
partition), the ``index_records()`` flattening of the index a check must
end up with: for the populated volume the index its clean unmount wrote,
for a crash state the full index the clean unmount of the *original*
volume wrote, which the recovery has to reproduce on both partitions.

The crash states are the cases of tests/common/incindex_cases.py, built
exactly as tests/scenarios/test_incindex_recovery.py builds them (the MAM
``attr_*`` files are left out so the volume coherency shortcut cannot hide
the incremental indexes).

Usage: make_images.py [--cases NAME,...] [--keep-going] OUTDIR
    altfs binaries on PATH, FUSE available. --cases restricts the crash
    states to the named cases; --keep-going builds every image even when
    one fails and reports the failures at the end (exit status 1).
"""

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.altfs import format_tape, mount_tape, umount_tape  # noqa: E402
from common.helpers import full_sync, incremental_sync, set_xattr  # noqa: E402
from common.incindex_cases import CASES, setup_base  # noqa: E402
from common.index import index_records, parse_latest_index  # noqa: E402


def _indexes(tape_dir):
    return {str(p): index_records(parse_latest_index(tape_dir, p))
            for p in (0, 1)}


def _write_expected(out, altfsck, index):
    (out / "expected.json").write_text(
        json.dumps({"altfsck": altfsck, "index": index}, indent=1,
                   ensure_ascii=False, sort_keys=True) + "\n")


def _populated_tree(mnt):
    """Three index generations: two full indexes written on request, an
    incremental one, and the full index of the clean unmount. The content
    covers what an index records: nested directories, small and multi-block
    files, an empty file, a non-ASCII name, a symlink, extended attributes
    on a file and a directory, the read-only flag, a rename and a delete."""
    (mnt / "docs").mkdir()
    (mnt / "docs" / "readme.txt").write_text("read me\n")
    (mnt / "data").mkdir()
    # 1.5 MiB: spans several 512 KiB blocks, so the file has real extents
    (mnt / "data" / "big.bin").write_bytes(bytes(range(256)) * 6144)
    (mnt / "empty.txt").touch()
    (mnt / "日本語のファイル.txt").write_text("non-ASCII name\n")
    os.symlink("docs/readme.txt", mnt / "link-to-readme")
    set_xattr(mnt / "docs" / "readme.txt", "test.tag", "on a file")
    full_sync(mnt, "generation 1")

    os.rename(mnt / "docs" / "readme.txt", mnt / "docs" / "README.txt")
    (mnt / "empty.txt").unlink()
    (mnt / "docs" / "notes.txt").write_text("notes\n")
    os.chmod(mnt / "data" / "big.bin", 0o444)
    set_xattr(mnt / "data", "test.dir", "on a directory")
    full_sync(mnt, "generation 2")

    (mnt / "docs" / "notes.txt").write_text("notes, changed after the full index\n")
    (mnt / "data" / "small.bin").write_bytes(b"\x00\x01\x02\x03" * 64)
    incremental_sync(mnt, "incremental after generation 2")


def _fresh(out):
    """Start the image directory over: a rebuilt image (--cases, a second
    run into the same OUTDIR) must not carry records of the previous one."""
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)


def build_populated(out, work):
    tape, mnt = out / "tape", work / "mnt"
    _fresh(out)
    tape.mkdir()
    mnt.mkdir(parents=True)
    format_tape(tape, serial="XPLAT0", label="xplat")
    mount_tape(tape, mnt)
    try:
        _populated_tree(mnt)
    finally:
        umount_tape(mnt)
    _write_expected(out, "consistent", _indexes(tape))


def build_crash(out, work, steps):
    original, mnt = work / "tape", work / "mnt"
    original.mkdir(parents=True)
    mnt.mkdir(parents=True)
    format_tape(original, serial="INCIDX", label="incidx")
    mount_tape(original, mnt)
    try:
        setup_base(mnt)
        full_sync(mnt, "base")
        for number, step in enumerate(steps, 1):
            step(mnt)
            incremental_sync(mnt, f"inc {number}")
        # Nothing writes to the tape directory now (see
        # tests/common/recovery.py): this copy is the crash state.
        _fresh(out)
        shutil.copytree(original, out / "tape",
                        ignore=shutil.ignore_patterns("attr_*"))
    finally:
        umount_tape(mnt)
    # The clean unmount wrote the full index the recovery must reproduce,
    # on both partitions.
    ground_truth = index_records(parse_latest_index(original))
    _write_expected(out, "corrected", {"0": ground_truth, "1": ground_truth})


def _altfs_version():
    """First line of ``altfs --version``; also the check that the altfs
    binaries are on PATH before any image is built."""
    try:
        r = subprocess.run(["altfs", "--version"], capture_output=True,
                           text=True, timeout=30)
    except OSError as exc:
        sys.exit(f"altfs is not runnable ({exc}); put the altfs bin directory on PATH")
    lines = (r.stdout + r.stderr).strip().splitlines()
    return lines[0] if lines else "unknown"


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("outdir", type=Path)
    parser.add_argument("--cases", metavar="NAME,...",
                        help="crash states to build (default: all)")
    parser.add_argument("--keep-going", action="store_true",
                        help="build every image even when one fails")
    args = parser.parse_args(argv[1:])

    cases = CASES
    if args.cases:
        wanted = args.cases.split(",")
        unknown = set(wanted) - {name for name, _ in CASES}
        if unknown:
            parser.error(f"unknown case(s): {', '.join(sorted(unknown))}")
        cases = [(name, steps) for name, steps in CASES if name in wanted]

    altfs_version = _altfs_version()
    outdir = args.outdir.resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    builds = [("populated", lambda work: build_populated(outdir / "populated", work))]
    builds += [(f"crash/{name}", lambda work, s=steps, n=name:
                build_crash(outdir / "crash" / n, work, s)) for name, steps in cases]

    images, failed = [], []
    with tempfile.TemporaryDirectory(prefix="altfs-xplat-") as tmp:
        for name, build in builds:
            try:
                build(Path(tmp) / name.replace("/", "-"))
            except Exception as exc:  # noqa: BLE001 - reported below
                if not args.keep_going:
                    raise
                failed.append((name, exc))
                shutil.rmtree(outdir / name, ignore_errors=True)
                print(f"FAILED {name}: {exc!r}", file=sys.stderr)
                continue
            images.append(name)

    (outdir / "manifest.json").write_text(json.dumps({
        "generator": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "altfs": altfs_version,
        "images": images,
    }, indent=1) + "\n")
    print(f"{len(images)} images under {outdir}"
          + (f", {len(failed)} failed" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
