/*
**
**  OO_Copyright_BEGIN
**
**
**  Copyright 2010, 2020 IBM Corp. All rights reserved.
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
**  OO_Copyright_END
*/

/*************************************************************************************
 ** FILE NAME:       ltfslogging.c
 **
 ** DESCRIPTION:     Routines for logging via syslog and stderr. (LTFS messages)
 **
 ** AUTHORS:         Brian Biskeborn
 **                  IBM Almaden Research Center
 **                  bbiskebo@us.ibm.com
 **
 *************************************************************************************
 */

#ifdef mingw_PLATFORM
#include "arch/win/win_util.h"
#endif
#include <stdlib.h>
#include <stdarg.h>
#include <string.h>
#include <errno.h>
#ifndef mingw_PLATFORM
#include <syslog.h>
#endif

#ifdef __APPLE_MAKEFILE__
#include <ICU/unicode/ucnv.h>
#include <ICU/unicode/ures.h>
#include <ICU/unicode/utypes.h>
#include <ICU/unicode/udata.h>
#include <ICU/unicode/uclean.h>
#else
#include <unicode/ucnv.h>
#include <unicode/ures.h>
#include <unicode/utypes.h>
#include <unicode/udata.h>
#include <unicode/putil.h>
#include <unicode/uclean.h>
#endif
#ifdef mingw_PLATFORM
#include <sys/types.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include "arch/win/winlog.h"
#else
#include <dlfcn.h>
#include <sys/types.h>
#endif

#include "libltfs/ltfslogging.h"
#include "libltfs/ltfs_thread.h"
#include "libltfs/ltfs_locking.h"
#include "libltfs/ltfs_error.h"
#include "queue.h"

/* Some hard-coded message bits. */
#define MSG_PREFIX_POSIX_TID   "%016llx LTFS%s "
#define MSG_PREFIX_TID         "%lx LTFS%s "
#define MSG_PREFIX             "LTFS%s "
#define MSG_FALLBACK           "(could not generate message)"

#define OUTPUT_BUF_SIZE 4096  /* Output buffer size, should be big enough to hold any message. */

struct plugin_bundle {
	TAILQ_ENTRY(plugin_bundle) list;
	char prefix[4];                    /**< 3-char message prefix (e.g. "ALG") + NUL */
	UResourceBundle *bundle_root;      /**< Root resource bundle for this plugin */
	UResourceBundle *bundle_messages;  /**< Resource bundle containing this plugin's messages */
};

/* Syslog levels corresponding to the LTFS logging levels defined in libltfs/ltfslogging.h. */
static int syslog_levels[] = {
	LOG_ERR,      /* LTFS_ERR    */
	LOG_WARNING,  /* LTFS_WARN   */
	LOG_INFO,     /* LTFS_INFO   */
	LOG_DEBUG,    /* LTFS_DEBUG  */
	LOG_DEBUG,    /* LTFS_DEBUG1 */
	LOG_DEBUG,    /* LTFS_DEBUG2 */
	LOG_DEBUG,    /* LTFS_DEBUG3 */
	LOG_DEBUG,    /* LTFS_TRACE  */
};

U_CFUNC char lc_dat[]; /* U_CFUNC is an ICU synonym for extern. */
U_CFUNC char lg_dat[];
U_CFUNC char li_dat[];
U_CFUNC char lb_dat[];
U_CFUNC char lp_dat[];
U_CFUNC char lf_dat[];
U_CFUNC char lj_dat[];
U_CFUNC char lx_dat[];
U_CFUNC char ei_dat[];
U_CFUNC char ed_dat[];
U_CFUNC char tape_common_dat[];

static bool libaltfs_dat_init = false;
int ltfs_log_level = LTFS_INFO;
int ltfs_syslog_level = LTFS_INFO;
bool ltfs_print_thread_id = false;
static bool ltfs_use_syslog = false;

/* Resource bundles, used for quick indexing into message arrays. */
static UResourceBundle *bundle_fallback;
static TAILQ_HEAD(message_struct, plugin_bundle) plugin_bundles;

/* Static output buffer: needed to avoid allocating memory on error. */
static ltfs_mutex_t output_lock;
static char output_buf[OUTPUT_BUF_SIZE];
static char msg_buf[OUTPUT_BUF_SIZE * 2];
static UConverter *output_conv = NULL;

