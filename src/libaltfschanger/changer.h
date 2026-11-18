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
** FILE NAME:       libaltfschanger/changer.h
**
** DESCRIPTION:     The medium changer layer: the one place that holds a
**                  changer plugin's function table. It keeps a table of the
**                  cartridges and the drives of one library and moves
**                  cartridges by barcode and drive serial. It knows nothing
**                  of volumes or tape drives: loading a tape into the drive
**                  (tape_load_tape) and unloading it before a return are the
**                  caller's job.
**
*************************************************************************************
*/

#ifndef __changer_h
#define __changer_h

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "libaltfschanger/changer_ops.h"
#include "libltfs/ltfs_thread.h"
#include "libltfs/arch/time_internal.h"

#ifdef __cplusplus
extern "C" {
#endif

/** Where a cartridge is and what can be done with it */
enum changer_tape_state {
	CHANGER_TAPE_AVAILABLE,       /**< In storage or import/export and movable */
	CHANGER_TAPE_LOADED,          /**< In a data transfer element */
	CHANGER_TAPE_MOVING,          /**< In the middle of our own MOVE or EXCHANGE */
	CHANGER_TAPE_DUPLICATE,       /**< The same barcode is on two or more cartridges */
	CHANGER_TAPE_NOT_ACCESSIBLE,  /**< Its element has Access=0 or Except set */
	CHANGER_TAPE_CLEANING,        /**< Barcode starts with CLN */
};

/** One cartridge. Keyed by barcode, or by address when unlabeled. */
struct changer_tape {
	char     barcode[CHANGER_VOLTAG_MAX + 1];     /**< "" for an unlabeled cartridge */
	char     raw_voltag[CHANGER_VOLTAG_MAX + 1];  /**< The tag as read when it did not normalize */
	enum changer_element_type where;              /**< STORAGE, IMPORT_EXPORT or DATA_TRANSFER */
	uint16_t address;
	uint16_t home;                                /**< Storage address it came from, 0 unknown. Meaningful in a drive */
	enum changer_tape_state state;
	enum changer_tape_state base_state;           /**< state apart from DUPLICATE and MOVING: what the element says */
	uint8_t  asc, ascq;                           /**< Of the element exception when NOT_ACCESSIBLE */
	struct ltfs_timespec first_seen, last_seen;
};

/** One data transfer element */
struct changer_drive {
	uint16_t address;
	char     serial[TAPE_SERIAL_LEN_MAX + 1];     /**< DVCID, "" when the device does not report it */
	bool     full;
	char     barcode[CHANGER_VOLTAG_MAX + 1];     /**< Of the cartridge in it, "" when empty or unlabeled */
	bool     accessible;
	bool     exception;
	uint8_t  asc, ascq;
};

/** Tunables of the layer; zero means the default */
struct changer_opts {
	unsigned ready_wait;    /**< Seconds to wait for a not-ready changer before giving up (30) */
	unsigned move_wait;     /**< Seconds a cartridge may be unseen while the picker holds it (5) */
	uint16_t transport;     /**< Transport element to use, 0 = the device default */
};

/** A copy of the tables, for the reads of tapes/, drives/ and library */
struct changer_inventory {
	struct changer_info   info;
	bool                  ready;             /**< The changer answered the last command */
	int                   not_ready_reason;  /**< EDEV_* when not ready, 0 otherwise */
	bool                  stale;             /**< The tables could not be rebuilt after a change */
	struct ltfs_timespec  inventory_time;    /**< When the whole library was last read */
	int                   last_ua;           /**< Last unit attention seen (EDEV_*), 0 none */
	struct ltfs_timespec  last_ua_time;
	struct changer_tape  *tapes;             /**< Labeled first (by barcode), then unlabeled (by address) */
	size_t                n_tapes;
	size_t                n_unlabeled;
	struct changer_drive *drives;            /**< By address */
	size_t                n_drives;
	uint16_t              storage_free;      /**< Empty, accessible storage elements */
	uint16_t              storage_unusable;  /**< Storage elements with Access=0 or Except */
	uint16_t              ie_free;
};

struct changer;

/** Load the layer's message bundle; the caller keeps the handle for changer_unload_messages(). */
int changer_load_messages(void **handle);
void changer_unload_messages(void *handle);

/**
 * Open a changer: check the function table, open the device, read its
 * identity and take the first inventory. A changer that is not ready (door
 * open) still opens; its tables are empty and the inventory says why.
 * The layer does not reserve the device.
 */
int changer_open(struct changer **out, const char *devname, struct changer_ops *ops,
				 const struct changer_opts *opts);
void changer_close(struct changer *ch);

/** The plugin handle and function table, for the options a plugin parses itself */
void *changer_backend_handle(struct changer *ch);

/**
 * Rebuild the tables from a full READ ELEMENT STATUS. deep first makes the
 * device re-read its elements (INITIALIZE ELEMENT STATUS, minutes).
 * home and first_seen of a barcode survive the rebuild.
 */
int changer_rescan(struct changer *ch, bool deep);

/** Snapshot of the tables; no command goes to the device. Free with changer_inventory_free(). */
int changer_inventory(struct changer *ch, struct changer_inventory *out);
void changer_inventory_free(struct changer_inventory *inv);

/** Table lookups. -LTFS_BARCODE_AMBIGUOUS for a duplicate barcode. */
int changer_find_tape(struct changer *ch, const char *barcode, struct changer_tape *out);
int changer_find_drive(struct changer *ch, const char *serial, struct changer_drive *out);

/** READ ELEMENT STATUS of one element, the check made right before a move */
int changer_element_at(struct changer *ch, uint16_t address, struct changer_element *out);

/** First empty, accessible storage element at or after near (wrapping around), just read */
int changer_free_slot(struct changer *ch, uint16_t near, uint16_t *address);

/** Move the cartridge into the drive. 0 when it is already there. */
int changer_load(struct changer *ch, const char *barcode, const char *serial);

/** Move the cartridge in the drive back to its home slot (or where it came from), else to a free slot */
int changer_return(struct changer *ch, const char *serial);

/**
 * Return the cartridge in the drive and load another one, with EXCHANGE
 * MEDIUM when the device has it and two moves otherwise. The caller has
 * unmounted and unloaded the tape in the drive before calling.
 */
int changer_swap(struct changer *ch, const char *barcode, const char *serial);

/** Move the cartridge to a free import/export element */
int changer_export(struct changer *ch, const char *barcode);

/** Move the cartridge from the import/export element to a free storage slot */
int changer_import(struct changer *ch, const char *barcode);

/** TEST UNIT READY until the changer is ready or the seconds are over */
int changer_wait_ready(struct changer *ch, unsigned seconds);

/**
 * TEST UNIT READY to collect a unit attention the device may be holding for
 * us, and re-read what it says has changed. A daemon calls it when idle.
 */
int changer_check_attention(struct changer *ch);

const char *changer_tape_state_name(enum changer_tape_state state);

#ifdef __cplusplus
}
#endif

#endif /* __changer_h */
