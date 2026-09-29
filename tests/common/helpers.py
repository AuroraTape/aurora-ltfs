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
# namespace, and altfs strips the prefix), elsewhere under their own name
# (macOS has no namespaces; the BSDs pass the "user" namespace as a
# separate argument and their FUSE layers add and strip the prefix).
# Python has os.*xattr only on Linux, so the other platforms go through
# libc.
_NS = "user." if sys.platform.startswith("linux") else ""


def _check(ret, path):
    if ret < 0:
        errno = ctypes.get_errno()
        raise OSError(errno, os.strerror(errno), os.fspath(path))
    return ret


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

    def _getxattr(path, name, follow_symlinks=True):
        p, n = os.fsencode(os.fspath(path)), name.encode()
        opts = 0 if follow_symlinks else _XATTR_NOFOLLOW
        size = _check(_libc.getxattr(p, n, None, 0, 0, opts), path)
        if size == 0:
            return b""  # a zero-length buffer would be answered with ERANGE
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
elif sys.platform.startswith(("freebsd", "netbsd")):
    _libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    # <sys/extattr.h>: the namespace is an argument, the name is bare
    _EXTATTR_NAMESPACE_USER = 1
    for _fn in ("extattr_get_file", "extattr_get_link", "extattr_set_file"):
        getattr(_libc, _fn).argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p,
                                        ctypes.c_void_p, ctypes.c_size_t]
        getattr(_libc, _fn).restype = ctypes.c_ssize_t
    _libc.extattr_delete_file.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p]
    _libc.extattr_delete_file.restype = ctypes.c_int
    for _fn in ("extattr_list_file", "extattr_list_link"):
        getattr(_libc, _fn).argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p,
                                        ctypes.c_size_t]
        getattr(_libc, _fn).restype = ctypes.c_ssize_t
    _SYSTEM_PREFIX = None

    def _getxattr(path, name, follow_symlinks=True):
        fn = _libc.extattr_get_file if follow_symlinks else _libc.extattr_get_link
        p, n = os.fsencode(os.fspath(path)), name.encode()
        size = _check(fn(p, _EXTATTR_NAMESPACE_USER, n, None, 0), path)
        if size == 0:
            return b""
        buf = ctypes.create_string_buffer(size)
        got = _check(fn(p, _EXTATTR_NAMESPACE_USER, n, buf, size), path)
        return buf.raw[:got]

    def _setxattr(path, name, value):
        p, n = os.fsencode(os.fspath(path)), name.encode()
        _check(_libc.extattr_set_file(p, _EXTATTR_NAMESPACE_USER, n, value,
                                      len(value)), path)

    def _removexattr(path, name):
        _check(_libc.extattr_delete_file(os.fsencode(os.fspath(path)),
                                         _EXTATTR_NAMESPACE_USER, name.encode()), path)

    def _listxattr(path, follow_symlinks=True):
        # The list is a sequence of (length byte, name) pairs.
        fn = _libc.extattr_list_file if follow_symlinks else _libc.extattr_list_link
        p = os.fsencode(os.fspath(path))
        size = _check(fn(p, _EXTATTR_NAMESPACE_USER, None, 0), path)
        if size == 0:
            return []
        buf = ctypes.create_string_buffer(size)
        got = _check(fn(p, _EXTATTR_NAMESPACE_USER, buf, size), path)
        data, names, i = buf.raw[:got], [], 0
        while i < len(data):
            length = data[i]
            names.append(data[i + 1:i + 1 + length].decode())
            i += 1 + length
        return names
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
