/*
**
**  OO_Copyright_BEGIN
**
**
**  Copyright 2010, 2025 The LTFS project. All rights reserved.
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
** COMPONENT NAME:  Linear Tape File System
**
** FILE NAME:       test-tools/ltfs_incindex_recovery.c
**
** DESCRIPTION:     Test tool for incremental index recovery
**
*************************************************************************************
*/

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <getopt.h>
#include <errno.h>
#include <unistd.h>

#include "libltfs/ltfs.h"
#include "libltfs/ltfs_internal.h"
#include "libltfs/tape.h"
#include "libltfs/plugin.h"
#include "libltfs/kmi.h"
#include "libltfs/xml.h"
#include "libltfs/config_file.h"

struct test_options {
	char *tape_path;          /* Path to tape emulation directory */
	char *backend_name;       /* Tape backend name (default: file) */
	int verbose;              /* Verbose output level */
};

static void usage(const char *progname)
{
	printf("LTFS Incremental Index Recovery Test Tool\n");
	printf("Usage: %s [options] <tape-emulation-dir>\n", progname);
	printf("\nOptions:\n");
	printf("  -e, --backend <name>      Tape backend to use (default: file)\n");
	printf("  -v, --verbose             Increase verbosity (can be used multiple times)\n");
	printf("  -h, --help                Show this help\n");
}

static int load_tape_backend(struct ltfs_volume *vol, struct libltfs_plugin *backend, const char *backend_name, const char *tape_path, struct config_file *config)
{
	int ret;
	const char *backend_str = backend_name ? backend_name : "file";
	
	printf("Loading tape backend: %s\n", backend_str);
	
	/* Load the tape backend plugin */
	ret = plugin_load(backend, "tape", backend_str, config);
	if (ret < 0) {
		fprintf(stderr, "ERROR: Cannot load tape backend '%s': %d\n", backend_str, ret);
		return ret;
	}
	
	/* Open the device */
	printf("Opening device: %s\n", tape_path);
	ret = ltfs_device_open(tape_path, backend->ops, vol);
	if (ret < 0) {
		fprintf(stderr, "ERROR: Cannot open device '%s': %d\n", tape_path, ret);
		return ret;
	}
	
	return 0;
}



static int perform_recovery(struct ltfs_volume *vol, struct test_options *opts)
{
	int ret;
	struct tc_position eod_pos;
	struct ltfs_index *recovered_index = NULL;
	
	printf("\n=== Starting Incremental Index Recovery ===\n");
	
	/* Get current position (should be at EOD) */
	ret = tape_get_position(vol->device, &eod_pos);
	if (ret < 0) {
		fprintf(stderr, "ERROR: Cannot get tape position: %d\n", ret);
		return ret;
	}
	
	printf("Current position: partition=%u, block=%llu\n",
		   eod_pos.partition, (unsigned long long)eod_pos.block);
	
	/* Read the last index */
	printf("\nReading last index from tape...\n");
	ret = ltfs_read_index(eod_pos.block, false, false, vol);
	if (ret < 0) {
		fprintf(stderr, "ERROR: Cannot read index: %d\n", ret);
		return ret;
	}
	
	printf("Last index: generation=%llu, position=(%u,%llu)\n",
		   (unsigned long long)vol->index->generation,
		   vol->index->selfptr.partition,
		   (unsigned long long)vol->index->selfptr.block);
	
	/* Apply incremental indexes */
	printf("\nApplying incremental indexes...\n");
	/* TODO: Call the incremental index recovery function */
	printf("INFO: Incremental index recovery function will be called here\n");
	
	recovered_index = vol->index;
	printf("\nRecovered index: generation=%llu, file_count=%llu\n",
		   (unsigned long long)recovered_index->generation,
		   (unsigned long long)recovered_index->file_count);
	
	printf("\n=== Recovery Complete ===\n");
	return 0;
}

int main(int argc, char **argv)
{
	int ret;
	struct ltfs_volume *vol = NULL;
	struct test_options opts = {0};
	struct libltfs_plugin backend;
	struct config_file *config = NULL;
	int c, option_index;
	
	static struct option long_options[] = {
		{"backend",  required_argument, 0, 'e'},
		{"verbose",  no_argument,       0, 'v'},
		{"help",     no_argument,       0, 'h'},
		{0, 0, 0, 0}
	};
	
	/* Parse options */
	while ((c = getopt_long(argc, argv, "e:vh", long_options, &option_index)) != -1) {
		switch (c) {
		case 'e':
			opts.backend_name = optarg;
			break;
		case 'v':
			opts.verbose++;
			break;
		case 'h':
			usage(argv[0]);
			return 0;
		default:
			usage(argv[0]);
			return 1;
		}
	}
	
	/* Check for tape path argument */
	if (optind >= argc) {
		fprintf(stderr, "ERROR: Tape emulation directory path required\n\n");
		usage(argv[0]);
		return 1;
	}
	opts.tape_path = argv[optind];
	
	/* Initialize LTFS */
	printf("Initializing LTFS...\n");
	ret = ltfs_init(LTFS_INFO + opts.verbose, true, true);
	if (ret < 0) {
		fprintf(stderr, "ERROR: LTFS initialization failed: %d\n", ret);
		return 1;
	}
	
	/* Load configuration */
	ret = config_file_load(NULL, &config);
	if (ret < 0) {
		fprintf(stderr, "ERROR: Cannot load configuration: %d\n", ret);
		ret = 1;
		goto cleanup;
	}
	
	/* Allocate volume structure */
	ret = ltfs_volume_alloc("ltfs-test", &vol);
	if (ret < 0) {
		fprintf(stderr, "ERROR: Cannot allocate volume: %d\n", ret);
		goto cleanup_config;
	}
	
	/* Load tape backend */
	ret = load_tape_backend(vol, &backend, opts.backend_name, opts.tape_path, config);
	if (ret < 0) {
		goto cleanup_vol;
	}
	
	/* Perform recovery */
	ret = perform_recovery(vol, &opts);
	
	/* Close device */
	printf("\nClosing device...\n");
	ltfs_device_close(vol);
	
cleanup_vol:
	ltfs_volume_free(&vol);
	
cleanup_config:
	config_file_free(config);
	
cleanup:
	ltfs_finish();
	
	return (ret < 0) ? 1 : 0;
}