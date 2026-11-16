/*
**
**  OO_Copyright_BEGIN
**
**
**  Copyright 2026 Aurora Tape Project contributors. All rights reserved.
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
**
*************************************************************************************
**
** COMPONENT NAME:  Aurora LTFS
**
** FILE NAME:       altfschanger.c
**
** DESCRIPTION:     Drives one medium changer through a changer plugin, the way
**                  mkaltfs drives one tape drive. For now the commands are the
**                  operations of the plugin itself, named by element address,
**                  which is what the plugin tests need; the cartridge level
**                  commands (load, return, swap by barcode) arrive with the
**                  changer layer.
**
*************************************************************************************
*/

#include <errno.h>
#include <getopt.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <syslog.h>

#include "libltfs/ltfs_fuse_version.h"
#include <fuse.h>

#include "libltfs/ltfs.h"
#include "libltfs/ltfslogging.h"
#include "libltfs/plugin.h"
#include "libltfs/config_file.h"
#include "libaltfschanger/changer_ops.h"

/* Exit codes, the shape of the other commands */
#define ALTFSCHANGER_OK                 (0)
#define ALTFSCHANGER_OPERATIONAL_ERROR  (8)
#define ALTFSCHANGER_USAGE_ERROR        (16)

extern char bin_altfschanger_dat[];

static struct option long_options[] = {
	{ "device",  required_argument, 0, 'd' },
	{ "backend", required_argument, 0, 'e' },
	{ "config",  required_argument, 0, 'i' },
	{ "verbose", required_argument, 0, 'v' },
	{ "help",    no_argument,       0, 'h' },
	{ "version", no_argument,       0, 'V' },
	{ 0, 0, 0, 0 }
};

static const char *short_options = "d:e:i:o:hV";

struct options {
	struct config_file *config;
	const char *devname;
	const char *backend;
	int verbose;
};

static int parse_address(const char *s, uint16_t *addr)
{
	char *end;
	unsigned long v;

	v = strtoul(s, &end, 0);
	if (*s == '\0' || *end != '\0' || v > 0xFFFF) {
		ltfsmsg(ACH0008E, s);
		return -1;
	}
	*addr = (uint16_t)v;
	return 0;
}

static int parse_type(const char *s, enum changer_element_type *type)
{
	if (!strcmp(s, "any"))            *type = CHANGER_ELEMENT_ANY;
	else if (!strcmp(s, "transport")) *type = CHANGER_ELEMENT_TRANSPORT;
	else if (!strcmp(s, "storage"))   *type = CHANGER_ELEMENT_STORAGE;
	else if (!strcmp(s, "ie"))        *type = CHANGER_ELEMENT_IMPORT_EXPORT;
	else if (!strcmp(s, "drive"))     *type = CHANGER_ELEMENT_DATA_TRANSFER;
	else {
		ltfsmsg(ACH0009E, s);
		return -1;
	}
	return 0;
}

static const char *type_short(enum changer_element_type type)
{
	switch (type) {
		case CHANGER_ELEMENT_TRANSPORT:     return "transport";
		case CHANGER_ELEMENT_STORAGE:       return "storage";
		case CHANGER_ELEMENT_IMPORT_EXPORT: return "ie";
		case CHANGER_ELEMENT_DATA_TRANSFER: return "drive";
		default:                            return "?";
	}
}

static int cmd_list(struct changer_ops *ops)
{
	struct tc_drive_info *buf;
	int n, i;

	n = ops->get_device_list(NULL, 0);
	if (n < 0) {
		ltfsmsg(ACH0004E, "list", n);
		return ALTFSCHANGER_OPERATIONAL_ERROR;
	}
	if (n == 0) {
		ltfsmsg(ACH0005I);
		return ALTFSCHANGER_OK;
	}
	buf = calloc(n, sizeof(*buf));
	if (!buf)
		return ALTFSCHANGER_OPERATIONAL_ERROR;
	n = ops->get_device_list(buf, n);
	for (i = 0; i < n; i++)
		printf("%s %s %s %s\n", buf[i].name, buf[i].vendor, buf[i].model, buf[i].serial_number);
	free(buf);
	return ALTFSCHANGER_OK;
}

