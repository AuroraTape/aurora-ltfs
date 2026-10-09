## How to maintain the man pages of LTFS

Man pages for LTFS is originally written by SGML (DocBook V4.1). And it is converted to man (troff) by `docbook2man`.

The pages in this directory are generated from the SGML sources in `sgml/`; edit the SGML, not the pages. When `configure` finds `docbook2man` (package `docbook-utils`, in the Dev Containers), `make` rebuilds a page whose SGML source is newer than the page; commit the regenerated page together with the SGML change. Without `docbook2man` the pages are installed as they are.

The Markdown command reference in `docs/user/reference/` is generated from the pages with `man/make-markdown.sh` (needs pandoc; the CI uses the pandoc of Ubuntu 24.04, which the Ubuntu Dev Container has). Run it after regenerating a page and commit the result. The CI regenerates both the pages and the Markdown and fails when the committed files differ.

The following link is useful to refer how to write `docbook::reference` document in SGML.

http://www.fifi.org/doc/docbook-doc/r43656.html
