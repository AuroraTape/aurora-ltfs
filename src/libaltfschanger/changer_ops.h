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
** FILE NAME:       libaltfschanger/changer_ops.h
**
** DESCRIPTION:     The function table of a medium changer plugin and the
**                  structures it fills. A plugin drives one medium changer
**                  (an SMC device, or an emulation of one) and knows nothing
**                  about LTFS volumes.
**
*************************************************************************************
*/

#ifndef __changer_ops_h
#define __changer_ops_h

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "libltfs/tape_ops.h"	/* struct tc_inq, struct tc_drive_info and the length limits */

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Element types, with the values of the SMC element type code so a plugin can
 * put the field of a READ ELEMENT STATUS descriptor straight into the enum.
 */
enum changer_element_type {
	CHANGER_ELEMENT_TRANSPORT     = 1,	/**< Medium transport element: the picker */
	CHANGER_ELEMENT_STORAGE       = 2,	/**< Storage element: a slot */
	CHANGER_ELEMENT_IMPORT_EXPORT = 3,	/**< Import/export element: the I/E station */
	CHANGER_ELEMENT_DATA_TRANSFER = 4,	/**< Data transfer element: a drive */
};

/** Passed to get_elements() as the type to read every element type. Kept out of the enum. */
#define CHANGER_ELEMENT_ANY 0

/** Length of the identifier part of a primary volume tag (the barcode) */
#define CHANGER_VOLTAG_MAX 32

/**
 * One element as READ ELEMENT STATUS reports it. The plugin interprets the
 * descriptor (per type layout, vendor differences); the caller never sees the
 * raw page.
 */
struct changer_element {
	enum changer_element_type type;
	uint16_t address;
	bool     full;                            /**< Full bit: a cartridge is in the element */
	bool     accessible;                      /**< Access bit: the picker can reach the element */
	bool     exception;                       /**< Except bit: the element is in an abnormal state, see asc / ascq */
	uint8_t  asc;                             /**< Additional sense code of the exception */
	uint8_t  ascq;                            /**< Additional sense code qualifier of the exception */
	bool     source_valid;                    /**< SValid bit: source is meaningful */
	uint16_t source;                          /**< Storage element the cartridge came from */
	bool     voltag_valid;                    /**< A primary volume tag was read */
	char     voltag[CHANGER_VOLTAG_MAX + 1];  /**< The tag with trailing blanks removed, otherwise untouched */
	char     dvcid[TAPE_SERIAL_LEN_MAX + 1];  /**< Data transfer only: serial number of the drive, "" if not reported */
	bool     impexp;                          /**< Import/export only: ImpExp bit, the operator placed the cartridge */
	bool     inenab;                          /**< Import/export only: InEnab bit */
	bool     exenab;                          /**< Import/export only: ExEnab bit */
};

/**
 * What the plugin learned about the changer when it opened it: identity and
 * the element address assignment, plus which optional features the device
 * accepts. The feature flags are probed on open; while the device is not
 * ready they stay at their optimistic defaults and `probed` is false.
 */
struct changer_info {
	char     vendor[TAPE_VENDOR_NAME_LEN_MAX + 1];
	char     model[TAPE_MODEL_NAME_LEN_MAX + 1];
	char     serial_number[TAPE_SERIAL_LEN_MAX + 1];
	char     product_rev[PRODUCT_REV_LENGTH + 1];
	uint16_t transport_start;
	uint16_t transport_count;
	uint16_t storage_start;
	uint16_t storage_count;
	uint16_t ie_start;
	uint16_t ie_count;
	uint16_t dt_start;
	uint16_t dt_count;
	bool     barcode_reader;                  /**< READ ELEMENT STATUS accepts VOLTAG=1 */
	bool     drive_id;                        /**< READ ELEMENT STATUS accepts DVCID=1 */
	bool     exchange;                        /**< EXCHANGE MEDIUM is accepted */
	bool     probed;                          /**< The three flags above were verified against the device */
};

