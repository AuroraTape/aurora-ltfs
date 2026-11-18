#!/usr/bin/env python3
"""The operator's panel of a file medium changer (libchanger-file).

    filelib.py <dir> create <library.yaml>     build the directory
    filelib.py <dir> show [--all]              what is where
    filelib.py <dir> move <barcode> <to>       move a cartridge by hand
    filelib.py <dir> insert <barcode> [<to>]   a new cartridge appears (default: a free I/E slot)
    filelib.py <dir> remove <barcode>          a cartridge leaves the library
    filelib.py <dir> relabel <barcode> <new>   the label changes, the medium does not (a
                                               formatted tape keeps the old barcode in its MAM)
    filelib.py <dir> fault <element> inaccessible | <ASCASCQ> | clear
                                               a lasting element fault: READ ELEMENT STATUS
                                               shows it, MOVE / EXCHANGE touching it fails
                                               (3B18 element disabled, 3B1A drive removed)
    filelib.py <dir> inject <line>             a one-shot fault for the next SMC command, e.g.
                                               'ua 06/2800', 'fail move 05/3B0D', 'lost move_after'
    filelib.py <dir> door open|close           the library answers NOT READY (02/0418) until closed

Everything works while a changer process has the library open: the plugin
reads the files on every command, so these are the operator, another host or
a failing part changing the library behind the back of the mounted altfs.

<to> is an element address, a drive serial, or the word ie / slot for the
first free one of that kind; <element> is an address or a drive serial.
insert takes --type to put a label of one generation on a medium of another
(insert BAD001L7 --type L5). The commands write the files directly, as an
operator at the panel would, behind the back of the SMC path; the SMC path
is `altfschanger -e file -d <dir> move|exchange|elements ...`.

The YAML for create is counts; barcodes are generated (000001L5, ...):

    library:
      vid: IBM
      pid: 3584-TL
      serial: '0123456789'
      slots: 100
      ie: 20
      drives:
        - {vid: IBM, pid: ULTRIUM-TD5, serial: '000000001'}
        - {vid: IBM, pid: ULTRIUM-TD6, serial: '000000002'}
      cartridges:
        L5: 10                             # 000001L5 ... 000010L5
        L6: {volser: 'A01001', num: 10}    # A01001L6 ... A01010L6

Cartridges are not formatted (formatting and checking are jobs of the
library mount). Each gets the filedebug_tc_conf.xml of its type, so the tape
file backend sees the generation that the barcode says: cart_type from the
last two characters (L5 to L9, M8, the 3592 J types), the density fixed for
LTO and unknown for 3592 until a format sets it.
"""

import argparse
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.changer import FileLibrary, DRIVE_LINK_SIZE  # noqa: E402

# barcode suffix -> (cart_type of filedebug_tc_conf.xml, density code).
# LTO: the density is fixed by the generation (M8 is an L7 cartridge at the
# M8 density). 3592: the same cartridge is written at the density of the
# drive that formats it, so it is left unknown (0) until a format sets it;
# the mountability table of ibm_tape.c has entries for that state.
CARTRIDGE_TYPES = {
    "L5": ("L5", 0x58), "L6": ("L6", 0x5A), "L7": ("L7", 0x5C),
    "M8": ("M8", 0x5D), "L8": ("L8", 0x5E), "L9": ("L9", 0x60),
    "JB": ("JB", 0x00), "JC": ("JC", 0x00), "JK": ("JK", 0x00), "JY": ("JY", 0x00),
    "JD": ("JD", 0x00), "JL": ("JL", 0x00), "JZ": ("JZ", 0x00),
    "JE": ("JE", 0x00), "JV": ("JV", 0x00), "JM": ("JM", 0x00), "JF": ("JF", 0x00),
}
CAPACITY_MB = 3072  # the tape file backend's default

CARTRIDGE_CONF = """<?xml version="1.0" encoding="UTF-8"?>
<filedebug_cartridge_config>
    <dummy_io>false</dummy_io>
    <emulate_readonly>false</emulate_readonly>
    <capacity_mb>{capacity_mb}</capacity_mb>
    <cart_type>{cart_type}</cart_type>
    <density_code>{density:02X}</density_code>
</filedebug_cartridge_config>
"""


class Fail(Exception):
    pass


# ---------------------------------------------------------------- create

