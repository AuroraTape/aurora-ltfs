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

Requires:       fuse
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
./autogen.sh
%configure
%make_build

%install
%make_install
# libtool .la files are not desired by packaging policy.
find %{buildroot} -name '*.la' -delete

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

%post -n libaltfs -p /sbin/ldconfig
%postun -n libaltfs -p /sbin/ldconfig

%changelog
* Sat May 16 2026 Atsushi Abe <atsushi.abe@turing-motors.com> - 0.0.0-1
- Placeholder entry; release CI overwrites Version and prepends a real entry.
