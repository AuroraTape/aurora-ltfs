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

bin_PROGRAMS = mkaltfs altfsck altfsindextool

nobase_bin_SCRIPTS = altfs_ordered_copy

noinst_HEADERS =

mkaltfs_SOURCES = mkltfs.c
mkaltfs_DEPENDENCIES = ../libltfs/libaltfs.la ../../messages/libbin_mkaltfs_dat.a
mkaltfs_LDADD = ../libltfs/libaltfs.la
mkaltfs_LDFLAGS = @AM_LDFLAGS@ ../../messages/libbin_mkaltfs_dat.a
mkaltfs_CPPFLAGS = @AM_CPPFLAGS@ -I .. -fPIC

altfsck_SOURCES = ltfsck.c
altfsck_DEPENDENCIES = ../libltfs/libaltfs.la ../../messages/libbin_altfsck_dat.a
altfsck_LDADD = ../libltfs/libaltfs.la
altfsck_LDFLAGS = @AM_LDFLAGS@ ../../messages/libbin_altfsck_dat.a
altfsck_CPPFLAGS = @AM_CPPFLAGS@ -I .. -fPIC

altfsindextool_SOURCES = ltfsindextool.c
altfsindextool_DEPENDENCIES = ../libltfs/libaltfs.la ../../messages/libbin_altfsindextool_dat.a ../../messages/libbin_mkaltfs_dat.a
altfsindextool_LDADD = ../libltfs/libaltfs.la
altfsindextool_LDFLAGS = @AM_LDFLAGS@ -L../../messages -lbin_altfsindextool_dat
altfsindextool_CPPFLAGS = @AM_CPPFLAGS@ -I .. -fPIC
