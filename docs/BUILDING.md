# Building from source

Most users install the packages instead: see "Installing packages" in the
[README](../README.md#installing-packages). Build from source to work on Aurora
LTFS, to run it on a platform without packages (FreeBSD, NetBSD, Linux
distributions other than the Tier 1 ones), or to try a change before it is
released.

## Prerequisites

### Linux

Ubuntu / Debian:

```
# apt install build-essential autoconf automake libtool pkg-config \
      libfuse-dev libxml2-dev libicu-dev icu-devtools uuid-dev
```

Rocky Linux / RHEL 9 (`fuse-devel` is in CRB; `redhat-rpm-config` and the
annobin plugin are needed by ICU's `pkgdata`, which compiles the message
catalogs with the distribution's compiler flags):

```
# dnf install dnf-plugins-core
# dnf config-manager --set-enabled crb
# dnf install autoconf automake libtool make gcc pkg-config \
      fuse-devel libxml2-devel libicu-devel icu libuuid-devel \
      redhat-rpm-config gcc-plugin-annobin diffutils
```

Dev Container definitions with the full development environment (debugger,
valgrind, docbook tools) are in [.devcontainer/](../.devcontainer/), for
[Ubuntu 24.04](../.devcontainer/ubuntu2404/) and [Rocky Linux 9](../.devcontainer/rocky9/).
Use them with VS Code Dev Containers or as the reference list of packages.

### macOS

Install macFUSE and the libraries with Homebrew:

```
$ brew install --cask macfuse
$ brew install autoconf automake libtool pkg-config ossp-uuid libxml2 icu4c
```

`icu4c` and `libxml2` are keg-only, and the ICU tools (`genrb`, `pkgdata`)
must be the Homebrew ones found through `PATH` at configure time; macFUSE
installs `fuse.pc` under `/usr/local/lib/pkgconfig`, also on Apple silicon:

```
$ export PKG_CONFIG_PATH="$(brew --prefix icu4c)/lib/pkgconfig:$(brew --prefix libxml2)/lib/pkgconfig:/usr/local/lib/pkgconfig"
$ export PATH="$(brew --prefix icu4c)/bin:$(brew --prefix libxml2)/bin:$PATH"
```

A legacy `/Library/Frameworks/ICU.framework` (e.g. ICU 4.8 from old LTFS SDE
installs) is not supported and is ignored by the build.

### FreeBSD

FreeBSD 10.2 or later (sa(4) driver support):

```
# pkg install automake autoconf libtool pkgconf gmake fusefs-libs libuuid libxml2 icu
```

### NetBSD

NetBSD 7.0 or later (FUSE support):

```
# pkgin install automake autoconf libtool-base pkgconf gmake fuse libuuid libxml2 icu
```

## Build and install

Linux:

```
$ ./autogen.sh
$ ./configure
$ make
# make install
```

macOS:

```
$ ./autogen.sh
$ LDFLAGS="-framework CoreFoundation -framework IOKit" ./configure
$ make
$ sudo make install
```

FreeBSD:

```
$ ./autogen.sh
$ ./configure --prefix=/usr/local --mandir=/usr/local/man
$ gmake
# gmake install
```

NetBSD:

```
$ ./autogen.sh
$ ./configure
$ gmake
# gmake install
```

The default prefix is `/usr/local`. `./configure --help` lists all options;
the ones used most:

- `--prefix=<dir>`: where to install. For development, a directory of your
  own (the CI uses `--prefix=$PWD/_install`) needs no root and is what the
  test suites expect.
- `--sysconfdir=<dir>`: where `altfs.conf` goes (default `PREFIX/etc`). The
  packages use `/etc`.
- `--with-systemdsystemunitdir=<dir>`, `--with-sysusersdir=<dir>` (Linux):
  where the systemd units and the sysusers.d file of the `altfs` user go
  (default under `PREFIX/lib`). The packages use the system directories.
- `--enable-debug`: debug build with extra debugging output.
- `--enable-warning-as-error`: what the CI builds with on Linux.

Notes:

- On Linux, run `ldconfig` after `make install` if the commands do not find
  `libaltfs`.
- After moving `HEAD` (another branch, a new tag), run
  `rm -rf autom4te.cache && ./autogen.sh` again: the version string is cached.
  After changing `--prefix`, run `make clean` first; libtool refuses to install
  objects built for another prefix.
- On Linux `make install` also installs `altfs.service`, which unmounts every
  LTFS volume cleanly at shutdown. With a prefix other than `/usr`, register
  it yourself: `systemctl enable --now <prefix>/lib/systemd/system/altfs.service`.
  The syslog and logrotate files are described in [conf/README.md](../conf/README.md).
- The man pages are generated from the DocBook sources in `man/sgml` when
  `docbook2man` is installed; otherwise the pages in `man/` are installed as
  they are. See [man/README.md](../man/README.md).

## Running the tests

The test suites run the installed commands with pytest. They need pytest
and, for the tests that mount, the FUSE runtime (`fusermount`):

- Ubuntu / Debian: `apt install python3-pytest fuse`; Rocky Linux / RHEL:
  `dnf install python3-pytest fuse`
- macOS: pytest in a virtual environment (Homebrew's Python refuses `pip
  install` outside one): `python3 -m venv ~/venv && ~/venv/bin/pip install pytest`
- FreeBSD / NetBSD: the `py3XX-pytest` package of the default Python

Install into a prefix of your own, then point the suites at it with
`ALTFS_PREFIX`:

```
$ ./configure --prefix=$PWD/_install
$ make && make install
$ ALTFS_PREFIX=$PWD/_install bash tests/scenarios/run.sh -v
$ ALTFS_PREFIX=$PWD/_install bash tests/fsapi/run.sh -v
```

- `tests/scenarios`: command-line behaviour, mostly on the `file` tape
  backend (a directory that emulates a tape). Tests that need a FUSE mount
  are marked `mount`; where mounting is not possible (the macOS CI runners),
  run the others with `-m "not mount"`. On FreeBSD and NetBSD the CI runs
  `python3 -m pytest tests/scenarios -m "not mount"` with `PATH` and
  `LD_LIBRARY_PATH` set to the prefix, as `run.sh` does.
- `tests/fsapi`: file system API tests on a mounted `file` backend volume;
  they need FUSE.
- `tests/xplat`: reads volumes written on another platform; needs
  `ALTFS_IMAGE_DIR`, the output of `tests/xplat/make_images.py` (see
  `tests/xplat/test_images.py`).
- `tests/realdrive`: checks on a real tape drive, run by hand; see
  [tests/realdrive/README.md](../tests/realdrive/README.md).

## Building the packages

The deb and rpm packages are built by the release workflow
([`.github/workflows/release.yml`](../.github/workflows/release.yml)); its
`deb` and `rpm` jobs are the reference. In short, in a clean Ubuntu 24.04 or
Rocky Linux 9 container:

The packaging files carry placeholder versions (`0.0.0~manual` in
`debian/changelog`, `0.0.0` in `rpm/altfs.spec`); the release job sets the
real one first. Do the same, with a version that has no `-` (use `~` for a
pre-release, e.g. `1.5.0~rc.1`), in `AC_INIT` of `configure.ac` and, for the
rpm, in `Version:` of the spec, so that the tarball name and the spec match:

- deb: set the version with `dch --newversion <version> "<message>"` (or keep
  `0.0.0~manual` for a local build), then `dpkg-buildpackage -us -uc` in the
  source tree (packaging in `debian/`).
- rpm: `./autogen.sh && ./configure && make dist`, then `rpmbuild -ba` with
  `rpm/altfs.spec` and the tarball (`dnf builddep rpm/altfs.spec` installs
  the build dependencies; CRB and EPEL must be enabled).
