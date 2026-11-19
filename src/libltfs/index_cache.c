/*
**
**  AA_Copyright_BEGIN
**
**
**  Copyright 2026,      Aurora Tape Project contributors. All rights reserved.
**
**  Redistribution and use in source and binary forms, with or without
**   modification, are permitted provided that the following conditions
**  are met:
**  1. Redistributions of source code must retain the above copyright
**     notice, this list of conditions and the following disclaimer.
**  2. Redistributions in binary form must reproduce the above copyright
**     notice, this list of conditions and the following disclaimer in the
**  documentation and/or other materials provided with the distribution.
**  3. Neither the name of the copyright holder nor the names of its
**     contributors may be used to endorse or promote products derived from
**     this software without specific prior written permission.
**
**  THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS ``AS IS''
**  AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
**  IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
**  ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
**  LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
**  CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
**  SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
**  INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
**  CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
**  ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
**  POSSIBILITY OF SUCH DAMAGE.
**
**
**  AA_Copyright_END
**
*************************************************************************************
**
** FILE NAME:       index_cache.c
**
** DESCRIPTION:     Index cache: a copy of the last index on disk that a volume can be
**                  mounted from.
**
**                  The copy is the file libaltfs already writes next to the index on tape
**                  (vol->index_cache_path_w). Two extended attributes of that file say
**                  what it is worth:
**
**                    user.altfs.volume_uuid   UUID of the volume the index belongs to
**                    user.altfs.vcr           Volume Change Reference of the cartridge right
**                                             after the index was written to the tape
**
**                  A mount reads the index from the file instead of the tape when the UUID
**                  and the VCR are those of the loaded cartridge: nothing has been written
**                  to it since the copy was made.
**
*************************************************************************************
*/

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <unistd.h>
#include <inttypes.h>
#include <sys/types.h>
#include <sys/stat.h>

#include "ltfs.h"
#include "ltfs_internal.h"
#include "ltfs_error.h"
#include "ltfslogging.h"
#include "tape.h"
#include "xml_libltfs.h"
#include "index_cache.h"

#define EA_UUID       "volume_uuid"
#define EA_VCR        "vcr"

/*
 * Extended attributes of a file of the host, in the user namespace
 */
#if defined(__linux__)

#include <sys/xattr.h>
#define EA_NAME(n) "user.altfs." n

static int ea_set(const char *path, const char *name, const char *value)
{
	return setxattr(path, name, value, strlen(value), 0) ? -errno : 0;
}

static int ea_get(const char *path, const char *name, char *buf, size_t size)
{
	ssize_t len = getxattr(path, name, buf, size - 1);

	if (len < 0)
		return -errno;
	buf[len] = '\0';
	return 0;
}

static void ea_remove(const char *path, const char *name)
{
	removexattr(path, name);
}

#elif defined(__APPLE__)

#include <sys/xattr.h>
#define EA_NAME(n) "user.altfs." n

static int ea_set(const char *path, const char *name, const char *value)
{
	return setxattr(path, name, value, strlen(value), 0, 0) ? -errno : 0;
}

static int ea_get(const char *path, const char *name, char *buf, size_t size)
{
	ssize_t len = getxattr(path, name, buf, size - 1, 0, 0);

	if (len < 0)
		return -errno;
	buf[len] = '\0';
	return 0;
}

static void ea_remove(const char *path, const char *name)
{
	removexattr(path, name, 0);
}

#elif defined(__FreeBSD__) || defined(__NetBSD__)

#include <sys/extattr.h>
#define EA_NAME(n) "altfs." n

static int ea_set(const char *path, const char *name, const char *value)
{
	return extattr_set_file(path, EXTATTR_NAMESPACE_USER, name, value, strlen(value)) < 0 ? -errno : 0;
}

