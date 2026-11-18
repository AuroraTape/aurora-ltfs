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
** FILE NAME:       changer_drivers/smc_sense.c
**
** DESCRIPTION:     Sense data of a medium changer mapped to the EDEV_* codes.
**
*************************************************************************************
*/

#include "smc_sense.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "libltfs/ltfs_error.h"

struct smc_sense_entry {
	uint32_t    sense;
	int         err_code;
	const char *msg;
};

/*
 * The SPC codes a medium changer returns and the SMC specific ones. The
 * entries are matched on the full value (sense key, ASC, ASCQ); a value that
 * is not listed gets the generic code of its sense key.
 */
static const struct smc_sense_entry smc_sense_table[] = {
	/* Sense key 0: no sense */
	{ 0x000000, -EDEV_NO_SENSE,                "No additional sense information" },

	/* Sense key 2: not ready */
	{ 0x020400, -EDEV_NOT_REPORTABLE,          "Logical unit not ready, cause not reportable" },
	{ 0x020401, -EDEV_BECOMING_READY,          "Logical unit is in process of becoming ready" },
	{ 0x020402, -EDEV_NEED_INITIALIZE,         "Logical unit not ready, initializing command required" },
	{ 0x020403, -EDEV_MANUAL_INTERVENTION,     "Logical unit not ready, manual intervention required" },
	{ 0x020407, -EDEV_OPERATION_IN_PROGRESS,   "Logical unit not ready, operation in progress" },
	{ 0x020412, -EDEV_OFFLINE,                 "Logical unit not ready, offline" },
	{ 0x020418, -EDEV_DOOR_OPEN,               "Door open" },
	{ 0x020483, -EDEV_DOOR_OPEN,               "Library door is open" },
	{ 0x020484, -EDEV_IE_OPEN,                 "Import/export station is open" },
	{ 0x023B12, -EDEV_DOOR_OPEN,               "Medium magazine removed" },
	{ 0x023B16, -EDEV_IE_OPEN,                 "Mechanical positioning or changer error" },

	/* Sense key 4: hardware error */
	{ 0x040000, -EDEV_HARDWARE_ERROR,          "Hardware error" },
	{ 0x041500, -EDEV_HARDWARE_ERROR,          "Random positioning error" },
	{ 0x041501, -EDEV_HARDWARE_ERROR,          "Mechanical positioning error" },
	{ 0x043B16, -EDEV_HARDWARE_ERROR,          "Mechanical positioning or changer error" },
	{ 0x044400, -EDEV_HARDWARE_ERROR,          "Internal target failure" },

	/* Sense key 5: illegal request */
	{ 0x052000, -EDEV_UNSUPPORETD_COMMAND,     "Invalid command operation code" },
	{ 0x052101, -EDEV_INVALID_ADDRESS,         "Invalid element address" },
	{ 0x052400, -EDEV_INVALID_FIELD_CDB,       "Invalid field in CDB" },
	{ 0x052500, -EDEV_ILLEGAL_REQUEST,         "Logical unit not supported" },
	{ 0x052600, -EDEV_ILLEGAL_REQUEST,         "Invalid field in parameter list" },
	{ 0x052800, -EDEV_ILLEGAL_REQUEST,         "Import or export element accessed" },
	{ 0x053000, -EDEV_ILLEGAL_REQUEST,         "Incompatible medium installed" },
	{ 0x053B0D, -EDEV_DEST_FULL,               "Medium destination element full" },
	{ 0x053B0E, -EDEV_SRC_EMPTY,               "Medium source element empty" },
	{ 0x053B11, -EDEV_MAGAZINE_INACCESSIBLE,   "Medium magazine not accessible" },
	{ 0x053B12, -EDEV_MAGAZINE_INACCESSIBLE,   "Medium magazine removed" },
	{ 0x053B14, -EDEV_MAGAZINE_INACCESSIBLE,   "Medium magazine locked" },
	{ 0x053B18, -EDEV_ELEMENT_DISABLED,        "Element disabled" },
	{ 0x053B1A, -EDEV_DT_ELEMENT_REMOVED,      "Data transfer device removed" },
	{ 0x053B80, -EDEV_SRC_EMPTY,               "Medium transport element empty" },
	{ 0x053B81, -EDEV_DEST_FULL,               "Medium transport element full" },
	{ 0x055302, -EDEV_MEDIUM_LOCKED,           "Medium removal prevented" },
	{ 0x055303, -EDEV_MEDIUM_LOCKED,           "Medium removal prevented by data transfer element" },

	/* Sense key 6: unit attention */
	{ 0x062800, -EDEV_MEDIUM_MAY_BE_CHANGED,   "Not ready to ready transition, medium may have changed" },
	{ 0x062801, -EDEV_IE_ACCESSED,             "Import or export element accessed" },
	{ 0x062900, -EDEV_POR_OR_BUS_RESET,        "Power on, reset, or bus device reset occurred" },
	{ 0x062901, -EDEV_POR_OR_BUS_RESET,        "Power on occurred" },
	{ 0x062902, -EDEV_POR_OR_BUS_RESET,        "SCSI bus reset occurred" },
	{ 0x062903, -EDEV_POR_OR_BUS_RESET,        "Bus device reset function occurred" },
	{ 0x062904, -EDEV_POR_OR_BUS_RESET,        "Device internal reset" },
	{ 0x062A01, -EDEV_TIME_STAMP_CHANGED,      "Mode parameters changed" },
	{ 0x062F00, -EDEV_COMMAND_CLEARED,         "Commands cleared by another initiator" },
	{ 0x063B13, -EDEV_DOOR_CLOSED,             "Medium magazine inserted" },
	{ 0x063F01, -EDEV_CONFIGURE_CHANGED,       "Microcode has been changed" },
	{ 0x063F03, -EDEV_CONFIGURE_CHANGED,       "Inquiry data has changed" },
	{ 0x063F0E, -EDEV_CONFIGURE_CHANGED,       "Reported LUNs data has changed" },

	/* Sense key B: aborted command */
	{ 0x0B0000, -EDEV_ABORTED_COMMAND,         "Aborted command" },
	{ 0x0B4B06, -EDEV_TIMEOUT,                 "Initiator response timeout" },
};

