MAN8 = mkaltfs.8 altfsck.8 altfs.8 altfsindextool.8
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

altfs_ordered_copy.1: $(srcdir)/sgml/altfs_ordered_copy.sgml
	$(DOCBOOK2MAN) $< && rm -f manpage.*
endif

EXTRA_DIST = $(MAN8) $(MAN1) sgml