/**
 * Operations of a medium changer plugin. Every entry is mandatory; an
 * operation the device does not implement returns -EDEV_UNSUPPORTED_FUNCTION.
 * Return values are 0 (DEVICE_GOOD) or a negative LTFS_* / EDEV_* code.
 */
struct changer_ops {
	/**
	 * Open a changer.
	 * @param devname Device path or serial number; the format is plugin specific.
	 * @param[out] handle Opaque device handle on success.
	 */
	int (*open)(const char *devname, void **handle);

	/** Close a changer. The handle is invalid afterwards. */
	int (*close)(void *handle);

	/** 0 when a changer named devname can be reached from this host, negative otherwise. */
	int (*is_connected)(const char *devname);

	/** TEST UNIT READY. The wait for a not-ready device belongs to the caller. */
	int (*test_unit_ready)(void *handle);

	/** INQUIRY. Fields that do not apply are zero filled. */
	int (*inquiry)(void *handle, struct tc_inq *inq);

	/** Serial number of the changer. The caller frees the string. */
	int (*get_serialnumber)(void *handle, char **result);

	/** Identity, element address assignment and probed features. Does not talk to the device. */
	int (*get_info)(void *handle, struct changer_info *info);

	/**
	 * List the changers this host can reach, in the shape of the tape device list.
	 * @param buf Array to fill, or NULL to count only.
	 * @param count Capacity of buf.
	 * @return Number of changers found (also when buf is NULL or too small), or negative.
	 */
	int (*get_device_list)(struct tc_drive_info *buf, int count);

	/**
	 * READ ELEMENT STATUS for the elements in [start, start + count) of one type
	 * or of every type (CHANGER_ELEMENT_ANY). count 0 means every element of
	 * that type. The device decides how many descriptors come back, so the
	 * plugin allocates the array and the caller frees it with free().
	 * The plugin handles the allocation length, multiple pages and the
	 * descriptor layouts. VOLTAG and DVCID follow changer_info; CURDATA is set.
	 */
	int (*get_elements)(void *handle, enum changer_element_type type,
						uint16_t start, uint16_t count,
						struct changer_element **elements, size_t *n);

	/** MOVE MEDIUM. transport 0 means the device's default transport element. */
	int (*move)(void *handle, uint16_t transport, uint16_t source, uint16_t dest);

	/**
	 * EXCHANGE MEDIUM: the cartridge at source goes to dest1 and the cartridge
	 * that was at dest1 goes to dest2 (dest2 may equal source).
	 */
	int (*exchange)(void *handle, uint16_t transport, uint16_t source,
					uint16_t dest1, uint16_t dest2);

	/** PREVENT ALLOW MEDIUM REMOVAL with prevent set: lock the import/export station. */
	int (*prevent_medium_removal)(void *handle);

	/** PREVENT ALLOW MEDIUM REMOVAL with prevent clear. */
	int (*allow_medium_removal)(void *handle);

	/**
	 * Make the device re-read its elements (INITIALIZE ELEMENT STATUS). count 0
	 * means the whole library; a range uses the vendor command when the
	 * device accepts it and falls back to the whole library otherwise.
	 */
	int (*scan)(void *handle, uint16_t start, uint16_t count);

	/** Print the plugin's options. */
	void (*help_message)(const char *progname);

	/** Parse plugin specific options (a struct fuse_args *). */
	int (*parse_opts)(void *handle, void *opt_args);
};

/** Every plugin exports these two. */
struct changer_ops *changer_get_ops(void);
const char *changer_get_message_bundle_name(void **message_data);

/** Name of an element type for messages and listings. */
static inline const char *changer_element_type_name(enum changer_element_type type)
{
	switch (type) {
		case CHANGER_ELEMENT_TRANSPORT:     return "transport";
		case CHANGER_ELEMENT_STORAGE:       return "storage";
		case CHANGER_ELEMENT_IMPORT_EXPORT: return "import/export";
		case CHANGER_ELEMENT_DATA_TRANSFER: return "drive";
		default:                            return "unknown";
	}
}

#ifdef __cplusplus
}
#endif

#endif /* __changer_ops_h */
