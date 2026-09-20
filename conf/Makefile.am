# altfs.conf is generated with the directories of this build (libdir,
# sysconfdir), so it must not be distributed: a copy made by "make dist"
# carries the paths of the tree that ran "make dist", is newer than
# altfs.conf.in, and would be installed as is by the build from the tarball
# (the 1.0.0 rpm shipped /usr/local paths that way).
sysconf_DATA = altfs.conf

PLAT_OPT =

if PLATFORM_LINUX
PLAT_OPT += plugin tape sg __LIBDIR__/altfs/libtape-sg.so
endif

if PLATFORM_MAC
PLAT_OPT += plugin tape iokit __LIBDIR__/altfs/libtape-iokit.so
endif

if PLATFORM_FREEBSD
PLAT_OPT += plugin tape cam __LIBDIR__/altfs/libtape-cam.so
endif

if PLATFORM_NETBSD
PLAT_OPT += plugin tape scsipi-ibmtape __LIBDIR__/altfs/libtape-scsipi-ibmtape.so
endif

altfs.conf: altfs.conf.in Makefile
	${SED} -e "s!__PLATFORM_DRIVERS__!${PLAT_OPT}!" $(srcdir)/altfs.conf.in >altfs.conf.in1
	${SED} -e "s!__LIBDIR__!@libdir@!" altfs.conf.in1 >altfs.conf
	rm altfs.conf.in1
	mv altfs.conf altfs.conf.tmp
	${SED} -e "s!__DEFAULT_TAPE__!$(DEFAULT_TAPE)!" altfs.conf.tmp >altfs.conf
	mv altfs.conf altfs.conf.tmp
	${SED} -e "s!__DEFAULT_IOSCHED__!$(DEFAULT_IOSCHED)!" altfs.conf.tmp >altfs.conf
	mv altfs.conf altfs.conf.tmp
	${SED} -e "s!__DEFAULT_KMI__!$(DEFAULT_KMI)!" altfs.conf.tmp >altfs.conf
	mv altfs.conf altfs.conf.tmp
	${SED} -e "s!__CONFDIR__!@sysconfdir@!" altfs.conf.tmp >altfs.conf
	rm altfs.conf.tmp

# systemd unit that unmounts all volumes cleanly at shutdown. It calls the
# helper script installed from init.d/ into $(datadir)/altfs.
if PLATFORM_LINUX
systemdsystemunit_DATA = altfs.service
endif

altfs.service: altfs.service.in Makefile
	${SED} -e 's!@datadir[@]!$(datadir)!g' $(srcdir)/altfs.service.in >altfs.service.tmp
	mv altfs.service.tmp altfs.service

# rsyslog rule and logrotate config for /var/log/altfs.log. They take
# effect when sysconfdir is /etc, as in the deb / rpm packages. The 30-
# prefix of the rsyslog file is significant, see the comment inside it.
if PLATFORM_LINUX
rsyslogdir = $(sysconfdir)/rsyslog.d
rsyslog_DATA = 30-altfs.conf
endif

install-data-local:
	mkdir -p "$(DESTDIR)$(sysconfdir)"
	if [ ! -f "$(DESTDIR)$(sysconfdir)/altfs.conf.local" ]; then \
		cp altfs.conf.local "$(DESTDIR)$(sysconfdir)/altfs.conf.local"; \
	fi
if PLATFORM_LINUX
	mkdir -p "$(DESTDIR)$(sysconfdir)/logrotate.d"
	$(INSTALL_DATA) $(srcdir)/altfs.logrotate "$(DESTDIR)$(sysconfdir)/logrotate.d/altfs"
endif

uninstall-local:
if PLATFORM_LINUX
	rm -f "$(DESTDIR)$(sysconfdir)/logrotate.d/altfs"
endif

clean-local:
	rm -f altfs.conf altfs.service altfs.service.tmp

# Source / config files needed at build or install time. altfs.conf
# itself is generated from altfs.conf.in by the rule above, so the
# template plus all sidecar config files must be in `make dist`.
EXTRA_DIST = \
	altfs.conf.in \
	altfs.conf.local \
	altfs.service.in \
	30-altfs.conf \
	altfs.logrotate \
	README.md
