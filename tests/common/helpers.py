from __future__ import annotations

import ctypes
import ctypes.util
import os
import re
import sys
from pathlib import Path


_RECORD_RE = re.compile(r"^(\d+)_(\d+)_R$")

# Extended attributes as altfs exposes them: on Linux under the user.*
# namespace (the kernel only lets unprivileged callers see and set that
# namespace, and altfs strips the prefix), on macOS under their own name.
# Python has os.*xattr only on Linux, so macOS goes through libc.
_NS = "" if sys.platform == "darwin" else "user."


if sys.platform == "darwin":
    _libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    # <sys/xattr.h>: (path, name, value, size, position, options)
    _libc.getxattr.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p,
                               ctypes.c_size_t, ctypes.c_uint32, ctypes.c_int]
    _libc.getxattr.restype = ctypes.c_ssize_t
    _libc.setxattr.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p,
                               ctypes.c_size_t, ctypes.c_uint32, ctypes.c_int]
    _libc.setxattr.restype = ctypes.c_int
    _libc.removexattr.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
    _libc.removexattr.restype = ctypes.c_int
    _libc.listxattr.argtypes = [ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t,
                                ctypes.c_int]
    _libc.listxattr.restype = ctypes.c_ssize_t
    _XATTR_NOFOLLOW = 0x0001
    # Attributes macOS itself attaches to files (com.apple.provenance,
    # com.apple.FinderInfo, ...): not something altfs stores.
    _SYSTEM_PREFIX = "com.apple."

    def _check(ret, path):
        if ret < 0:
            errno = ctypes.get_errno()
            raise OSError(errno, os.strerror(errno), os.fspath(path))
        return ret

    def _getxattr(path, name, follow_symlinks=True):
        p, n = os.fsencode(os.fspath(path)), name.encode()
        opts = 0 if follow_symlinks else _XATTR_NOFOLLOW
        size = _check(_libc.getxattr(p, n, None, 0, 0, opts), path)
        buf = ctypes.create_string_buffer(size)
        got = _check(_libc.getxattr(p, n, buf, size, 0, opts), path)
        return buf.raw[:got]

    def _setxattr(path, name, value):
        p, n = os.fsencode(os.fspath(path)), name.encode()
        _check(_libc.setxattr(p, n, value, len(value), 0, 0), path)

    def _removexattr(path, name):
        _check(_libc.removexattr(os.fsencode(os.fspath(path)), name.encode(),
                                 0), path)

    def _listxattr(path, follow_symlinks=True):
        p = os.fsencode(os.fspath(path))
        opts = 0 if follow_symlinks else _XATTR_NOFOLLOW
        size = _check(_libc.listxattr(p, None, 0, opts), path)
        if size == 0:
            return []
        buf = ctypes.create_string_buffer(size)
        got = _check(_libc.listxattr(p, buf, size, opts), path)
        return [n.decode() for n in buf.raw[:got].split(b"\0") if n]
else:
    _SYSTEM_PREFIX = None

    def _getxattr(path, name, follow_symlinks=True):
        return os.getxattr(os.fspath(path), name, follow_symlinks=follow_symlinks)

    def _setxattr(path, name, value):
        os.setxattr(os.fspath(path), name, value)

    def _removexattr(path, name):
        os.removexattr(os.fspath(path), name)

    def _listxattr(path, follow_symlinks=True):
        return os.listxattr(os.fspath(path), follow_symlinks=follow_symlinks)


def get_xattr_bytes(path, name, follow_symlinks=True):
    return _getxattr(path, _NS + name, follow_symlinks)


def get_xattr(path, name):
    return get_xattr_bytes(path, name).decode("utf-8")


def get_xattr_int(path, name):
    return int(get_xattr(path, name))


def set_xattr(path, name, value):
    """value: str (encoded as UTF-8) or bytes."""
    if isinstance(value, str):
        value = value.encode("utf-8")
    _setxattr(path, _NS + name, value)


def remove_xattr(path, name):
    _removexattr(path, _NS + name)


def list_xattrs(path, follow_symlinks=True):
    """The attributes altfs exposes on the object, named as altfs knows
    them: on Linux the user.* namespace without its prefix (the other
    namespaces are the kernel's), on macOS everything but the com.apple.*
    attributes macOS attaches itself."""
    names = _listxattr(path, follow_symlinks)
    if _SYSTEM_PREFIX:
        names = [n for n in names if not n.startswith(_SYSTEM_PREFIX)]
    return [n[len(_NS):] for n in names if n.startswith(_NS)]


def full_sync(mnt, reason="test"):
    set_xattr(mnt, "ltfs.vendor.Aurora.FullSync", reason)


def incremental_sync(mnt, reason="test"):
    set_xattr(mnt, "ltfs.vendor.Aurora.IncrementalSync", reason)


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
