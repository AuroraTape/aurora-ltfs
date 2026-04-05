dist_sysconf_DATA = altfs.conf

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

altfs.conf: altfs.conf.in
	${SED} -e "s!__PLATFORM_DRIVERS__!${PLAT_OPT}!" altfs.conf.in >altfs.conf.in1
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

install-data-local:
	mkdir -p "$(DESTDIR)$(sysconfdir)"
	if [ ! -f "$(DESTDIR)$(sysconfdir)/altfs.conf.local" ]; then \
		cp altfs.conf.local "$(DESTDIR)$(sysconfdir)/altfs.conf.local"; \
	fi

clean-local:
	rm -f altfs.conf
