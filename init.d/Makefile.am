
all:

install-data-local:
	if [ ! -d "$(DESTDIR)@datadir@/altfs" ]; then \
		mkdir -p "$(DESTDIR)@datadir@/altfs"; \
	fi ;\
	if [ ! -f "$(DESTDIR)@datadir@/altfs/altfs" ]; then \
		install -m 755 altfs "$(DESTDIR)@datadir@/altfs/altfs"; \
	fi

clean-local:
