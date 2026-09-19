
all:

install-data-local:
	mkdir -p "$(DESTDIR)@datadir@/altfs"
	install -m 755 $(srcdir)/altfs "$(DESTDIR)@datadir@/altfs/altfs"

uninstall-local:
	rm -f "$(DESTDIR)@datadir@/altfs/altfs"

EXTRA_DIST = altfs

clean-local:
