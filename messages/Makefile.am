##
##
##  OO_Copyright_BEGIN
##
##
##  Copyright 2010, 2020 IBM Corp. All rights reserved.
##
##  Redistribution and use in source and binary forms, with or without
##   modification, are permitted provided that the following conditions
##  are met:
##  1. Redistributions of source code must retain the above copyright
##     notice, this list of conditions and the following disclaimer.
##  2. Redistributions in binary form must reproduce the above copyright
##     notice, this list of conditions and the following disclaimer in the
##  documentation and/or other materials provided with the distribution.
##  3. Neither the name of the copyright holder nor the names of its
##     contributors may be used to endorse or promote products derived from
##     this software without specific prior written permission.
##
##  THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS ``AS IS''
##  AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
##  IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
##  ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
##  LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
##  CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
##  SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
##  INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
##  CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
##  ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
##  POSSIBILITY OF SUCH DAMAGE.
##
##
##  OO_Copyright_END
##
######################################################################################
##
## COMPONENT NAME:  IBM Linear Tape File System
##
## FILE NAME:       Makefile.osx
##
## DESCRIPTION:     Automake template for LTFS message libraries on Linux.
##
## AUTHOR:          Brian Biskeborn
##                  IBM Almaden Research Center
##                  bbiskebo@us.ibm.com
##
######################################################################################

RESOURCES = \
	libbin_mkaltfs_dat.la \
	libbin_altfsck_dat.la \
	libbin_altfsindextool_dat.la \
	libbin_altfs_dat.la \
	libkmi_simple_dat.la \
	libkmi_flatfile_dat.la \
	libtape_generic_file_dat.la \
	libtape_generic_itdtimg_dat.la \
	libtape_linux_sg_dat.la \
	libtape_iokit_dat.la \
	libtape_freebsd_cam_dat.la \
	libiosched_fcfs_dat.la \
	libiosched_unified_dat.la \
	liblc_dat.la \
	liblg_dat.la \
	libli_dat.la \
	liblb_dat.la \
	liblp_dat.la \
	liblf_dat.la \
	liblj_dat.la \
	liblx_dat.la \
	libei_dat.la \
	libed_dat.la \
	libtape_common_dat.la

.PHONY: all $(RESOURCES) clean-local
if CHK_MESSAGE
all: $(RESOURCES) ../src/ltfsmsg.h
else
all: $(RESOURCES)
endif

$(RESOURCES):
	@LIBTOOL='$(SHELL) $(abs_top_builddir)/libtool' CC='$(CC)' ./make_message_src.sh $@

if CHK_MESSAGE
../src/ltfsmsg.h: $(RESOURCES)
	./print_error_messages.py > ../src/ltfsmsg.h
endif

clean-local:
	rm -rf $(RESOURCES) */work */work_*
	rm -rf .libs
	rm -f ../src/ltfsmsg.h
	rm -f *.la *.lo *.a

# Ship the helper scripts and per-component ICU resource source directories
# in `make dist` so the rpm build (which consumes the dist tarball) has them.
EXTRA_DIST = \
	make_message_src.sh \
	print_error_messages.py \
	README \
	bin_altfs \
	bin_altfsck \
	bin_altfsindextool \
	bin_mkaltfs \
	internal_error \
	iosched_fcfs \
	iosched_unified \
	kmi_flatfile \
	kmi_simple \
	libaltfs \
	tape_common \
	tape_freebsd_cam \
	tape_generic_file \
	tape_generic_itdtimg \
	tape_iokit \
	tape_linux_sg