static int _generic_for_key(uint32_t sense)
{
	switch ((sense >> 16) & 0x0F) {
		case 0x0: return -EDEV_NO_SENSE;
		case 0x1: return DEVICE_GOOD;	/* recovered error */
		case 0x2: return -EDEV_NOT_READY;
		case 0x3: return -EDEV_MEDIUM_ERROR;
		case 0x4: return -EDEV_HARDWARE_ERROR;
		case 0x5: return -EDEV_ILLEGAL_REQUEST;
		case 0x6: return -EDEV_UNIT_ATTENTION;
		case 0xB: return -EDEV_ABORTED_COMMAND;
		default:  return -EDEV_UNKNOWN;
	}
}

int smc_sense_to_errorcode(uint32_t sense, const char **msg)
{
	size_t i;

	if (msg)
		*msg = NULL;

	for (i = 0; i < sizeof(smc_sense_table) / sizeof(smc_sense_table[0]); i++) {
		if (smc_sense_table[i].sense == (sense & 0xFFFFFF)) {
			if (msg)
				*msg = smc_sense_table[i].msg;
			return smc_sense_table[i].err_code;
		}
	}

	return _generic_for_key(sense);
}

int smc_parse_sense_string(const char *str, uint32_t *sense)
{
	unsigned int sk, asc_ascq;
	char *end;

	if (!str || !sense)
		return -1;

	sk = (unsigned int)strtoul(str, &end, 16);
	if (end == str || *end != '/' || sk > 0x0F)
		return -1;
	str = end + 1;
	asc_ascq = (unsigned int)strtoul(str, &end, 16);
	if (end == str || *end != '\0' || asc_ascq > 0xFFFF)
		return -1;

	*sense = (sk << 16) | asc_ascq;
	return 0;
}