def create(dest, spec_path):
    import yaml

    with open(spec_path) as f:
        spec = yaml.safe_load(f) or {}
    lib = spec.get("library")
    if not isinstance(lib, dict):
        raise Fail("library: missing")
    drives = lib.get("drives") or []
    if not drives:
        raise Fail("library.drives: at least one drive is needed")
    serials = [str(d.get("serial", "")) for d in drives]
    if "" in serials:
        raise Fail("library.drives: every drive needs a serial")
    if serials != sorted(serials) or len(set(serials)) != len(serials):
        raise Fail("library.drives: the plugin numbers the drive files in name order; "
                   f"list distinct serials sorted: {sorted(set(serials))}")
    barcodes = cartridge_barcodes(lib.get("cartridges") or {})
    slots = int(lib.get("slots", 4))
    if len(barcodes) > slots:
        raise Fail(f"library.cartridges: {len(barcodes)} cartridges for {slots} slots")

    conf = {"vendor": lib.get("vid", "AURORA"), "model": lib.get("pid", "FILECHANGER"),
            "serial": str(lib.get("serial", "FLIB0001"))}
    flib = FileLibrary(dest, slots=slots, ie=int(lib.get("ie", 1)),
                       drives=[f"{d['serial']}.{d.get('pid', 'ULTRIUM-TD5')}" for d in drives],
                       conf=conf)
    for i, barcode in enumerate(barcodes):
        flib.put(flib.storage[i], barcode)
        write_cartridge_conf(flib.cartridge_dir(barcode), barcode)
    return flib, len(barcodes)


def cartridge_barcodes(carts):
    """The barcodes of the cartridges section, in order. A type takes a count
    (six digit counter shared by all such types) or {volser, num} (the first
    volume serial and how many follow it by incrementing its trailing digits)."""
    if not isinstance(carts, dict):
        raise Fail("library.cartridges: expected type: count or type: {volser, num}")
    out = []
    seen = set()
    counter = 0
    for ctype, value in carts.items():
        ctype = str(ctype).upper()
        if ctype not in CARTRIDGE_TYPES:
            raise Fail(f"library.cartridges: unknown type {ctype}; one of {' '.join(CARTRIDGE_TYPES)}")
        if isinstance(value, dict):
            volser = str(value.get("volser", ""))
            num = int(value.get("num", 1))
            m = re.fullmatch(r"([A-Z0-9]*?)(\d+)", volser)
            if len(volser) != 6 or not m:
                raise Fail(f"library.cartridges: {ctype}: volser must be 6 upper case letters and digits "
                           f"ending in digits, got {volser!r}")
            head, digits = m.groups()
            for k in range(num):
                tail = str(int(digits) + k).zfill(len(digits))
                if len(tail) > len(digits):
                    raise Fail(f"library.cartridges: {ctype}: {volser} + {num} overflows its digits")
                out.append(f"{head}{tail}{ctype}")
        else:
            for _ in range(int(value)):
                counter += 1
                out.append(f"{counter:06d}{ctype}")
    for b in out:
        if b in seen:
            raise Fail(f"library.cartridges: {b} generated twice")
        seen.add(b)
    return out


def write_cartridge_conf(cart_dir, barcode, medium_type=None):
    """The medium is what the barcode says unless medium_type names another generation."""
    key = (medium_type or barcode[-2:]).upper()
    if key not in CARTRIDGE_TYPES:
        raise Fail(f"{key}: unknown cartridge type; one of {' '.join(CARTRIDGE_TYPES)}")
    cart_type, density = CARTRIDGE_TYPES[key]
    (cart_dir / "filedebug_tc_conf.xml").write_text(
        CARTRIDGE_CONF.format(capacity_mb=CAPACITY_MB, cart_type=cart_type, density=density))


# ---------------------------------------------------------------- the panel