static int ea_get(const char *path, const char *name, char *buf, size_t size)
{
	ssize_t len = extattr_get_file(path, EXTATTR_NAMESPACE_USER, name, buf, size - 1);

	if (len < 0)
		return -errno;
	buf[len] = '\0';
	return 0;
}

static void ea_remove(const char *path, const char *name)
{
	extattr_delete_file(path, EXTATTR_NAMESPACE_USER, name);
}

#else

/* No extended attributes: the copy is written but never trusted for a mount */
#define EA_NAME(n) n

static int ea_set(const char *path, const char *name, const char *value)
{
	(void) path; (void) name; (void) value;
	return -ENOTSUP;
}

static int ea_get(const char *path, const char *name, char *buf, size_t size)
{
	(void) path; (void) name; (void) buf; (void) size;
	return -ENOTSUP;
}

static void ea_remove(const char *path, const char *name)
{
	(void) path; (void) name;
}

#endif

/**
 * Turn the index cache on: the directory the copies of the indexes are kept in.
 * Call before ltfs_mount(). The file of a volume is <dir>/<BARCODE>.index.xml, or
 * <dir>/<volume UUID>.index.xml for a volume without a barcode.
 */
int ltfs_set_index_cache_dir(const char *dir, struct ltfs_volume *vol)
{
	CHECK_ARG_NULL(dir, -LTFS_NULL_ARG);
	CHECK_ARG_NULL(vol, -LTFS_NULL_ARG);

	if (vol->index_cache_dir)
		free(vol->index_cache_dir);
	vol->index_cache_dir = strdup(dir);
	if (! vol->index_cache_dir) {
		ltfsmsg(ALC0002E, "ltfs_set_index_cache_dir");
		return -LTFS_NO_MEMORY;
	}
	return 0;
}

/**
 * Is the file vol->index_cache_path_w the index cache of this volume (and not a plain
 * capture of the indexes)?
 */
bool index_cache_enabled(struct ltfs_volume *vol)
{
	return vol->index_cache_dir && vol->index_cache_path_w;
}

/**
 * Name the cache file of the loaded volume. Called by ltfs_mount() once the labels are read.
 */
int index_cache_setup(struct ltfs_volume *vol)
{
	int ret;

	if (! vol->index_cache_dir)
		return 0;

	if (vol->index_cache_path_w) {
		free(vol->index_cache_path_w);
		vol->index_cache_path_w = NULL;
	}

	ret = asprintf(&vol->index_cache_path_w, "%s/%s.index.xml", vol->index_cache_dir,
				   HAVE_BARCODE(vol) ? vol->label->barcode : vol->label->vol_uuid);
	if (ret < 0) {
		vol->index_cache_path_w = NULL;
		ltfsmsg(ALC0002E, "index_cache_setup");
		return -LTFS_NO_MEMORY;
	}

	return 0;
}

/**
 * Read the index of the volume from its cache file, if the file is the index the tape ends with.
 * Called by ltfs_mount() where it would read the index of the index partition, with the
 * coherency data of the cartridge already checked against the VCR.
 * @param vcr current Volume Change Reference of the cartridge
 * @param vol LTFS volume; vol->index is replaced
 * @return 0 when the index was read from the file, a negative value when the tape has to be read
 */