#ifdef mingw_PLATFORM
static int _open_message_file(char *bundle_name, void **bundle_data);
#endif
int ltfsprintf_init(int log_level, bool use_syslog, bool print_thread_id)
{
	int ret;
	UErrorCode err = U_ZERO_ERROR;
	struct plugin_bundle *pl;

	/* Open converter for generating output in the system locale. */
	ret = ltfs_mutex_init(&output_lock);
	if (ret > 0) {
		fprintf(stderr, "ALC0003E Could not initialize mutex (%d)\n", ret);
		return -ret;
	}
	output_conv = ucnv_open(NULL, &err);
	if (U_FAILURE(err)) {
		fprintf(stderr, "ALG0002E Could not open output converter (ucnv_open: %d)\n", err);
		output_conv = NULL;
		ltfsprintf_finish();
		return -1;
	}

	/* Initialize output lock and plugin list */
	TAILQ_INIT(&plugin_bundles);
#ifdef mingw_PLATFORM
	u_setDataDirectory(LTFS_RB_DIR);
#endif

	/* Load libaltfs sub-component message bundles.
	 * Load lg first because it contains fallback_messages. */
	{
		struct { const char *name; void *data; } libaltfs_bundles[] = {
			{ "lg", lg_dat },
			{ "lc", lc_dat },
			{ "li", li_dat },
			{ "lb", lb_dat },
			{ "lp", lp_dat },
			{ "lf", lf_dat },
			{ "lj", lj_dat },
			{ "lx", lx_dat },
		};
		size_t nbundles = sizeof(libaltfs_bundles) / sizeof(libaltfs_bundles[0]);
		size_t bi;
		for (bi = 0; bi < nbundles; bi++) {
			ret = ltfsprintf_load_plugin(libaltfs_bundles[bi].name,
				libaltfs_bundles[bi].data, (void **)&pl);
			if (ret < 0) {
				fprintf(stderr, "ALG0023E Cannot load messages for libltfs/%s (%d)\n",
					libaltfs_bundles[bi].name, ret);
				ltfsprintf_finish();
				return ret;
			}
			/* Load fallback message set from the first bundle (lg) */
			if (bi == 0) {
				bundle_fallback = ures_getByKey(pl->bundle_root, "fallback_messages", NULL, &err);
				if (U_FAILURE(err)) {
					fprintf(stderr, "ALG0001E Could not load resource \"fallback_messages\" (ures_getByKey: %d)\n", err);
					bundle_fallback = NULL;
					ltfsprintf_finish();
					return -1;
				}
			}
		}
	}

	/* Load internal_error sub-component message bundles */
	ret = ltfsprintf_load_plugin("ei", ei_dat, (void **)&pl);
	if (ret < 0) {
		fprintf(stderr, "ALG0023E Cannot load messages for internal_error/ei (%d)\n", ret);
		ltfsprintf_finish();
		return ret;
	}
	ret = ltfsprintf_load_plugin("ed", ed_dat, (void **)&pl);
	if (ret < 0) {
		fprintf(stderr, "ALG0023E Cannot load messages for internal_error/ed (%d)\n", ret);
		ltfsprintf_finish();
		return ret;
	}

	/* Load the tape_common message bundle */
	ret = ltfsprintf_load_plugin("tape_common", tape_common_dat, (void **)&pl);
	if (ret < 0) {
		fprintf(stderr, "ALG0023E Cannot load messages for tape backend common messages (%d)\n", ret);
		ltfsprintf_finish();
		return ret;
	}

	ltfs_log_level = log_level;
	ltfs_use_syslog = use_syslog;
	ltfs_print_thread_id = print_thread_id;
	libaltfs_dat_init = true;

	return 0;
}

/* Shut down the logging and error reporting framework. */
void ltfsprintf_finish()
{

	libaltfs_dat_init = false;

	if (bundle_fallback) {
		ures_close(bundle_fallback);
		bundle_fallback = NULL;
	}
	while (1) {
		if (! TAILQ_EMPTY(&plugin_bundles))
			ltfsprintf_unload_plugin(TAILQ_LAST(&plugin_bundles, message_struct));
		else
			break;
	}
	if (output_conv) {
		ucnv_close(output_conv);
		output_conv = NULL;
	}

	ltfs_mutex_destroy(&output_lock);
	u_cleanup();
}

/* Update ltfs_log_level */
int ltfsprintf_set_log_level(int log_level)
{
	if (log_level < LTFS_ERR) {
		fprintf(stderr, "ALG0025W Unknown log level (%d), forced the level to (%d)\n", log_level, LTFS_ERR);
		log_level = LTFS_ERR;
	}
	else if (log_level > LTFS_TRACE) {
		fprintf(stderr, "ALG0025W Unknown log level (%d), forced the level to (%d)\n", log_level, LTFS_TRACE);
		log_level = LTFS_TRACE;
	}
	else {
		ltfs_log_level = log_level;
	}
	return 0;
}