class Panel:
    """Reads and writes an existing library directory."""

    def __init__(self, root):
        self.dir = Path(root)
        if not (self.dir / "library.conf").is_file():
            raise Fail(f"{root}: no library.conf, not a file medium changer")
        self.conf = self._read_conf(self.dir / "library.conf")
        self.storage = sorted(int(p.name) for p in (self.dir / "slots").iterdir() if p.name.isdigit())
        self.ie = sorted(int(p.name) for p in (self.dir / "ie").iterdir() if p.name.isdigit())
        dt_start = int(self.conf.get("dt_start", 257))
        files = sorted(p for p in (self.dir / "drives").iterdir() if p.name.startswith("Drive_"))
        self.drives = {}  # address -> (serial, product, path)
        for i, path in enumerate(files):
            serial, _, product = path.name[len("Drive_"):].partition(".")
            self.drives[dt_start + i] = (serial, product, path)

    @staticmethod
    def _read_conf(path):
        out = {}
        if path.exists():
            for line in path.read_text().splitlines():
                key, eq, value = line.partition("=")
                if eq and not line.lstrip().startswith("#"):
                    out[key.strip()] = value.strip()
        return out

    # -- elements
    def kind(self, addr):
        if addr in self.storage:
            return "storage"
        if addr in self.ie:
            return "ie"
        if addr in self.drives:
            return "drive"
        raise Fail(f"no element {addr}")

    def path(self, addr):
        kind = self.kind(addr)
        if kind == "drive":
            return self.drives[addr][2]
        return self.dir / ("slots" if kind == "storage" else "ie") / str(addr)

    def content(self, addr):
        if self.kind(addr) == "drive":
            raw = self.path(addr).read_bytes().rstrip(b"\0").decode()
            return None if raw in ("", "empty") else raw.rsplit("/", 1)[-1]
        return self.path(addr).read_text().strip() or None

    def put(self, addr, name):
        if self.kind(addr) == "drive":
            link = f"../cartridges/{name}" if name else "empty"
            self.path(addr).write_bytes(link.encode().ljust(DRIVE_LINK_SIZE, b"\0"))
        else:
            self.path(addr).write_text(f"{name}\n" if name else "")

    def where(self, barcode):
        for addr in list(self.drives) + self.ie + self.storage:
            if self.content(addr) == barcode:
                return addr
        raise Fail(f"{barcode} is not in the library")

    def resolve(self, to):
        """An address, a drive serial, or ie / slot for the first free one."""
        if to in ("ie", "slot", "storage"):
            pool = self.ie if to == "ie" else self.storage
            for addr in pool:
                if self.content(addr) is None:
                    return addr
            raise Fail(f"no free {to} element")
        for addr, (serial, _, _) in self.drives.items():
            if serial == to:
                return addr
        if not to.isdigit():
            raise Fail(f"{to}: not an address, a drive serial, ie or slot")
        addr = int(to)
        self.kind(addr)
        return addr

    # -- commands
    def show(self, everything=False):
        c = self.conf
        print(f"{c.get('vendor', '')} {c.get('model', '')} {c.get('serial', '')}  "
              f"{len(self.storage)} storage, {len(self.ie)} import/export, {len(self.drives)} drives")
        faults = self.faults()
        if self.door_is_open():
            print("door open: the library is NOT READY")

        def mark(addr):
            return f"  [{faults[addr]}]" if addr in faults else ""

        for addr, (serial, product, _) in self.drives.items():
            print(f"drive   {addr:5d}  {serial:<12} {product:<12} {self.content(addr) or '-'}{mark(addr)}")
        for label, pool in (("ie", self.ie), ("storage", self.storage)):
            empty = 0
            for addr in pool:
                name = self.content(addr)
                if name is None and addr not in faults and not everything:
                    empty += 1
                    continue
                print(f"{label:<7} {addr:5d}  {name or '-'}{mark(addr)}")
            if empty:
                print(f"{label:<7}        {empty} empty")

    def move(self, barcode, to):
        src = self.where(barcode)
        dst = self.resolve(to)
        if self.content(dst) is not None:
            raise Fail(f"{dst} holds {self.content(dst)}")
        self.put(src, None)
        self.put(dst, barcode)
        print(f"{barcode}: {src} -> {dst}")

    def insert(self, barcode, to="ie", medium_type=None):
        if barcode.upper() != barcode or not barcode.isalnum():
            raise Fail(f"{barcode}: a barcode is upper case letters and digits")
        for addr in list(self.drives) + self.ie + self.storage:
            if self.content(addr) == barcode:
                raise Fail(f"{barcode} is already in element {addr}")
        dst = self.resolve(to)
        if self.content(dst) is not None:
            raise Fail(f"{dst} holds {self.content(dst)}")
        cart_dir = self.dir / "cartridges" / barcode
        if not cart_dir.exists():
            cart_dir.mkdir()
            write_cartridge_conf(cart_dir, barcode, medium_type)
        elif medium_type:
            write_cartridge_conf(cart_dir, barcode, medium_type)
        self.put(dst, barcode)
        print(f"{barcode}: inserted into {dst}" + (f" (medium is {medium_type.upper()})" if medium_type else ""))

    def relabel(self, barcode, new):
        if new.upper() != new or not new.isalnum():
            raise Fail(f"{new}: a barcode is upper case letters and digits")
        src = self.where(barcode)
        if (self.dir / "cartridges" / new).exists():
            raise Fail(f"{new}: a cartridge directory of that name exists")
        (self.dir / "cartridges" / barcode).rename(self.dir / "cartridges" / new)
        self.put(src, new)
        print(f"{barcode} -> {new} in {src} (the medium and its MAM are unchanged)")

    def fault(self, element, what):
        addr = self.resolve(element)
        path = self.dir / "faults"
        lines = [l for l in (path.read_text().splitlines() if path.exists() else [])
                 if l.split() and l.split()[0] != str(addr)]
        if what == "clear":
            print(f"{addr}: fault cleared")
        else:
            if what != "inaccessible" and not re.fullmatch(r"[0-9A-Fa-f]{4}", what):
                raise Fail("fault takes inaccessible, four hex digits (ASC ASCQ) or clear")
            lines.append(f"{addr} {what.upper() if what != 'inaccessible' else what}")
            print(f"{addr}: {what}")
        path.write_text("".join(l + "\n" for l in lines))

    def inject(self, words):
        with open(self.dir / "inject", "a") as f:
            f.write(" ".join(words) + "\n")
        print(f"injected: {' '.join(words)}")

    def door(self, state):
        path = self.dir / "state.conf"
        conf = self._read_conf(path)
        conf["not_ready_until"] = str(2**31 - 1 if state == "open" else 0)
        path.write_text("".join(f"{k} = {v}\n" for k, v in conf.items()))
        print(f"door {state}")

    def door_is_open(self):
        return int(self._read_conf(self.dir / "state.conf").get("not_ready_until", 0)) > time.time()

    def faults(self):
        path = self.dir / "faults"
        out = {}
        if path.exists():
            for l in path.read_text().splitlines():
                w = l.split()
                if len(w) >= 2 and w[0].isdigit():
                    out[int(w[0])] = w[1]
        return out

    def remove(self, barcode):
        src = self.where(barcode)
        self.put(src, None)
        print(f"{barcode}: removed from {src} (its directory stays under cartridges/)")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__.split("\n", 2)[2])
    ap.add_argument("dir", help="the library directory")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("create").add_argument("spec", help="YAML description")
    sub.add_parser("show").add_argument("--all", action="store_true", help="list empty elements too")
    p = sub.add_parser("move")
    p.add_argument("barcode")
    p.add_argument("to")
    p = sub.add_parser("insert")
    p.add_argument("barcode")
    p.add_argument("to", nargs="?", default="ie")
    p.add_argument("--type", help="generation of the medium when the label lies (L5, L7, JC, ...)")
    sub.add_parser("remove").add_argument("barcode")
    p = sub.add_parser("relabel")
    p.add_argument("barcode")
    p.add_argument("new")
    p = sub.add_parser("fault")
    p.add_argument("element")
    p.add_argument("what")
    sub.add_parser("inject").add_argument("words", nargs="+")
    sub.add_parser("door").add_argument("state", choices=("open", "close"))
    args = ap.parse_args(argv)

    try:
        if args.cmd == "create":
            if Path(args.dir).exists():
                raise Fail(f"{args.dir} exists")
            lib, n = create(args.dir, args.spec)
            print(f"{lib.dir}: {len(lib.storage)} storage, {len(lib.ie)} import/export, "
                  f"{len(lib.drives)} drives, {n} cartridges")
            return
        panel = Panel(args.dir)
        if args.cmd == "show":
            panel.show(args.all)
        elif args.cmd == "move":
            panel.move(args.barcode, args.to)
        elif args.cmd == "insert":
            panel.insert(args.barcode, args.to, args.type)
        elif args.cmd == "remove":
            panel.remove(args.barcode)
        elif args.cmd == "relabel":
            panel.relabel(args.barcode, args.new)
        elif args.cmd == "fault":
            panel.fault(args.element, args.what)
        elif args.cmd == "inject":
            panel.inject(args.words)
        elif args.cmd == "door":
            panel.door(args.state)
    except Fail as e:
        sys.exit(f"{ap.prog}: {e}")


if __name__ == "__main__":
    main()
