#
#
#  OO_Copyright_BEGIN
#
#
#  Copyright 2010, 2020 IBM Corp. All rights reserved.
#
#  Redistribution and use in source and binary forms, with or without
#   modification, are permitted provided that the following conditions
#  are met:
#  1. Redistributions of source code must retain the above copyright
#     notice, this list of conditions and the following disclaimer.
#  2. Redistributions in binary form must reproduce the above copyright
#     notice, this list of conditions and the following disclaimer in the
#  documentation and/or other materials provided with the distribution.
#  3. Neither the name of the copyright holder nor the names of its
#     contributors may be used to endorse or promote products derived from
#     this software without specific prior written permission.
#
#  THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS ``AS IS''
#  AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
#  IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
#  ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
#  LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
#  CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
#  SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
#  INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
#  CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
#  ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
#  POSSIBILITY OF SUCH DAMAGE.
#
#
#  OO_Copyright_END
#

ACLOCAL_AMFLAGS = -I m4

nobase_pkginclude_HEADERS = config.h

SUBDIRS = messages src conf init.d man

# Packaging helpers, plus headers that exist in the tree but are not
# registered in any `_HEADERS` variable, so `make dist` would otherwise
# omit them. These are required by the build on every platform (some
# are platform-specific arch shims but are still #include'd
# unconditionally from sources).
EXTRA_DIST = \
	README.md \
	LICENSE \
	build-aux/git-version.sh \
	rpm/altfs.spec \
	src/cmd/altfs/ltfs_fuse.h \
	src/iosched/cache_manager.h \
	src/kmi/key_format_ltfs.h \
	src/libltfs/inc_journal.h \
	src/libltfs/arch/freebsd/errno.h \
	src/libltfs/arch/freebsd/freebsd_locking_old.h \
	src/libltfs/arch/freebsd/xattr.h \
	src/libltfs/arch/osx/osx_string.h \
	src/libltfs/arch/osx/osx_string.c \
	src/tape_drivers/crc32c_crc.h \
	src/tape_drivers/crc32c_crc.c \
	src/tape_drivers/reed_solomon_crc.c \
	src/tape_drivers/vendor_compat.c \
	src/tape_drivers/ibm_tape.c \
	src/tape_drivers/hp_tape.c \
	src/tape_drivers/quantum_tape.c \
	src/tape_drivers/open_factor.c \
	src/tape_drivers/hp_tape.h \
	src/tape_drivers/open_factor.h \
	src/tape_drivers/quantum_tape.h \
	src/tape_drivers/reed_solomon_crc.h \
	src/tape_drivers/vendor_compat.h \
	src/tape_drivers/freebsd/cam/IBM_tape.h \
	src/tape_drivers/freebsd/cam/cam_cmn.h \
	src/tape_drivers/generic/file/filedebug_conf_tc.h \
	src/tape_drivers/linux/sg/sg_scsi_tape.h \
	src/tape_drivers/linux/sg/sg_tape.h \
	src/tape_drivers/netbsd/scsipi-ibmtape/scsipi_ibmtape.h \
	src/tape_drivers/netbsd/scsipi-ibmtape/scsipi_scsi_tape.h \
	src/tape_drivers/osx/iokit/iokit_scsi.h \
	src/tape_drivers/osx/iokit/iokit_service.h \
	src/tape_drivers/osx/iokit/iokit_tape.h

install-data-local: altfs.pc
	if [ ! -d $(DESTDIR)$(libdir)/pkgconfig ]; then \
		mkdir -p $(DESTDIR)$(libdir)/pkgconfig; \
	fi
	cp ./altfs.pc $(DESTDIR)$(libdir)/pkgconfig/

clean-local:
	rm -f altfs.pc