int ltfsprintf_load_plugin(const char *bundle_name, void *bundle_data, void **messages)
{
	UErrorCode err = U_ZERO_ERROR;
	struct plugin_bundle *pl;

	CHECK_ARG_NULL(bundle_name, -LTFS_NULL_ARG);
	CHECK_ARG_NULL(messages, -LTFS_NULL_ARG);

#ifndef mingw_PLATFORM
	udata_setAppData(bundle_name, bundle_data, &err);
	if (U_FAILURE(err)) {
		if (libaltfs_dat_init)
			ltfsmsg(ALG0022E, err);
		else
			fprintf(stderr, "ALG0022E Cannot load messages: failed to register message data (%d)\n", err);
		return -1;
	}
#endif

	pl = calloc(1, sizeof(struct plugin_bundle));
	if (! pl) {
		if (libaltfs_dat_init)
			ltfsmsg(ALC0002E, __FUNCTION__);
		else
			fprintf(stderr, "ALC0002E Memory allocation failed (%s)\n", __FUNCTION__);
		return -LTFS_NO_MEMORY;
	}

	/* Load messages table */
	pl->bundle_root = ures_open(bundle_name, NULL, &err);
	if (U_FAILURE(err)) {
		if (libaltfs_dat_init)
			ltfsmsg(ALG0021E, err);
		else
			fprintf(stderr, "ALG0021E Cannot load messages: failed to open resource bundle (%d)\n", err);
		free(pl);
		return -1;
	}
	pl->bundle_messages = ures_getByKey(pl->bundle_root, "messages", NULL, &err);
	if (U_FAILURE(err)) {
		if (libaltfs_dat_init)
			ltfsmsg(ALG0019E, err);
		else
			fprintf(stderr, "ALG0019E Cannot load messages: failed to get message table (%d)\n", err);
		ures_close(pl->bundle_root);
		free(pl);
		return -1;
	}

	/* Read the prefix string for this component (e.g. "ALG"). */
	{
		int32_t prefix_len = 0;
		const UChar *prefix_uc;
		prefix_uc = ures_getStringByKey(pl->bundle_messages, "prefix", &prefix_len, &err);
		if (U_FAILURE(err) || prefix_len < 2 || prefix_len > 3) {
			if (libaltfs_dat_init)
				ltfsmsg(ALG0020E, err);
			else
				fprintf(stderr, "ALG0020E Cannot load messages: failed to determine message prefix (ures_getStringByKey: %d)\n", err);
			ures_close(pl->bundle_messages);
			ures_close(pl->bundle_root);
			free(pl);
			return -1;
		}
		/* Convert UChar prefix to char */
		pl->prefix[0] = (char)prefix_uc[0];
		pl->prefix[1] = (char)prefix_uc[1];
		pl->prefix[2] = (prefix_len >= 3) ? (char)prefix_uc[2] : '\0';
		pl->prefix[3] = '\0';
	}

	*messages = pl;
	ltfs_mutex_lock(&output_lock);
	TAILQ_INSERT_HEAD(&plugin_bundles, pl, list);
	ltfs_mutex_unlock(&output_lock);
	return 0;
}

void ltfsprintf_unload_plugin(void *handle)
{
	struct plugin_bundle *pl = handle;

	if (pl) {
		ltfs_mutex_lock(&output_lock);
		TAILQ_REMOVE(&plugin_bundles, pl, list);
		ltfs_mutex_unlock(&output_lock);
		ures_close(pl->bundle_messages);
		ures_close(pl->bundle_root);
		free(pl);
	}
}