static int cmd_info(struct changer_ops *ops, void *handle)
{
	struct changer_info info;
	int ret;

	ret = ops->get_info(handle, &info);
	if (ret < 0) {
		ltfsmsg(ACH0004E, "info", ret);
		return ALTFSCHANGER_OPERATIONAL_ERROR;
	}
	printf("vendor %s\nmodel %s\nserial %s\nrevision %s\n",
		   info.vendor, info.model, info.serial_number, info.product_rev);
	printf("transport %u %u\nstorage %u %u\nie %u %u\ndrive %u %u\n",
		   info.transport_start, info.transport_count, info.storage_start, info.storage_count,
		   info.ie_start, info.ie_count, info.dt_start, info.dt_count);
	printf("barcode_reader %s\ndvcid %s\nexchange %s\nprobed %s\n",
		   info.barcode_reader ? "yes" : "no", info.drive_id ? "yes" : "no",
		   info.exchange ? "yes" : "no", info.probed ? "yes" : "no");
	return ALTFSCHANGER_OK;
}

/* One line per element: type address full|empty [voltag=X] [source=N] [dvcid=S] [flags] */
static void print_element(const struct changer_element *e)
{
	printf("%s %u %s", type_short(e->type), e->address, e->full ? "full" : "empty");
	if (e->voltag_valid)
		printf(" voltag=%s", e->voltag);
	else if (e->full)
		printf(" voltag=-");
	if (e->source_valid)
		printf(" source=%u", e->source);
	if (e->dvcid[0])
		printf(" dvcid=%s", e->dvcid);
	if (!e->accessible)
		printf(" inaccessible");
	if (e->exception)
		printf(" except=%02X/%02X", e->asc, e->ascq);
	if (e->type == CHANGER_ELEMENT_IMPORT_EXPORT && e->impexp)
		printf(" impexp");
	printf("\n");
}

/* Repeat a command once when the plugin switched paths under it */
#define RETRY_ON_FAILOVER(name, call) \
	do { \
		ret = (call); \
		if (ret == -EDEV_NEED_FAILOVER) { \
			ltfsmsg(ACH0014W, name); \
			ret = (call); \
		} \
	} while (0)

static int cmd_elements(struct changer_ops *ops, void *handle, int argc, char **argv)
{
	enum changer_element_type type = CHANGER_ELEMENT_ANY;
	uint16_t start = 0, count = 0;
	struct changer_element *elements = NULL;
	size_t n = 0, i;
	int ret;

	if (argc >= 1 && parse_type(argv[0], &type) < 0)
		return ALTFSCHANGER_USAGE_ERROR;
	if (argc >= 2 && parse_address(argv[1], &start) < 0)
		return ALTFSCHANGER_USAGE_ERROR;
	if (argc >= 3 && parse_address(argv[2], &count) < 0)
		return ALTFSCHANGER_USAGE_ERROR;

	RETRY_ON_FAILOVER("elements", ops->get_elements(handle, type, start, count, &elements, &n));
	if (ret < 0) {
		ltfsmsg(ACH0004E, "elements", ret);
		return ALTFSCHANGER_OPERATIONAL_ERROR;
	}
	for (i = 0; i < n; i++)
		print_element(&elements[i]);
	free(elements);
	return ALTFSCHANGER_OK;
}

static int cmd_move(struct changer_ops *ops, void *handle, int argc, char **argv)
{
	uint16_t src, dst, transport = 0;
	int ret;

	if (argc < 2) {
		ltfsmsg(ACH0007E, "move", 2);
		return ALTFSCHANGER_USAGE_ERROR;
	}
	if (parse_address(argv[0], &src) < 0 || parse_address(argv[1], &dst) < 0)
		return ALTFSCHANGER_USAGE_ERROR;
	if (argc >= 3 && parse_address(argv[2], &transport) < 0)
		return ALTFSCHANGER_USAGE_ERROR;

	/* A MOVE is not repeated after a failover: whether it ran is unknown, the caller must look */
	ret = ops->move(handle, transport, src, dst);
	if (ret < 0) {
		ltfsmsg(ACH0004E, "move", ret);
		return ALTFSCHANGER_OPERATIONAL_ERROR;
	}
	return ALTFSCHANGER_OK;
}

