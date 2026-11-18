"""Helpers for the file medium changer (libchanger-file) and altfschanger.

A library is a directory:

    library.conf          identity, features, delays (key = value)
    slots/<address>       storage element, content = cartridge name or empty
    ie/<address>          import/export element, same content
    drives/Drive_<SERIAL>.<PRODUCT>
                          drive element in the format of the tape file
                          backend: "../cartridges/<name>" or "empty", NUL
                          padded to 36 bytes. Drives are numbered from
                          dt_start (257) in name order.
    cartridges/<name>/    the tape file backend directories
    inject                one-shot faults, one per line (see FileLibrary.inject)
    faults                lasting element faults, one per line (see FileLibrary.fault)
    state.conf            written by the plugin: source addresses, door state

Element addresses follow the IBM convention: transport 1, drives from 257,
import/export from 769, storage from 1025.
"""

import os
import re
import subprocess
from pathlib import Path

_TIMEOUT = 30
DRIVE_LINK_SIZE = 36

TRANSPORT_START = 1
DRIVE_START = 257
IE_START = 769
STORAGE_START = 1025

# altfschanger is a development tool in contrib/: built with the tree, not
# installed. Run the libtool wrapper from the build tree; ALTFSCHANGER overrides.
_BUILT = Path(__file__).resolve().parents[2] / "contrib" / "altfschanger" / "altfschanger"
ALTFSCHANGER = os.environ.get("ALTFSCHANGER") or (str(_BUILT) if _BUILT.exists() else "altfschanger")


class FileLibrary:
    def __init__(self, base, slots=4, ie=1, drives=("1234567890.ULTRIUM-TD5",),
                 cartridges=None, conf=None, storage_start=STORAGE_START, ie_start=IE_START):
        """Create a library under base. cartridges maps a storage or I/E
        address to a cartridge name; the matching directory under
        cartridges/ is created (unformatted) as well. Drives are numbered
        from conf["dt_start"] (257) in name order, so pass them sorted."""
        self.dir = Path(base)
        for sub in ("slots", "ie", "drives", "cartridges"):
            (self.dir / sub).mkdir(parents=True)
        lines = {"vendor": "AURORA", "model": "FILECHANGER", "serial": "FLIB0001"}
        lines.update(conf or {})
        (self.dir / "library.conf").write_text(
            "".join(f"{k} = {v}\n" for k, v in lines.items()))
        self.storage_start = storage_start
        self.ie_start = ie_start
        self.drive_start = int(lines.get("dt_start", DRIVE_START))
        self.storage = [storage_start + i for i in range(slots)]
        self.ie = [ie_start + i for i in range(ie)]
        self.drives = [self.drive_start + i for i in range(len(drives))]
        for addr in self.storage:
            (self.dir / "slots" / str(addr)).write_text("")
        for addr in self.ie:
            (self.dir / "ie" / str(addr)).write_text("")
        self.drive_files = []
        for name in drives:
            path = self.dir / "drives" / f"Drive_{name}"
            self._write_drive(path, None)
            self.drive_files.append(path)
        for addr, name in (cartridges or {}).items():
            self.put(addr, name)

    # ----- direct manipulation (the operator's panel) -----

    def element_file(self, addr):
        # range checks, not list membership: a 60,000 slot library is built
        # with one put() per slot
        if self.storage_start <= addr < self.storage_start + len(self.storage):
            return self.dir / "slots" / str(addr)
        if self.ie_start <= addr < self.ie_start + len(self.ie):
            return self.dir / "ie" / str(addr)
        if self.drive_start <= addr < self.drive_start + len(self.drives):
            return self.drive_files[addr - self.drive_start]
        raise KeyError(addr)

    def is_drive(self, addr):
        return self.drive_start <= addr < self.drive_start + len(self.drives)

    @staticmethod
    def _write_drive(path, name):
        link = f"../cartridges/{name}" if name else "empty"
        path.write_bytes(link.encode().ljust(DRIVE_LINK_SIZE, b"\0"))

    def put(self, addr, name):
        """Place cartridge name into an element behind the plugin's back."""
        if name:
            (self.dir / "cartridges" / name).mkdir(exist_ok=True)
        if self.is_drive(addr):
            self._write_drive(self.element_file(addr), name)
        else:
            self.element_file(addr).write_text(f"{name}\n" if name else "")

    def content(self, addr):
        """Cartridge name in an element, or None."""
        if self.is_drive(addr):
            raw = self.element_file(addr).read_bytes().rstrip(b"\0").decode()
            return None if raw in ("", "empty") else raw.rsplit("/", 1)[-1]
        text = self.element_file(addr).read_text().strip()
        return text or None

    def cartridge_dir(self, name):
        return self.dir / "cartridges" / name

    def inject(self, *lines):
        """Append one-shot faults: 'ua 06/2800', 'fail move 05/3B0D',
        'lost move', 'lost move_after', 'door_open 2'."""
        with open(self.dir / "inject", "a") as f:
            for line in lines:
                f.write(line + "\n")

    def fault(self, addr, what):
        """A lasting element fault: 'inaccessible' or an ASC/ASCQ such as '3B18'."""
        with open(self.dir / "faults", "a") as f:
            f.write(f"{addr} {what}\n")

    def pending_injections(self):
        path = self.dir / "inject"
        if not path.exists():
            return []
        return [l for l in path.read_text().splitlines() if l.strip()]

    def set_conf(self, key, value):
        path = self.dir / "library.conf"
        lines = [l for l in path.read_text().splitlines()
                 if not l.split("=")[0].strip() == key]
        lines.append(f"{key} = {value}")
        path.write_text("\n".join(lines) + "\n")

    def state(self):
        path = self.dir / "state.conf"
        if not path.exists():
            return {}
        out = {}
        for line in path.read_text().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
        return out

    # ----- altfschanger -----

    def run(self, *args, env=None, check=False, device=True):
        cmd = [ALTFSCHANGER, "-e", "file"]
        if device:
            cmd += ["-d", str(self.dir)]
        cmd += [str(a) for a in args]
        full_env = dict(os.environ)
        if env:
            full_env.update(env)
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=_TIMEOUT, env=full_env)
        if check and proc.returncode != 0:
            raise RuntimeError(f"{cmd} failed ({proc.returncode}):\n{proc.stderr}")
        return proc

    def elements(self, *args):
        """Parsed output of `elements`: {address: {type, full, voltag, source, dvcid, ...}}."""
        proc = self.run("elements", *args, check=True)
        out = {}
        for line in proc.stdout.splitlines():
            parts = line.split()
            if len(parts) < 3:
                continue
            e = {"type": parts[0], "full": parts[2] == "full", "voltag": None,
                 "source": None, "dvcid": None, "flags": []}
            for p in parts[3:]:
                if "=" in p:
                    k, v = p.split("=", 1)
                    e[k] = None if v == "-" else v
                else:
                    e["flags"].append(p)
            if e["source"] is not None:
                e["source"] = int(e["source"])
            out[int(parts[1])] = e
        return out

    def info(self):
        proc = self.run("info", check=True)
        out = {}
        for line in proc.stdout.splitlines():
            key, _, value = line.partition(" ")
            out[key] = value
        return out


def error_code(proc):
    """The negative LTFS/EDEV code altfschanger reports in 'ACH0004E <cmd> failed (-N)'."""
    m = re.search(r"ACH0004E .* failed \((-\d+)\)", proc.stderr)
    return int(m.group(1)) if m else None