/* Print a formatted message in the current system locale. */
int ltfsmsg_internal(bool print_id, int level, char **msg_out, const char *_id, ...)
{
	const UChar *format_uc = NULL;
	int32_t prefix_len, format_len;
	char id[16];
	size_t idlen;
	UErrorCode err = U_ZERO_ERROR;
	va_list argp;
	struct plugin_bundle *entry;

	/*
	 * We accept quoted id used in HPE backend source,
	 * hence we need to remove quotes first.
	 */
	idlen = strlen(_id);
	if (idlen > sizeof(id) - 1)
		goto internal_error;

	if (idlen > 1 && _id[0] == '"' && _id[idlen - 1] == '"') {
		strncpy(id, _id + 1, idlen - 2);
		id[idlen - 2] = '\0';
	} else {
		strcpy(id, _id);
	}

	/* Check loaded plugins for the message, most recently loaded first.
	 * Match by 3-char prefix (id[0..2] == entry->prefix[0..2]). */
	if (! TAILQ_EMPTY(&plugin_bundles)) {
		ltfs_mutex_lock(&output_lock);
		TAILQ_FOREACH(entry, &plugin_bundles, list) {
			if (id[0] == entry->prefix[0] && id[1] == entry->prefix[1] && id[2] == entry->prefix[2]) {
				err = U_ZERO_ERROR;
				format_uc = ures_getStringByKey(entry->bundle_messages, id, &format_len, &err);
				if (U_FAILURE(err) && err != U_MISSING_RESOURCE_ERROR) {
					ltfs_mutex_unlock(&output_lock);
					goto internal_error;
				} else if (U_SUCCESS(err))
					break;
				format_uc = NULL;
			}
		}
		ltfs_mutex_unlock(&output_lock);
		err = U_ZERO_ERROR;
	}

	/* Try to get a fallback message if we didn't find the real message */
	if (! format_uc) {
		format_uc = ures_getStringByKey(bundle_fallback, "notfound", &format_len, &err);
		if (U_FAILURE(err))
			goto internal_error;
	}

	/* Format and print the message string. */
	ltfs_mutex_lock(&output_lock);
	if (ltfs_print_thread_id)
		prefix_len = print_id ? sprintf(output_buf, MSG_PREFIX_TID, (unsigned long)ltfs_get_thread_id(), id) : 0;
	else
		prefix_len = print_id ? sprintf(output_buf, MSG_PREFIX, id) : 0;
	ucnv_fromUChars(output_conv, output_buf + prefix_len, OUTPUT_BUF_SIZE - prefix_len - 1,
		format_uc, format_len, &err);
	if (err == U_BUFFER_OVERFLOW_ERROR) {
		err = U_ZERO_ERROR;
		format_uc = ures_getStringByKey(bundle_fallback, "overflow", &format_len, &err);
		if (U_FAILURE(err)) {
			ltfs_mutex_unlock(&output_lock);
			goto internal_error;
		}

		ucnv_fromUChars(output_conv, output_buf + prefix_len, OUTPUT_BUF_SIZE - prefix_len - 1,
			format_uc, format_len, &err);
		if (U_FAILURE(err)) {
			ltfs_mutex_unlock(&output_lock);
			goto internal_error;
		}
	} else if (U_FAILURE(err)) {
		ltfs_mutex_unlock(&output_lock);
		goto internal_error;
	}

#ifdef mingw_PLATFORM
	va_start(argp, _id);
	vsyslog(level, output_buf, argp);
	va_end(argp);
#else
	va_start(argp, _id);
	vfprintf(stderr, output_buf, argp);
	va_end(argp);
	fprintf(stderr, "\n");

	if (level <= ltfs_syslog_level && ltfs_use_syslog) {
		va_start(argp, _id);
		if (level <= LTFS_ERR)
			vsyslog(syslog_levels[LTFS_ERR], output_buf, argp);
		else if (level >= LTFS_TRACE)
			vsyslog(syslog_levels[LTFS_TRACE], output_buf, argp);
		else
			vsyslog(syslog_levels[level], output_buf, argp);
		va_end(argp);
	}
#endif

	if (msg_out) {
		va_start(argp, _id);
		vsprintf(msg_buf, output_buf, argp);
		va_end(argp);
		*msg_out = strdup(msg_buf);
	}


	ltfs_mutex_unlock(&output_lock);

	return 0;

internal_error:
	if (ltfs_print_thread_id)
		fprintf(stderr, MSG_PREFIX_TID MSG_FALLBACK "\n", (unsigned long)ltfs_get_thread_id(), id);
	else
		fprintf(stderr, MSG_PREFIX MSG_FALLBACK "\n", id);

	if (level < LTFS_DEBUG && ltfs_use_syslog) {
		if (ltfs_print_thread_id) {
			if (level <= LTFS_ERR)
				syslog(syslog_levels[LTFS_ERR], MSG_PREFIX_TID MSG_FALLBACK, (unsigned long)ltfs_get_thread_id(), id);
			else if (level >= LTFS_TRACE)
				syslog(syslog_levels[LTFS_TRACE], MSG_PREFIX_TID MSG_FALLBACK, (unsigned long)ltfs_get_thread_id(), id);
			else
				syslog(syslog_levels[level], MSG_PREFIX_TID MSG_FALLBACK, (unsigned long)ltfs_get_thread_id(), id);
		} else {
			if (level <= LTFS_ERR)
				syslog(syslog_levels[LTFS_ERR], MSG_PREFIX MSG_FALLBACK, id);
			else if (level >= LTFS_TRACE)
				syslog(syslog_levels[LTFS_TRACE], MSG_PREFIX MSG_FALLBACK, id);
			else
				syslog(syslog_levels[level], MSG_PREFIX MSG_FALLBACK, id);
		}
	}
	return -1;
}