static int cmd_exchange(struct changer_ops *ops, void *handle, int argc, char **argv)
{
	uint16_t src, dst1, dst2, transport = 0;
	int ret;

	if (argc < 3) {
		ltfsmsg(ACH0007E, "exchange", 3);
		return ALTFSCHANGER_USAGE_ERROR;
	}
	if (parse_address(argv[0], &src) < 0 || parse_address(argv[1], &dst1) < 0
		|| parse_address(argv[2], &dst2) < 0)
		return ALTFSCHANGER_USAGE_ERROR;
	if (argc >= 4 && parse_address(argv[3], &transport) < 0)
		return ALTFSCHANGER_USAGE_ERROR;

	ret = ops->exchange(handle, transport, src, dst1, dst2);
	if (ret < 0) {
		ltfsmsg(ACH0004E, "exchange", ret);
		return ALTFSCHANGER_OPERATIONAL_ERROR;
	}
	return ALTFSCHANGER_OK;
}

static int cmd_scan(struct changer_ops *ops, void *handle, int argc, char **argv)
{
	uint16_t start = 0, count = 0;
	int ret;

	if (argc == 1) {
		ltfsmsg(ACH0007E, "scan", 2);
		return ALTFSCHANGER_USAGE_ERROR;
	}
	if (argc >= 2 && (parse_address(argv[0], &start) < 0 || parse_address(argv[1], &count) < 0))
		return ALTFSCHANGER_USAGE_ERROR;

	RETRY_ON_FAILOVER("scan", ops->scan(handle, start, count));
	if (ret < 0) {
		ltfsmsg(ACH0004E, "scan", ret);
		return ALTFSCHANGER_OPERATIONAL_ERROR;
	}
	return ALTFSCHANGER_OK;
}

static int cmd_simple(const char *name, int ret)
{
	if (ret < 0) {
		ltfsmsg(ACH0004E, name, ret);
		return ALTFSCHANGER_OPERATIONAL_ERROR;
	}
	return ALTFSCHANGER_OK;
}

