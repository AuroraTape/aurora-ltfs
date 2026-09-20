"""Replay command files of the LTFS file system simulator on a mount.

``contrib/fssim`` is the simulator that was written during the design
of the incremental index of format spec 2.5; ``contrib/fssim/testcases``
holds the command scripts its authors used to exercise the semantics
(rename chains, directory moves, delete and recreate under the same
name, ...). The commands are simplified Unix commands, described in
``contrib/fssim/docs/README.md``. This module runs the subset that
changes the file system against a real mount:

    touch  mkdir/md  rm  rmdir/rd  mv  cp [-r]  echo > / >>  cd  index

Commands that only display something are ignored. A command that fails
(removing what is not there, moving a directory onto a file, ...) is
skipped like the simulator does: it reports the error and goes on.
"""

import os
import shlex
import shutil
from pathlib import Path

from common.helpers import full_sync, incremental_sync


DISPLAY_ONLY = {"ls", "ll", "dir", "tree", "log", "cat", "cls", "fsck",
                "help"}


class Replay:
    def __init__(self, mnt):
        self.mnt = Path(mnt)
        self.cwd = "/"
        self.indexes = []       # "full" / "incremental", in order
        self.failed = []        # (line number, command) that did not apply
        self.changed_since_index = False

    # -- path handling -------------------------------------------------

    def _real(self, name):
        virtual = name if name.startswith("/") else \
            os.path.join(self.cwd, name)
        virtual = os.path.normpath(virtual)
        return self.mnt / virtual.lstrip("/")

    # -- commands ------------------------------------------------------

    def _touch(self, *names):
        for name in names:
            path = self._real(name)
            if path.exists():
                os.utime(path)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()

    def _mkdir(self, *names):
        for name in names:
            self._real(name).mkdir(parents=True, exist_ok=True)

    def _rm(self, name):
        path = self._real(name)
        if path.is_dir():
            raise IsADirectoryError(name)
        path.unlink()

    def _rmdir(self, name):
        self._real(name).rmdir()

    def _target(self, source, name):
        """An existing directory as the target means "into it"."""
        target = self._real(name)
        if target.is_dir():
            target = target / source.name
        return target

    def _mv(self, old, new):
        source = self._real(old)
        if source == self.mnt:
            raise PermissionError("cannot move the root")
        target = self._target(source, new)
        if target == source:
            raise FileExistsError("move to self")
        os.rename(source, target)

    def _cp(self, *args):
        if len(args) != (3 if args[:1] == ("-r",) else 2):
            raise TypeError("cp [-r] name name")
        if args[0] == "-r":
            source, target = self._real(args[1]), self._real(args[2])
            if not source.is_dir() or not target.is_dir():
                raise NotADirectoryError("cp -r needs two directories")
            shutil.copytree(source, target, dirs_exist_ok=True)
            return
        source = self._real(args[0])
        if source.is_dir():
            raise IsADirectoryError(args[0])
        shutil.copyfile(source, self._target(source, args[1]))

    def _echo(self, *args):
        if len(args) < 2 or args[-2] not in (">", ">>"):
            return          # echo to the screen
        path = self._real(args[-1])
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a" if args[-2] == ">>" else "w") as f:
            f.write(" ".join(args[:-2]))

    def _cd(self, name="/"):
        path = self._real(name)
        if not path.is_dir():
            raise NotADirectoryError(name)
        relative = str(path.relative_to(self.mnt))
        self.cwd = "/" if relative == "." else "/" + relative

    def index(self, *args):
        """index [-f | -i] [prefix]: the first index of a run is a full
        index, the following ones are incremental unless the command asks
        for a full one (-f). (Without a flag the simulator writes a full
        and an incremental index file side by side; on a tape the
        incremental one is what continues the chain.)"""
        flag = args[0] if args and args[0] in ("-f", "-i") else None
        names = args[1:] if flag else args
        reason = names[0] if names else "index"
        if flag == "-f" or not self.indexes:
            full_sync(self.mnt, reason)
            self.indexes.append("full")
        else:
            incremental_sync(self.mnt, reason)
            self.indexes.append("incremental")
        self.changed_since_index = False

    # -- driver --------------------------------------------------------

    def run(self, script):
        handlers = {
            "touch": self._touch, "mkdir": self._mkdir, "md": self._mkdir,
            "rm": self._rm, "rmdir": self._rmdir, "rd": self._rmdir,
            "mv": self._mv, "cp": self._cp, "echo": self._echo,
            "cd": self._cd, "index": self.index,
        }
        for number, line in enumerate(Path(script).read_text().splitlines(),
                                      1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            words = shlex.split(line)
            command, args = words[0], words[1:]
            if command == "exit":
                break
            if command in DISPLAY_ONLY:
                continue
            if command not in handlers:
                raise ValueError(f"{script}:{number}: unknown fssim "
                                 f"command '{command}'")
            try:
                handlers[command](*args)
                if command not in ("index", "cd"):
                    self.changed_since_index = True
            except (OSError, TypeError):
                self.failed.append((number, line))
        return self
