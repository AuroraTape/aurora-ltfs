MAN8 = mkaltfs.8 altfsck.8 altfs.8 altfsindextool.8
# altfsctl is installed on Linux (systemd) only
if PLATFORM_LINUX
MAN8 += altfsctl.8
endif
MAN1 = altfs_ordered_copy.1

man_MANS = $(MAN8) $(MAN1)

if HAVE_DOCBOOK2MAN
mkaltfs.8: $(srcdir)/sgml/mkaltfs.sgml
	$(DOCBOOK2MAN) $< && rm -f manpage.*

altfsck.8: $(srcdir)/sgml/altfsck.sgml
	$(DOCBOOK2MAN) $< && rm -f manpage.*

altfs.8: $(srcdir)/sgml/altfs.sgml
	$(DOCBOOK2MAN) $< && rm -f manpage.*

altfsindextool.8: $(srcdir)/sgml/altfsindextool.sgml
	$(DOCBOOK2MAN) $< && rm -f manpage.*

altfsctl.8: $(srcdir)/sgml/altfsctl.sgml
	$(DOCBOOK2MAN) $< && rm -f manpage.*

altfs_ordered_copy.1: $(srcdir)/sgml/altfs_ordered_copy.sgml
	$(DOCBOOK2MAN) $< && rm -f manpage.*
endif

# altfsctl.8 is listed on its own so that "make dist" on other platforms has it too
EXTRA_DIST = $(MAN8) $(MAN1) altfsctl.8 sgml