int main(int argc, char **argv)
{
	struct options opt;
	struct libltfs_plugin plugin;
	struct changer_ops *ops;
	void *handle = NULL;
	void *message_handle = NULL;
	const char *config_file = NULL;
	const char *command;
	int ret, c, log_level, syslog_level;
	int cmd_argc;
	char **cmd_argv;
	int fuse_argc = 1;
	char **fuse_argv;
	struct fuse_args args;

	memset(&opt, 0, sizeof(opt));
	opt.verbose = -1;

	/* The -o options go to the plugin as if they were on a fuse command line */
	fuse_argv = calloc(argc + 1, sizeof(char *));
	if (!fuse_argv)
		return ALTFSCHANGER_OPERATIONAL_ERROR;
	fuse_argv[0] = argv[0];

	if (!getenv("LANG"))
		setenv("LANG", "en_US.UTF-8", 1);

	openlog("altfschanger", LOG_PID, LOG_USER);
	ret = ltfs_init(LTFS_INFO, true, false);
	if (ret < 0) {
		ltfsmsg(ALC0001E, ret);
		return ALTFSCHANGER_OPERATIONAL_ERROR;
	}
	ret = ltfsprintf_load_plugin("bin_altfschanger", bin_altfschanger_dat, &message_handle);
	if (ret < 0) {
		ltfsmsg(ALC0011E, ret);
		return ALTFSCHANGER_OPERATIONAL_ERROR;
	}

	while ((c = getopt_long(argc, argv, short_options, long_options, NULL)) != -1) {
		switch (c) {
			case 'd':
				opt.devname = optarg;
				break;
			case 'e':
				opt.backend = optarg;
				break;
			case 'i':
				config_file = optarg;
				break;
			case 'o':
				fuse_argv[fuse_argc++] = "-o";
				fuse_argv[fuse_argc++] = optarg;
				break;
			case 'v':
				opt.verbose = atoi(optarg);
				break;
			case 'h':
				ltfsresult(ACH0010I, argv[0]);
				return ALTFSCHANGER_OK;
			case 'V':
				ltfsresult(ACH0011I, "altfschanger", PACKAGE_VERSION);
				return ALTFSCHANGER_OK;
			default:
				ltfsresult(ACH0010I, argv[0]);
				return ALTFSCHANGER_USAGE_ERROR;
		}
	}

	if (opt.verbose >= 100) {
		syslog_level = opt.verbose / 100;
		log_level = opt.verbose % 100;
	} else if (opt.verbose >= 0) {
		log_level = opt.verbose;
		syslog_level = opt.verbose < LTFS_INFO ? opt.verbose : LTFS_INFO;
	} else {
		log_level = LTFS_INFO;
		syslog_level = LTFS_INFO;
	}
	ltfs_set_log_level(log_level);
	ltfs_set_syslog_level(syslog_level);
	ltfsmsg(ACH0001I, PACKAGE_NAME, PACKAGE_VERSION, log_level);

	if (optind >= argc) {
		ltfsresult(ACH0010I, argv[0]);
		return ALTFSCHANGER_USAGE_ERROR;
	}
	command = argv[optind];
	cmd_argc = argc - optind - 1;
	cmd_argv = argv + optind + 1;

	ret = config_file_load(config_file, &opt.config);
	if (ret < 0) {
		ltfsmsg(ALC0009E, ret);
		return ALTFSCHANGER_OPERATIONAL_ERROR;
	}

	if (!opt.backend)
		opt.backend = config_file_get_default_plugin("changer", opt.config);
	if (!opt.backend || !strcmp(opt.backend, "none")) {
		ltfsmsg(ACH0015E);
		return ALTFSCHANGER_USAGE_ERROR;
	}

	ret = plugin_load(&plugin, "changer", opt.backend, opt.config);
	if (ret < 0) {
		ltfsmsg(ACH0002E, opt.backend, ret);
		return ALTFSCHANGER_OPERATIONAL_ERROR;
	}
	ops = plugin.ops;

	/* Commands that need no open changer */
	if (!strcmp(command, "list")) {
		ret = cmd_list(ops);
		goto out;
	}
	if (!strcmp(command, "help")) {
		ops->help_message(argv[0]);
		ret = ALTFSCHANGER_OK;
		goto out;
	}

	if (!opt.devname) {
		ltfsmsg(ACH0012E);
		ret = ALTFSCHANGER_USAGE_ERROR;
		goto out;
	}

	ret = ops->open(opt.devname, &handle);
	if (ret < 0) {
		ltfsmsg(ACH0003E, opt.devname, ret);
		ret = ALTFSCHANGER_OPERATIONAL_ERROR;
		goto out;
	}

	args.argc = fuse_argc;
	args.argv = fuse_argv;
	args.allocated = 0;
	ret = ops->parse_opts(handle, &args);
	if (ret < 0) {
		ltfsmsg(ACH0013E, ret);
		ret = ALTFSCHANGER_USAGE_ERROR;
		goto close;
	}

	if (!strcmp(command, "info"))
		ret = cmd_info(ops, handle);
	else if (!strcmp(command, "elements"))
		ret = cmd_elements(ops, handle, cmd_argc, cmd_argv);
	else if (!strcmp(command, "move"))
		ret = cmd_move(ops, handle, cmd_argc, cmd_argv);
	else if (!strcmp(command, "exchange"))
		ret = cmd_exchange(ops, handle, cmd_argc, cmd_argv);
	else if (!strcmp(command, "scan"))
		ret = cmd_scan(ops, handle, cmd_argc, cmd_argv);
	else if (!strcmp(command, "tur"))
		ret = cmd_simple("tur", ops->test_unit_ready(handle));
	else if (!strcmp(command, "prevent"))
		ret = cmd_simple("prevent", ops->prevent_medium_removal(handle));
	else if (!strcmp(command, "allow"))
		ret = cmd_simple("allow", ops->allow_medium_removal(handle));
	else {
		ltfsmsg(ACH0006E, command);
		ret = ALTFSCHANGER_USAGE_ERROR;
	}

close:
	ops->close(handle);
out:
	plugin_unload(&plugin);
	config_file_free(opt.config);
	ltfsprintf_unload_plugin(message_handle);
	ltfs_finish();
	free(fuse_argv);
	return ret;
}