int index_cache_mount(uint64_t vcr, struct ltfs_volume *vol)
{
	const char *path = vol->index_cache_path_w;
	char value[128];
	struct stat st;
	int ret;

	if (! index_cache_enabled(vol) || stat(path, &st) || st.st_size == 0)
		return -LTFS_CACHE_IO;

	if (vcr == 0 || vcr == UINT64_MAX) {
		ltfsmsg(ALB0290I, path, "the cartridge has no usable volume change reference");
		return -LTFS_CACHE_IO;
	}
	if (ea_get(path, EA_NAME(EA_UUID), value, sizeof(value)) < 0 ||
		strcmp(value, vol->label->vol_uuid)) {
		ltfsmsg(ALB0290I, path, "it does not belong to this volume");
		return -LTFS_CACHE_IO;
	}
	if (ea_get(path, EA_NAME(EA_VCR), value, sizeof(value)) < 0 ||
		strtoull(value, NULL, 10) != vcr) {
		ltfsmsg(ALB0290I, path, "the cartridge was written after the file");
		return -LTFS_CACHE_IO;
	}

	ret = ltfs_read_indexfile((char *) path, false, vol);
	if (ret < 0) {
		ltfsmsg(ALB0290I, path, "the file cannot be parsed");
		return ret;
	}

	/* The file must be the index the cartridge memory points at */
	if (strncmp(vol->index->vol_uuid, vol->label->vol_uuid, 36) ||
		vol->index->generation != vol->ip_coh.count ||
		vol->index->selfptr.partition != vol->label->partid_ip ||
		vol->index->selfptr.block != vol->ip_coh.set_id) {
		ltfsmsg(ALB0290I, path, "it is not the index the cartridge ends with");
		return -LTFS_INDEX_INVALID;
	}

	ltfsmsg(ALB0289I, path, (unsigned long long) vol->index->generation, (unsigned long long) vcr);
	return 0;
}

/**
 * The index was read from the tape, which ends with it: make the file a copy of it, so that
 * the next mount can use the file even if no index is written in this one.
 * Called by ltfs_mount() right after the index of the index partition was read.
 * @param vcr current Volume Change Reference of the cartridge
 * @param vol LTFS volume
 */
void index_cache_refresh(uint64_t vcr, struct ltfs_volume *vol)
{
	const char *path = vol->index_cache_path_w;
	char value[32], *tmp = NULL;
	int ret;

	if (! index_cache_enabled(vol) || vcr == 0 || vcr == UINT64_MAX || ! vol->index->creator)
		return;

	if (asprintf(&tmp, "%s.tmp", path) < 0)
		return;

	ret = xml_schema_to_file(tmp, vol->index->creator, NULL, vol->index);
	if (ret == 0) {
		snprintf(value, sizeof(value), "%" PRIu64, vcr);
		ret = ea_set(tmp, EA_NAME(EA_UUID), vol->label->vol_uuid);
		if (ret == 0)
			ret = ea_set(tmp, EA_NAME(EA_VCR), value);
		if (ret < 0)
			ltfsmsg(ALB0291W, path, ret);
		else if (chmod(tmp, S_IRUSR | S_IWUSR | S_IRGRP | S_IWGRP) || rename(tmp, path))
			ret = -errno;
	}
	if (ret < 0)
		unlink(tmp);
	free(tmp);
}

/**
 * The file is about to be rewritten, or the tape to move on without it: it is no longer
 * the index the tape ends with.
 */
void index_cache_invalidate(struct ltfs_volume *vol)
{
	if (index_cache_enabled(vol))
		ea_remove(vol->index_cache_path_w, EA_NAME(EA_VCR));
}

/**
 * A full index was written to the tape and to the file: say which state of the cartridge
 * the file is the index of.
 */
void index_cache_written(struct ltfs_volume *vol)
{
	const char *path = vol->index_cache_path_w;
	char value[32];
	uint64_t vcr = 0;
	int ret;

	if (! index_cache_enabled(vol))
		return;

	ret = tape_get_volume_change_reference(vol->device, &vcr);
	if (ret < 0 || vcr == 0 || vcr == UINT64_MAX)
		return; /* stays without a VCR: never used for a mount */

	snprintf(value, sizeof(value), "%" PRIu64, vcr);
	ret = ea_set(path, EA_NAME(EA_UUID), vol->label->vol_uuid);
	if (ret == 0)
		ret = ea_set(path, EA_NAME(EA_VCR), value);
	if (ret < 0) {
		ea_remove(path, EA_NAME(EA_VCR));
		ltfsmsg(ALB0291W, path, ret);
	}
}
