man_MANS = mkaltfs.8 altfsck.8 altfs.8 altfs_ordered_copy.1 altfsindextool.8

man-clean:
	rm $(man_MANS)

man-rebuild:
	docbook2man sgml/mkaltfs.sgml
	docbook2man sgml/altfsck.sgml
	docbook2man sgml/altfs.sgml
	docbook2man sgml/altfs_ordered_copy.sgml
	docbook2man sgml/altfsindextool.sgml
	rm -f manpage.*
