from __future__ import annotations

import os
import re
from pathlib import Path


_RECORD_RE = re.compile(r"^(\d+)_(\d+)_R$")

# On Linux, LTFS xattrs are exposed under the user.* namespace; the kernel
# only lets unprivileged callers see/set xattrs in that namespace.
_LINUX_NS = "user."


def get_xattr(path, name):
    return os.getxattr(os.fspath(path), _LINUX_NS + name).decode("utf-8")


def get_xattr_int(path, name):
    return int(get_xattr(path, name))


def set_xattr(path, name, value):
    os.setxattr(os.fspath(path), _LINUX_NS + name, value.encode("utf-8"))


def full_sync(mnt, reason="test"):
    set_xattr(mnt, "ltfs.vendor.Aurora.FullSync", reason)


def list_records(tape_dir):
    ip, dp = [], []
    for name in os.listdir(tape_dir):
        m = _RECORD_RE.match(name)
        if not m:
            continue
        partition, block = int(m.group(1)), int(m.group(2))
        path = Path(tape_dir) / name
        if partition == 0:
            ip.append((block, path))
        elif partition == 1:
            dp.append((block, path))
    ip.sort()
    dp.sort()
    return [p for _, p in ip], [p for _, p in dp]
