%global pkgname aurora-ltfs

Name:           %{pkgname}
Version:        0.0.0
Release:        1%{?dist}
Summary:        Aurora LTFS: mount LTFS-formatted tapes as a filesystem

License:        BSD-3-Clause
URL:            https://github.com/turing-motors/aurora-ltfs
Source0:        %{name}-%{version}.tar.gz

BuildRequires:  autoconf
BuildRequires:  automake
BuildRequires:  libtool
BuildRequires:  make
BuildRequires:  gcc
BuildRequires:  pkgconfig
BuildRequires:  fuse-devel
BuildRequires:  libxml2-devel
BuildRequires:  libicu-devel
BuildRequires:  libuuid-devel
BuildRequires:  icu
BuildRequires:  diffutils
BuildRequires:  redhat-rpm-config
BuildRequires:  systemd-rpm-macros

Requires:       fuse
%{?systemd_requires}
Requires:       libaltfs%{?_isa} = %{version}-%{release}

%description
Aurora LTFS lets you mount LTFS-formatted tapes as a regular filesystem
using FUSE. This package provides the altfs FUSE daemon plus the mkaltfs,
altfsck and altfsindextool utilities, along with the tape / iosched / kmi
plugin libraries loaded at runtime.

%package -n libaltfs
Summary:        Aurora LTFS shared library

%description -n libaltfs
Shared library used by Aurora LTFS commands and plugins. This package
provides the runtime libaltfs.so.* needed to run altfs/mkaltfs/altfsck.

%package -n libaltfs-devel
Summary:        Development files for libaltfs
Requires:       libaltfs%{?_isa} = %{version}-%{release}

%description -n libaltfs-devel
Header files and pkg-config metadata for building software against
libaltfs.

%prep
%autosetup -n %{name}-%{version}

%build
# The source tarball is produced by `make dist`, so it already contains a
# generated configure script. No need to bootstrap again here.
%configure --disable-static --with-systemdsystemunitdir=%{_unitdir}
%make_build

%install
%make_install
# libtool .la files are not desired by packaging policy.
find %{buildroot} -name '*.la' -delete
# altfs.service unmounts all LTFS volumes cleanly at shutdown and is inert
# otherwise, so enable it by default through a preset.
install -d %{buildroot}%{_presetdir}
echo 'enable altfs.service' > %{buildroot}%{_presetdir}/90-altfs.preset

%files
%license LICENSE
%doc README.md
%{_bindir}/altfs
%{_bindir}/mkaltfs
%{_bindir}/altfsck
%{_bindir}/altfsindextool
%{_bindir}/altfs_ordered_copy
%dir %{_libdir}/altfs
%{_libdir}/altfs/*.so
%{_datadir}/altfs/
%{_unitdir}/altfs.service
%{_presetdir}/90-altfs.preset
%config(noreplace) %{_sysconfdir}/rsyslog.d/30-altfs.conf
%config(noreplace) %{_sysconfdir}/logrotate.d/altfs
%{_mandir}/man1/altfs_ordered_copy.1*
%{_mandir}/man8/altfs.8*
%{_mandir}/man8/mkaltfs.8*
%{_mandir}/man8/altfsck.8*
%{_mandir}/man8/altfsindextool.8*
%config(noreplace) %{_sysconfdir}/altfs.conf
%config(noreplace) %{_sysconfdir}/altfs.conf.local

%files -n libaltfs
%license LICENSE
%{_libdir}/libaltfs.so.*

%files -n libaltfs-devel
%{_includedir}/%{pkgname}/
%{_libdir}/libaltfs.so
%{_libdir}/pkgconfig/altfs.pc

%post
%systemd_post altfs.service
# The unit only does work when it is stopped at shutdown, so it has to be
# active. The preset enables it; start it on first install as well.
if [ $1 -eq 1 ] && [ -d /run/systemd/system ]; then
    systemctl start altfs.service >/dev/null 2>&1 || :
    # Make a running rsyslog pick up rsyslog.d/30-altfs.conf (rsyslog has no
    # reload, a config change needs a restart).
    systemctl try-restart rsyslog.service >/dev/null 2>&1 || :
fi

%triggerun -- %{name} < 1.0.1
# Upgrade from a release that did not ship altfs.service (1.0.0): the
# systemd_post macro applies the preset only on a first install, so the
# upgrade would leave the unit disabled. Apply the preset and start the
# unit once, when the old package goes away. Later upgrades keep the
# administrator's choice. 1.0.0 had no rsyslog rule either.
systemctl --no-reload preset altfs.service >/dev/null 2>&1 || :
if [ -d /run/systemd/system ]; then
    systemctl start altfs.service >/dev/null 2>&1 || :
    systemctl try-restart rsyslog.service >/dev/null 2>&1 || :
fi

%preun
# Does nothing on upgrade: the unit stays active and mounted volumes are
# left alone. On removal it stops the unit, which unmounts all volumes
# before the binaries disappear.
%systemd_preun altfs.service

%postun
# Not the _with_restart variant: restarting runs "stop", which would
# unmount the user's tapes in the middle of a package upgrade.
%systemd_postun altfs.service
# On removal the rsyslog rule is gone (unless it was modified and kept as
# .rpmsave); let a running rsyslog drop it.
if [ $1 -eq 0 ] && [ -d /run/systemd/system ]; then
    systemctl try-restart rsyslog.service >/dev/null 2>&1 || :
fi

%post -n libaltfs -p /sbin/ldconfig
%postun -n libaltfs -p /sbin/ldconfig

%changelog
* Sat May 16 2026 Atsushi Abe <atsushi.abe@turing-motors.com> - 0.0.0-1
- Placeholder entry; release CI overwrites Version and prepends a real entry.
