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
** FILE NAME:       libaltfschanger/changer.c
**
** DESCRIPTION:     The medium changer layer. See changer.h.
**
**                  The layer holds cartridges and drives, not slots: the
**                  tables are rebuilt from a full READ ELEMENT STATUS and an
**                  empty slot is looked for on the device when one is needed.
**                  The library is shared with operators and other hosts, so
**                  every move is preceded by a read of the two elements it
**                  touches, a unit attention makes the layer re-read what
**                  the device says has changed, and a move whose outcome is
**                  unknown (failover, timeout) is never repeated blindly: the
**                  elements are read instead.
**
*************************************************************************************
*/

#include "changer.h"

#include <ctype.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include "libltfs/ltfs.h"
#include "libltfs/ltfs_error.h"
#include "libltfs/ltfslogging.h"
#include "libltfs/ltfstrace.h"

extern char changer_layer_dat[];

#define DEFAULT_READY_WAIT   (30)
#define DEFAULT_MOVE_WAIT    (5)
#define FREE_SLOT_WINDOW     (64)      /* storage elements read around a hint */
#define FREE_SLOT_CHUNK      (256)     /* and per read when sweeping the whole range */
#define UA_DEPTH_MAX         (2)       /* unit attentions handled while handling one */
#define CHANGE_LOG_MAX       (20)      /* appeared / disappeared cartridges named one by one */
#define CLEANING_PREFIX      "CLN"
#define RETRY_FROM_CHECKS    (1)       /* private: the device recovered, redo the operation from its checks */
#define WAIT_UA_MAX          (4)       /* unit attentions swallowed while waiting for ready */

/* Request ids of the layer for the request trace (four hex digits, pasted into the request number) */
#define REQ_CHG_OPEN    0001
#define REQ_CHG_RESCAN  0002
#define REQ_CHG_LOAD    0003
#define REQ_CHG_RETURN  0004
#define REQ_CHG_SWAP    0005
#define REQ_CHG_EXPORT  0006
#define REQ_CHG_IMPORT  0007

struct changer {
	struct changer_ops   *backend;
	void                 *backend_data;
	char                 *devname;
	struct changer_info   info;
	struct changer_opts   opts;

	ltfs_thread_mutex_t   cmd_lock;        /* one operation (checks + move + table update) at a time */
	ltfs_thread_mutex_t   cache_lock;      /* the tables below */

	struct changer_tape  *tapes;           /* labeled sorted by barcode, then unlabeled sorted by address */
	size_t                n_tapes, n_unlabeled, cap_tapes;
	struct changer_drive *drives;          /* sorted by address */
	size_t                n_drives;
	uint16_t              storage_free, storage_unusable, ie_free;
	struct ltfs_timespec  inventory_time;
	bool                  ready;
	int                   not_ready_reason;
	bool                  stale;
	int                   last_ua;
	struct ltfs_timespec  last_ua_time;
};

/* ---------------------------------------------------------------------- */
/* Small helpers                                                          */
/* ---------------------------------------------------------------------- */

const char *changer_tape_state_name(enum changer_tape_state state)
{
	switch (state) {
		case CHANGER_TAPE_AVAILABLE:      return "available";
		case CHANGER_TAPE_LOADED:         return "loaded";
		case CHANGER_TAPE_MOVING:         return "moving";
		case CHANGER_TAPE_DUPLICATE:      return "duplicate";
		case CHANGER_TAPE_NOT_ACCESSIBLE: return "not-accessible";
		case CHANGER_TAPE_CLEANING:       return "cleaning";
		default:                          return "unknown";
	}
}

int changer_load_messages(void **handle)
{
	return ltfsprintf_load_plugin("changer_layer", changer_layer_dat, handle);
}

void changer_unload_messages(void *handle)
{
	ltfsprintf_unload_plugin(handle);
}

static bool _is_not_ready(int ret)
{
	return ret <= -EDEV_NOT_READY && ret > -(EDEV_NOT_READY + 100);
}

static bool _is_ua(int ret)
{
	return ret < 0 && IS_UNIT_ATTENTION(-ret);
}

/* A move whose outcome is unknown: the command may or may not have run */
static bool _is_uncertain(int ret)
{
	return ret == -EDEV_NEED_FAILOVER || ret == -EDEV_CONNECTION_LOST || ret == -EDEV_TIMEOUT
		|| ret == -EDEV_NO_CONNECTION;
}

static enum changer_element_type _type_of(const struct changer *ch, uint16_t address)
{
	const struct changer_info *i = &ch->info;

	if (i->dt_count && address >= i->dt_start && address < i->dt_start + i->dt_count)
		return CHANGER_ELEMENT_DATA_TRANSFER;
	if (i->ie_count && address >= i->ie_start && address < i->ie_start + i->ie_count)
		return CHANGER_ELEMENT_IMPORT_EXPORT;
	if (i->storage_count && address >= i->storage_start && address < i->storage_start + i->storage_count)
		return CHANGER_ELEMENT_STORAGE;
	if (i->transport_count && address >= i->transport_start && address < i->transport_start + i->transport_count)
		return CHANGER_ELEMENT_TRANSPORT;
	return CHANGER_ELEMENT_ANY;
}

/* A barcode is 1 to 32 upper case letters and digits */
static bool _normalize_barcode(const struct changer_element *e, char *barcode, char *raw)
{
	const char *s = e->voltag;
	size_t len = strlen(s);

	barcode[0] = '\0';
	raw[0] = '\0';
	if (!e->voltag_valid || !len || len > CHANGER_VOLTAG_MAX) {
		strncpy(raw, s, CHANGER_VOLTAG_MAX);
		raw[CHANGER_VOLTAG_MAX] = '\0';
		return false;
	}
	for (; *s; s++) {
		if (!(isupper((unsigned char)*s) || isdigit((unsigned char)*s))) {
			strncpy(raw, e->voltag, CHANGER_VOLTAG_MAX);
			raw[CHANGER_VOLTAG_MAX] = '\0';
			return false;
		}
	}
	strcpy(barcode, e->voltag);
	return true;
}

static int _cmp_tape(const void *a, const void *b)
{
	const struct changer_tape *x = a, *y = b;
	bool xl = x->barcode[0] != '\0', yl = y->barcode[0] != '\0';

	if (xl != yl)
		return xl ? -1 : 1;              /* labeled first */
	if (xl)
		return strcmp(x->barcode, y->barcode);
	return (int)x->address - (int)y->address;
}

static int _cmp_drive(const void *a, const void *b)
{
	const struct changer_drive *x = a, *y = b;
	return (int)x->address - (int)y->address;
}

static int _cmp_barcode_key(const void *key, const void *elem)
{
	return strcmp(key, ((const struct changer_tape *)elem)->barcode);
}

/* ---------------------------------------------------------------------- */
/* The tables (cache_lock held by the caller)                             */
/* ---------------------------------------------------------------------- */

static size_t _n_labeled(const struct changer *ch)
{
	return ch->n_tapes - ch->n_unlabeled;
}

static struct changer_tape *_find_labeled(struct changer_tape *tapes, size_t n_labeled, const char *barcode)
{
	if (!n_labeled || !barcode || !barcode[0])
		return NULL;
	return bsearch(barcode, tapes, n_labeled, sizeof(*tapes), _cmp_barcode_key);
}

static struct changer_tape *_tape_by_barcode(struct changer *ch, const char *barcode)
{
	return _find_labeled(ch->tapes, _n_labeled(ch), barcode);
}

static struct changer_tape *_tape_at(struct changer *ch, uint16_t address)
{
	size_t i;

	for (i = 0; i < ch->n_tapes; i++)
		if (ch->tapes[i].address == address)
			return &ch->tapes[i];
	return NULL;
}

static struct changer_drive *_drive_at(struct changer *ch, uint16_t address)
{
	size_t i;

	for (i = 0; i < ch->n_drives; i++)
		if (ch->drives[i].address == address)
			return &ch->drives[i];
	return NULL;
}

static struct changer_drive *_drive_by_serial(struct changer *ch, const char *serial)
{
	size_t i;
	char *end;
	unsigned long addr;

	if (!serial || !serial[0])
		return NULL;
	for (i = 0; i < ch->n_drives; i++)
		if (ch->drives[i].serial[0] && !strcmp(ch->drives[i].serial, serial))
			return &ch->drives[i];
	/* A device that reports no DVCID: the element address names the drive */
	addr = strtoul(serial, &end, 10);
	if (!*end && addr <= 0xFFFF)
		return _drive_at(ch, (uint16_t)addr);
	return NULL;
}

/* Sort, split labeled from unlabeled and mark duplicate barcodes */
static void _resort(struct changer *ch)
{
	size_t i, n_labeled;

	if (ch->n_tapes)
		qsort(ch->tapes, ch->n_tapes, sizeof(*ch->tapes), _cmp_tape);
	n_labeled = 0;
	while (n_labeled < ch->n_tapes && ch->tapes[n_labeled].barcode[0])
		n_labeled++;
	ch->n_unlabeled = ch->n_tapes - n_labeled;

	for (i = 0; i < n_labeled; i++) {
		struct changer_tape *t = &ch->tapes[i];
		bool dup = (i + 1 < n_labeled && !strcmp(t->barcode, ch->tapes[i + 1].barcode))
			|| (i > 0 && !strcmp(t->barcode, ch->tapes[i - 1].barcode));
		if (dup) {
			if (t->state != CHANGER_TAPE_DUPLICATE && i + 1 < n_labeled
				&& !strcmp(t->barcode, ch->tapes[i + 1].barcode))
				ltfsmsg(ACL0006W, t->barcode, changer_element_type_name(t->where), t->address,
						changer_element_type_name(ch->tapes[i + 1].where), ch->tapes[i + 1].address);
			t->state = CHANGER_TAPE_DUPLICATE;
		} else if (t->state == CHANGER_TAPE_DUPLICATE) {
			t->state = t->base_state;	/* the twin went away */
		}
	}
}

/* The state a cartridge in this element has, apart from duplicate and moving */
static enum changer_tape_state _state_for(const struct changer_element *e, const char *barcode)
{
	if (e->type == CHANGER_ELEMENT_DATA_TRANSFER)
		return CHANGER_TAPE_LOADED;
	if (!e->accessible || e->exception)
		return CHANGER_TAPE_NOT_ACCESSIBLE;
	if (barcode[0] && !strncmp(barcode, CLEANING_PREFIX, strlen(CLEANING_PREFIX)))
		return CHANGER_TAPE_CLEANING;
	return CHANGER_TAPE_AVAILABLE;
}

static int _grow_tapes(struct changer *ch, size_t need)
{
	struct changer_tape *grown;
	size_t cap = ch->cap_tapes ? ch->cap_tapes : 64;

	if (need <= ch->cap_tapes)
		return 0;
	while (cap < need)
		cap *= 2;
	grown = realloc(ch->tapes, cap * sizeof(*grown));
	if (!grown)
		return -LTFS_NO_MEMORY;
	ch->tapes = grown;
	ch->cap_tapes = cap;
	return 0;
}

static void _fill_drive(struct changer_drive *d, const struct changer_element *e)
{
	char raw[CHANGER_VOLTAG_MAX + 1];

	memset(d, 0, sizeof(*d));
	d->address = e->address;
	strncpy(d->serial, e->dvcid, TAPE_SERIAL_LEN_MAX);
	d->full = e->full;
	d->accessible = e->accessible;
	d->exception = e->exception;
	d->asc = e->asc;
	d->ascq = e->ascq;
	if (e->full)
		_normalize_barcode(e, d->barcode, raw);
}

/* Rebuild everything from a full element list. Keeps home and first_seen of a barcode. */
static int _build_tables(struct changer *ch, const struct changer_element *elements, size_t n)
{
	struct changer_tape *old_tapes = ch->tapes, *tapes = NULL;
	struct changer_drive *drives = NULL;
	size_t old_n = ch->n_tapes, old_labeled = _n_labeled(ch), old_cap = ch->cap_tapes;
	size_t n_tapes = 0, n_drives = 0, cap = 0, i;
	uint16_t storage_free = 0, storage_unusable = 0, ie_free = 0;
	struct ltfs_timespec now;
	size_t appeared = 0, disappeared = 0;

	get_current_timespec(&now);

	for (i = 0; i < n; i++)
		if (elements[i].type == CHANGER_ELEMENT_DATA_TRANSFER)
			n_drives++;
	drives = calloc(n_drives ? n_drives : 1, sizeof(*drives));
	if (!drives)
		return -LTFS_NO_MEMORY;
	n_drives = 0;

	for (i = 0; i < n; i++) {
		const struct changer_element *e = &elements[i];
		struct changer_tape *t, *old;

		switch (e->type) {
			case CHANGER_ELEMENT_STORAGE:
				if (!e->accessible || e->exception)
					storage_unusable++;
				else if (!e->full)
					storage_free++;
				break;
			case CHANGER_ELEMENT_IMPORT_EXPORT:
				if (!e->full && e->accessible && !e->exception)
					ie_free++;
				break;
			case CHANGER_ELEMENT_DATA_TRANSFER:
				_fill_drive(&drives[n_drives++], e);
				break;
			default:
				continue;
		}
		if (!e->full)
			continue;

		if (n_tapes == cap) {
			struct changer_tape *grown;
			cap = cap ? cap * 2 : 64;
			grown = realloc(tapes, cap * sizeof(*tapes));
			if (!grown) {
				free(tapes);
				free(drives);
				return -LTFS_NO_MEMORY;
			}
			tapes = grown;
		}
		t = &tapes[n_tapes++];
		memset(t, 0, sizeof(*t));
		_normalize_barcode(e, t->barcode, t->raw_voltag);
		t->where = e->type;
		t->address = e->address;
		t->base_state = t->state = _state_for(e, t->barcode);
		t->asc = e->asc;
		t->ascq = e->ascq;
		t->last_seen = now;

		old = _find_labeled(old_tapes, old_labeled, t->barcode);
		t->first_seen = old ? old->first_seen : now;
		if (e->type == CHANGER_ELEMENT_DATA_TRANSFER) {
			if (e->source_valid && _type_of(ch, e->source) == CHANGER_ELEMENT_STORAGE)
				t->home = e->source;
			else if (old)
				t->home = old->home;
		}
		if (t->barcode[0] && !old && old_n)
			appeared++;
		if (t->barcode[0] && !old && old_n && appeared <= CHANGE_LOG_MAX)
			ltfsmsg(ACL0003I, t->barcode, changer_element_type_name(t->where), t->address);
	}

	if (n_drives)
		qsort(drives, n_drives, sizeof(*drives), _cmp_drive);

	/* Swap the tables in */
	ch->tapes = tapes;
	ch->n_tapes = n_tapes;
	ch->cap_tapes = cap;
	free(ch->drives);
	ch->drives = drives;
	ch->n_drives = n_drives;
	ch->storage_free = storage_free;
	ch->storage_unusable = storage_unusable;
	ch->ie_free = ie_free;
	ch->inventory_time = now;
	_resort(ch);

	/* What went away */
	for (i = 0; i < old_labeled; i++) {
		if (!_tape_by_barcode(ch, old_tapes[i].barcode)) {
			disappeared++;
			if (disappeared <= CHANGE_LOG_MAX)
				ltfsmsg(ACL0004I, old_tapes[i].barcode, changer_element_type_name(old_tapes[i].where),
						old_tapes[i].address);
		}
	}
	if (appeared > CHANGE_LOG_MAX || disappeared > CHANGE_LOG_MAX)
		ltfsmsg(ACL0005W, (unsigned)appeared, (unsigned)disappeared, (unsigned)CHANGE_LOG_MAX);
	(void)old_cap;
	free(old_tapes);

	ltfsmsg(ACL0002I, ch->devname, (unsigned)ch->n_tapes, (unsigned)ch->n_unlabeled,
			(unsigned)ch->n_drives, ch->storage_free, ch->storage_unusable, ch->ie_free);
	return 0;
}

/*
 * Make the tables agree with one element just read. Used after a check
 * before a move found something else than expected, and after a move.
 */
static int _apply_element(struct changer *ch, const struct changer_element *e)
{
	struct changer_tape *t = _tape_at(ch, e->address);
	struct changer_drive *d = _drive_at(ch, e->address);
	char barcode[CHANGER_VOLTAG_MAX + 1], raw[CHANGER_VOLTAG_MAX + 1];
	bool labeled = false, usable = e->accessible && !e->exception;
	int ret;

	if (e->type == CHANGER_ELEMENT_TRANSPORT)
		return 0;
	ret = _grow_tapes(ch, ch->n_tapes + 1);	/* before anything is taken out */
	if (ret < 0)
		return ret;
	if (e->full)
		labeled = _normalize_barcode(e, barcode, raw);

	/* Something was here and is not any more, or is something else */
	if (t && (!e->full || strcmp(t->barcode, e->full ? barcode : ""))) {
		bool was_usable = t->base_state != CHANGER_TAPE_NOT_ACCESSIBLE;
		if (e->type == CHANGER_ELEMENT_STORAGE) {
			if (usable)
				ch->storage_free++;
			else if (was_usable)
				ch->storage_unusable++;
		} else if (e->type == CHANGER_ELEMENT_IMPORT_EXPORT && usable) {
			ch->ie_free++;
		}
		*t = ch->tapes[--ch->n_tapes];
		t = NULL;
		_resort(ch);	/* the lookup by barcode below needs the order back */
	}

	if (e->full && !t) {
		struct changer_tape *elsewhere = labeled ? _tape_by_barcode(ch, barcode) : NULL;
		struct changer_tape fresh;

		if (elsewhere && elsewhere->state != CHANGER_TAPE_DUPLICATE) {
			/* The cartridge moved: carry its record, free where it was */
			struct changer_drive *od = _drive_at(ch, elsewhere->address);
			if (elsewhere->where == CHANGER_ELEMENT_STORAGE && elsewhere->base_state != CHANGER_TAPE_NOT_ACCESSIBLE)
				ch->storage_free++;
			else if (elsewhere->where == CHANGER_ELEMENT_IMPORT_EXPORT && elsewhere->base_state != CHANGER_TAPE_NOT_ACCESSIBLE)
				ch->ie_free++;
			if (od) {
				od->full = false;
				od->barcode[0] = '\0';
			}
			fresh = *elsewhere;
			*elsewhere = ch->tapes[--ch->n_tapes];
		} else {
			memset(&fresh, 0, sizeof(fresh));
			get_current_timespec(&fresh.first_seen);
			strcpy(fresh.barcode, barcode);
			strcpy(fresh.raw_voltag, raw);
		}
		if (e->type == CHANGER_ELEMENT_DATA_TRANSFER) {
			if (e->source_valid && _type_of(ch, e->source) == CHANGER_ELEMENT_STORAGE)
				fresh.home = e->source;
			else if (fresh.where == CHANGER_ELEMENT_STORAGE)
				fresh.home = fresh.address;
		} else if (e->type == CHANGER_ELEMENT_STORAGE) {
			fresh.home = 0;
		}
		fresh.where = e->type;
		fresh.address = e->address;
		fresh.base_state = fresh.state = _state_for(e, fresh.barcode);
		fresh.asc = e->asc;
		fresh.ascq = e->ascq;
		get_current_timespec(&fresh.last_seen);
		if (e->type == CHANGER_ELEMENT_STORAGE && usable && ch->storage_free)
			ch->storage_free--;
		else if (e->type == CHANGER_ELEMENT_IMPORT_EXPORT && usable && ch->ie_free)
			ch->ie_free--;
		ch->tapes[ch->n_tapes++] = fresh;
	} else if (e->full && t) {
		t->base_state = _state_for(e, t->barcode);
		t->state = t->state == CHANGER_TAPE_MOVING ? CHANGER_TAPE_MOVING : t->base_state;
		t->asc = e->asc;
		t->ascq = e->ascq;
		get_current_timespec(&t->last_seen);
	}

	if (d)
		_fill_drive(d, e);
	_resort(ch);
	return 0;
}

/*
 * Our own move succeeded: the cartridge at src is now at dst. False when the
 * record at src is not the cartridge the caller moved (the table was wrong);
 * the caller then reads the two elements instead.
 */
static bool _moved(struct changer *ch, uint16_t src, uint16_t dst, const char *barcode)
{
	struct changer_tape *t, *other;
	struct changer_drive *d;
	enum changer_element_type dtype = _type_of(ch, dst), stype = _type_of(ch, src);

	/* A record that still claims dst is stale: nothing can have been there */
	other = _tape_at(ch, dst);
	if (other) {
		if (dtype == CHANGER_ELEMENT_STORAGE && other->base_state != CHANGER_TAPE_NOT_ACCESSIBLE)
			ch->storage_free++;
		else if (dtype == CHANGER_ELEMENT_IMPORT_EXPORT && other->base_state != CHANGER_TAPE_NOT_ACCESSIBLE)
			ch->ie_free++;
		*other = ch->tapes[--ch->n_tapes];
		_resort(ch);
	}

	t = _tape_at(ch, src);
	if (!t || (barcode && t->barcode[0] && strcmp(t->barcode, barcode)))
		return false;

	if (stype == CHANGER_ELEMENT_STORAGE)
		ch->storage_free++;
	else if (stype == CHANGER_ELEMENT_IMPORT_EXPORT)
		ch->ie_free++;
	if (dtype == CHANGER_ELEMENT_STORAGE && ch->storage_free)
		ch->storage_free--;
	else if (dtype == CHANGER_ELEMENT_IMPORT_EXPORT && ch->ie_free)
		ch->ie_free--;

	if (dtype == CHANGER_ELEMENT_DATA_TRANSFER && stype == CHANGER_ELEMENT_STORAGE)
		t->home = src;
	else if (dtype == CHANGER_ELEMENT_STORAGE)
		t->home = 0;
	t->where = dtype;
	t->address = dst;
	t->base_state = dtype == CHANGER_ELEMENT_DATA_TRANSFER ? CHANGER_TAPE_LOADED
		: (t->barcode[0] && !strncmp(t->barcode, CLEANING_PREFIX, strlen(CLEANING_PREFIX)))
			? CHANGER_TAPE_CLEANING : CHANGER_TAPE_AVAILABLE;
	t->state = t->base_state;
	get_current_timespec(&t->last_seen);

	d = _drive_at(ch, src);
	if (d) {
		d->full = false;
		d->barcode[0] = '\0';
	}
	d = _drive_at(ch, dst);
	if (d) {
		d->full = true;
		strcpy(d->barcode, t->barcode);
	}
	_resort(ch);
	ltfsmsg(ACL0012I, t->barcode[0] ? t->barcode : "(unlabeled)", changer_element_type_name(stype), src,
			changer_element_type_name(dtype), dst);
	return true;
}

/* Mark a cartridge as moving, or (any other state) give it back the state its element says */
static void _set_state(struct changer *ch, uint16_t address, enum changer_tape_state state)
{
	struct changer_tape *t;

	ltfs_thread_mutex_lock(&ch->cache_lock);
	t = _tape_at(ch, address);
	if (t)
		t->state = state == CHANGER_TAPE_MOVING ? CHANGER_TAPE_MOVING : t->base_state;
	ltfs_thread_mutex_unlock(&ch->cache_lock);
}

/* The fields the inventory copies are written under cache_lock */
static void _set_ready(struct changer *ch, bool ready, int reason, bool stale)
{
	ltfs_thread_mutex_lock(&ch->cache_lock);
	ch->ready = ready;
	ch->not_ready_reason = reason;
	ch->stale = stale;
	ltfs_thread_mutex_unlock(&ch->cache_lock);
}

static void _note_ua(struct changer *ch, int ret)
{
	ltfs_thread_mutex_lock(&ch->cache_lock);
	ch->last_ua = -ret;
	get_current_timespec(&ch->last_ua_time);
	ch->stale = true;	/* until the re-read the attention calls for has run */
	ltfs_thread_mutex_unlock(&ch->cache_lock);
}

/* ---------------------------------------------------------------------- */
/* Commands to the device: unit attention, not ready, failover            */
/* ---------------------------------------------------------------------- */

static int _rescan(struct changer *ch, bool deep, int depth);
static int _get_elements(struct changer *ch, enum changer_element_type type, uint16_t start,
						 uint16_t count, struct changer_element **elements, size_t *n, int depth);

static int _after_ua(struct changer *ch, int ret, int depth);

/*
 * Wait for the device to answer TEST UNIT READY, up to seconds. A unit
 * attention seen meanwhile is handled (re-read) once the device is ready.
 */
static int _wait_ready(struct changer *ch, unsigned seconds, int depth)
{
	unsigned waited = 0;
	int ret = 0, retries = 0, uas = 0, pending_ua = 0;

	for (;;) {
		ret = ch->backend->test_unit_ready(ch->backend_data);
		if (ret == 0) {
			_set_ready(ch, true, 0, ch->stale);
			if (pending_ua)
				return _after_ua(ch, pending_ua, depth);
			return 0;
		}
		if (_is_ua(ret)) {
			_note_ua(ch, ret);
			if (-ret != EDEV_COMMAND_CLEARED && (!pending_ua || -ret != EDEV_IE_ACCESSED))
				pending_ua = ret;	/* the widest re-read wins */
			if (++uas > WAIT_UA_MAX)
				return ret;
			continue;	/* the condition is reported once; the next TUR tells the truth */
		}
		if (ret == -EDEV_NEED_FAILOVER && retries++ < 1)
			continue;
		if (!_is_not_ready(ret))
			return ret;
		_set_ready(ch, false, -ret, true);
		if (waited >= seconds) {
			ltfsmsg(ACL0008W, -ret, seconds);
			return -LTFS_CHANGER_NOT_READY;
		}
		if (!waited)
			ltfsmsg(ACL0009I, -ret);
		sleep(1);
		waited++;
	}
}

/*
 * The device told us someone else changed something. Re-read what the
 * unit attention says and remember it for the inventory. The command that
 * got the attention was not executed, so the caller repeats it.
 */
static int _after_ua(struct changer *ch, int ret, int depth)
{
	const char *scope;
	int r;

	_note_ua(ch, ret);
	if (depth >= UA_DEPTH_MAX)
		return 0;

	switch (-ret) {
		case EDEV_COMMAND_CLEARED:
			ltfsmsg(ACL0007W, -ret, ch->devname, "nothing: another initiator is active");
			ltfs_thread_mutex_lock(&ch->cache_lock);
			ch->stale = false;
			ltfs_thread_mutex_unlock(&ch->cache_lock);
			return 0;
		case EDEV_IE_ACCESSED: {
			struct changer_element *el = NULL;
			size_t n = 0, i;
			scope = "import/export elements";
			ltfsmsg(ACL0007W, -ret, ch->devname, scope);
			r = _get_elements(ch, CHANGER_ELEMENT_IMPORT_EXPORT, 0, 0, &el, &n, depth + 1);
			if (r < 0)
				return r;
			ltfs_thread_mutex_lock(&ch->cache_lock);
			for (i = 0; i < n && r == 0; i++)
				r = _apply_element(ch, &el[i]);
			if (r == 0)
				ch->stale = false;
			ltfs_thread_mutex_unlock(&ch->cache_lock);
			free(el);
			return r;
		}
		case EDEV_POR_OR_BUS_RESET:
		case EDEV_CONFIGURE_CHANGED:
		case EDEV_TIME_STAMP_CHANGED:
			scope = "device information and every element";
			ltfsmsg(ACL0007W, -ret, ch->devname, scope);
			{
				struct changer_info info;
				r = ch->backend->get_info(ch->backend_data, &info);
				if (r < 0)
					return r;
				ltfs_thread_mutex_lock(&ch->cache_lock);
				ch->info = info;
				ltfs_thread_mutex_unlock(&ch->cache_lock);
			}
			return _rescan(ch, false, depth + 1);
		default:
			scope = "every element";
			ltfsmsg(ACL0007W, -ret, ch->devname, scope);
			return _rescan(ch, false, depth + 1);
	}
}

/*
 * Run a command that is safe to repeat: handles a unit attention, a not
 * ready device and one failover. The command is a callback so the same
 * rules apply to READ ELEMENT STATUS, INITIALIZE ELEMENT STATUS and TUR.
 */
static int _issue_idempotent(struct changer *ch, int (*cmd)(struct changer *, void *), void *arg, int depth)
{
	int ret, attempts = 0, failovers = 0;

	for (;;) {
		ret = cmd(ch, arg);
		if (ret == 0)
			return 0;
		if (++attempts > 4)
			return ret;
		if (_is_ua(ret)) {
			ret = _after_ua(ch, ret, depth);
			if (ret < 0)
				return ret;
			continue;
		}
		if (ret == -EDEV_NEED_FAILOVER && failovers++ < 1)
			continue;
		if (_is_not_ready(ret)) {
			ret = _wait_ready(ch, ch->opts.ready_wait, depth);
			if (ret < 0)
				return ret;
			continue;
		}
		return ret;
	}
}

struct get_elements_arg {
	enum changer_element_type type;
	uint16_t start, count;
	struct changer_element **elements;
	size_t *n;
};

static int _cmd_get_elements(struct changer *ch, void *p)
{
	struct get_elements_arg *a = p;
	free(*a->elements);
	*a->elements = NULL;
	*a->n = 0;
	return ch->backend->get_elements(ch->backend_data, a->type, a->start, a->count, a->elements, a->n);
}

static int _get_elements(struct changer *ch, enum changer_element_type type, uint16_t start,
						 uint16_t count, struct changer_element **elements, size_t *n, int depth)
{
	struct get_elements_arg a = { type, start, count, elements, n };
	*elements = NULL;
	*n = 0;
	return _issue_idempotent(ch, _cmd_get_elements, &a, depth);
}

static int _cmd_scan(struct changer *ch, void *p)
{
	(void)p;
	return ch->backend->scan(ch->backend_data, 0, 0);
}

/* Full inventory */
static int _rescan(struct changer *ch, bool deep, int depth)
{
	struct changer_element *elements = NULL;
	size_t n = 0;
	int ret;

	if (deep) {
		ret = _issue_idempotent(ch, _cmd_scan, NULL, depth);
		if (ret < 0 && ret != -EDEV_UNSUPPORTED_FUNCTION)
			goto not_ready;
	}
	ret = _get_elements(ch, CHANGER_ELEMENT_ANY, 0, 0, &elements, &n, depth);
	if (ret < 0) {
		free(elements);
		goto not_ready;
	}

	ltfs_thread_mutex_lock(&ch->cache_lock);
	ret = _build_tables(ch, elements, n);
	if (ret == 0) {
		ch->ready = true;
		ch->not_ready_reason = 0;
		ch->stale = false;
	}
	ltfs_thread_mutex_unlock(&ch->cache_lock);
	free(elements);
	return ret;

not_ready:
	ltfs_thread_mutex_lock(&ch->cache_lock);
	ch->stale = true;
	if (ret == -LTFS_CHANGER_NOT_READY || _is_not_ready(ret)) {
		ch->ready = false;
		if (_is_not_ready(ret))
			ch->not_ready_reason = -ret;
		ret = -LTFS_CHANGER_NOT_READY;
	}
	ltfs_thread_mutex_unlock(&ch->cache_lock);
	return ret;
}

/* One element, just read */
static int _element_at(struct changer *ch, uint16_t address, struct changer_element *out)
{
	struct changer_element *el = NULL;
	size_t n = 0, i;
	int ret;

	ret = _get_elements(ch, CHANGER_ELEMENT_ANY, address, 1, &el, &n, 0);
	if (ret < 0)
		return ret;
	ret = -EDEV_INVALID_ADDRESS;
	for (i = 0; i < n; i++) {
		if (el[i].address == address) {
			*out = el[i];
			ret = 0;
			break;
		}
	}
	free(el);
	return ret;
}

/*
 * MOVE / EXCHANGE. A unit attention or a not-ready device means the command
 * did not run; after the re-read or the wait the operation goes back to its
 * checks (RETRY_FROM_CHECKS) rather than repeating the command blindly.
 */
static int _move(struct changer *ch, uint16_t src, uint16_t dst)
{
	int ret;

	ret = ch->backend->move(ch->backend_data, ch->opts.transport, src, dst);
	if (_is_ua(ret)) {
		ret = _after_ua(ch, ret, 0);
		return ret < 0 ? ret : RETRY_FROM_CHECKS;	/* not executed; the checks are stale */
	}
	if (_is_not_ready(ret)) {
		ret = _wait_ready(ch, ch->opts.ready_wait, 0);
		return ret < 0 ? ret : RETRY_FROM_CHECKS;
	}
	return ret;
}

static int _exchange(struct changer *ch, uint16_t src, uint16_t dst1, uint16_t dst2)
{
	int ret;

	ret = ch->backend->exchange(ch->backend_data, ch->opts.transport, src, dst1, dst2);
	if (_is_ua(ret)) {
		ret = _after_ua(ch, ret, 0);
		return ret < 0 ? ret : RETRY_FROM_CHECKS;
	}
	if (_is_not_ready(ret)) {
		ret = _wait_ready(ch, ch->opts.ready_wait, 0);
		return ret < 0 ? ret : RETRY_FROM_CHECKS;
	}
	return ret;
}

/* ---------------------------------------------------------------------- */
/* Checks around a move                                                   */
/* ---------------------------------------------------------------------- */

/*
 * The element must hold the cartridge (barcode, or any cartridge when
 * barcode is NULL) or, when want_full is false, be empty. A different
 * finding corrects the tables for that element and fails.
 */
static int _expect(struct changer *ch, uint16_t address, bool want_full, const char *barcode,
				   struct changer_element *out)
{
	struct changer_element e;
	char bc[CHANGER_VOLTAG_MAX + 1], raw[CHANGER_VOLTAG_MAX + 1];
	int ret;

	ret = _element_at(ch, address, &e);
	if (ret < 0)
		return ret;
	if (out)
		*out = e;

	if (want_full && !e.full) {
		ltfsmsg(ACL0011W, address, "empty", barcode ? barcode : "a cartridge");
		ret = -LTFS_ELEMENT_EMPTY;
	} else if (!want_full && e.full) {
		_normalize_barcode(&e, bc, raw);
		ltfsmsg(ACL0010W, address, bc[0] ? bc : "an unlabeled cartridge", "nothing");
		ret = -LTFS_ELEMENT_FULL;
	} else if (want_full && barcode) {
		_normalize_barcode(&e, bc, raw);
		if (strcmp(bc, barcode)) {
			ltfsmsg(ACL0010W, address, bc[0] ? bc : "an unlabeled cartridge", barcode);
			ret = -LTFS_INVENTORY_STALE;
		}
	}
	if (!e.accessible || e.exception) {
		ltfsmsg(ACL0018W, address, e.asc, e.ascq);
		if (ret == 0)
			ret = -EDEV_MAGAZINE_INACCESSIBLE;
	}
	if (ret < 0) {
		ltfs_thread_mutex_lock(&ch->cache_lock);
		_apply_element(ch, &e);
		ltfs_thread_mutex_unlock(&ch->cache_lock);
	}
	return ret;
}

/* The tables after reading both elements of a move, when the record could not simply be moved */
static int _settle_by_reading(struct changer *ch, uint16_t src, uint16_t dst)
{
	struct changer_element es, ed;
	int r;

	r = _element_at(ch, src, &es);
	if (r < 0)
		return r;
	ltfs_thread_mutex_lock(&ch->cache_lock);
	r = _apply_element(ch, &es);
	ltfs_thread_mutex_unlock(&ch->cache_lock);
	if (r < 0)
		return r;
	r = _element_at(ch, dst, &ed);
	if (r < 0)
		return r;
	ltfs_thread_mutex_lock(&ch->cache_lock);
	r = _apply_element(ch, &ed);
	ltfs_thread_mutex_unlock(&ch->cache_lock);
	return r;
}

/* Does the element hold the cartridge (any cartridge when barcode is NULL)? */
static bool _holds(const struct changer_element *e, const char *barcode)
{
	char bc[CHANGER_VOLTAG_MAX + 1], raw[CHANGER_VOLTAG_MAX + 1];

	if (!e->full)
		return false;
	if (!barcode)
		return true;
	_normalize_barcode(e, bc, raw);
	return !strcmp(bc, barcode);
}

/*
 * After a move the device answered for: 0 when the cartridge is at dst,
 * RETRY_FROM_CHECKS when the device recovered and the operation must redo
 * its checks, else what the elements say.
 */
static int _settle_move(struct changer *ch, int ret, uint16_t src, uint16_t dst, const char *barcode,
						bool allow_retry)
{
	struct changer_element es, ed;
	int r;

	if (ret == RETRY_FROM_CHECKS) {
		_set_state(ch, src, CHANGER_TAPE_AVAILABLE);
		return ret;
	}
	if (ret == 0) {
		bool ok;
		ltfs_thread_mutex_lock(&ch->cache_lock);
		ok = _moved(ch, src, dst, barcode);
		ltfs_thread_mutex_unlock(&ch->cache_lock);
		if (ok)
			return 0;
		ltfsmsg(ACL0017E, barcode ? barcode : "the cartridge");
		r = _settle_by_reading(ch, src, dst);
		return r < 0 ? r : -LTFS_INVENTORY_STALE;
	}

	if (_is_uncertain(ret)) {
		unsigned waited = 0;
		ltfsmsg(ACL0013W, -ret, barcode ? barcode : "the cartridge", src, dst);
		for (;;) {
			r = _element_at(ch, dst, &ed);
			if (r < 0)
				goto stale;
			if (_holds(&ed, barcode))
				return _settle_move(ch, 0, src, dst, barcode, false);
			r = _element_at(ch, src, &es);
			if (r < 0)
				goto stale;
			if (_holds(&es, barcode)) {
				if (!allow_retry) {
					/* Still where it was and we may not repeat: nothing happened */
					_set_state(ch, src, CHANGER_TAPE_AVAILABLE);
					return ret;
				}
				/* Never ran: issue it again, once */
				r = _move(ch, src, dst);
				return _settle_move(ch, r, src, dst, barcode, false);
			}
			if (waited >= ch->opts.move_wait)
				break;
			sleep(1);
			waited++;
		}
		ltfsmsg(ACL0016W, barcode ? barcode : "the cartridge", ch->opts.move_wait);
		goto stale;
	}

	if (ret == -EDEV_SRC_EMPTY || ret == -EDEV_DEST_FULL) {
		bool explained = false;
		r = _element_at(ch, src, &es);
		if (r == 0 && ret == -EDEV_SRC_EMPTY && !es.full)
			explained = true;
		if (r == 0) {
			ltfs_thread_mutex_lock(&ch->cache_lock);
			_apply_element(ch, &es);
			ltfs_thread_mutex_unlock(&ch->cache_lock);
		}
		r = _element_at(ch, dst, &ed);
		if (r == 0 && ret == -EDEV_DEST_FULL && ed.full)
			explained = true;
		if (r == 0) {
			ltfs_thread_mutex_lock(&ch->cache_lock);
			_apply_element(ch, &ed);
			ltfs_thread_mutex_unlock(&ch->cache_lock);
			/* The earlier attempt did it after all (repeat of a move that had run) */
			if (ret == -EDEV_SRC_EMPTY && !es.full && barcode && _holds(&ed, barcode))
				return 0;
		}
		if (explained) {
			_set_state(ch, src, CHANGER_TAPE_AVAILABLE);
			return ret;
		}
		goto stale;
	}

	/* Any other failure: the cartridge did not move */
	_set_state(ch, src, CHANGER_TAPE_AVAILABLE);
	return ret;

stale:
	ltfsmsg(ACL0017E, barcode ? barcode : "the cartridge");
	r = _rescan(ch, false, 0);
	return r < 0 ? r : -LTFS_INVENTORY_STALE;
}

/* The changer must be answering before an operation starts */
static int _require_ready(struct changer *ch)
{
	int ret;

	if (ch->ready && !ch->stale)
		return 0;
	ret = _wait_ready(ch, ch->opts.ready_wait, 0);
	if (ret < 0)
		return ret;
	return _rescan(ch, false, 0);
}

/* A barcode that is not in the tables may be on the picker: wait, re-read, look again */
static int _lookup_tape(struct changer *ch, const char *barcode, struct changer_tape *out)
{
	struct changer_tape *t;
	int ret;
	bool rescanned = false;

	for (;;) {
		ltfs_thread_mutex_lock(&ch->cache_lock);
		t = _tape_by_barcode(ch, barcode);
		if (t) {
			*out = *t;
			ltfs_thread_mutex_unlock(&ch->cache_lock);
			return out->state == CHANGER_TAPE_DUPLICATE ? -LTFS_BARCODE_AMBIGUOUS : 0;
		}
		ltfs_thread_mutex_unlock(&ch->cache_lock);
		if (rescanned)
			return -LTFS_BARCODE_NOT_FOUND;
		if (ch->opts.move_wait)
			sleep(ch->opts.move_wait);
		ret = _rescan(ch, false, 0);
		if (ret < 0)
			return ret;
		rescanned = true;
	}
}

static int _lookup_drive(struct changer *ch, const char *serial, struct changer_drive *out)
{
	struct changer_drive *d;

	ltfs_thread_mutex_lock(&ch->cache_lock);
	d = _drive_by_serial(ch, serial);
	if (d)
		*out = *d;
	ltfs_thread_mutex_unlock(&ch->cache_lock);
	return d ? 0 : -LTFS_DRIVE_NOT_IN_LIBRARY;
}

/* Can this cartridge be picked up for a load or a swap? */
static int _loadable(const struct changer_tape *t)
{
	switch (t->state) {
		case CHANGER_TAPE_DUPLICATE:      return -LTFS_BARCODE_AMBIGUOUS;
		case CHANGER_TAPE_CLEANING:       return -LTFS_CLEANING_CARTRIDGE;
		case CHANGER_TAPE_NOT_ACCESSIBLE: return -EDEV_MAGAZINE_INACCESSIBLE;
		case CHANGER_TAPE_MOVING:         return -LTFS_INVENTORY_STALE;
		default: break;
	}
	if (t->where == CHANGER_ELEMENT_IMPORT_EXPORT)
		return -LTFS_TAPE_IN_IE;
	return 0;
}

/* First empty, accessible storage element at or after near */
static int _free_slot(struct changer *ch, uint16_t near, uint16_t *address)
{
	struct changer_element *el = NULL;
	size_t n = 0, i;
	uint32_t start = ch->info.storage_start, end = start + ch->info.storage_count;
	uint32_t at;
	int ret, pass;

	if (!ch->info.storage_count)
		return -LTFS_NO_FREE_SLOT;
	if (near < start || near >= end)
		near = start;

	for (pass = 0; pass < 2; pass++) {
		at = pass == 0 ? near : start;
		while (at < end) {
			uint16_t count = pass == 0 ? FREE_SLOT_WINDOW : FREE_SLOT_CHUNK;
			if (at + count > end)
				count = (uint16_t)(end - at);
			ret = _get_elements(ch, CHANGER_ELEMENT_STORAGE, (uint16_t)at, count, &el, &n, 0);
			if (ret < 0)
				return ret;
			for (i = 0; i < n; i++) {
				if (!el[i].full && el[i].accessible && !el[i].exception) {
					*address = el[i].address;
					free(el);
					return 0;
				}
			}
			free(el);
			el = NULL;
			if (pass == 0)
				break;			/* the window around the hint had nothing; sweep */
			at += count;
		}
	}
	return -LTFS_NO_FREE_SLOT;
}

/* Where a cartridge in a drive goes back to: its home, the source the device remembers, or a free slot */
static int _return_target(struct changer *ch, const struct changer_tape *t, const struct changer_element *drive_el,
						  uint16_t *dest)
{
	struct changer_element e;
	uint16_t home = t->home;
	int ret;

	if (!home && drive_el->source_valid && _type_of(ch, drive_el->source) == CHANGER_ELEMENT_STORAGE)
		home = drive_el->source;
	if (!home) {
		/* Loaded from the import/export station or by another host, and the device kept no storage source */
		ret = _free_slot(ch, 0, dest);
		if (ret < 0)
			return ret;
		ltfsmsg(ACL0020W, t->barcode[0] ? t->barcode : "the unlabeled cartridge", *dest);
		return 0;
	}

	ret = _element_at(ch, home, &e);
	if (ret < 0)
		return ret;
	ltfs_thread_mutex_lock(&ch->cache_lock);
	_apply_element(ch, &e);
	ltfs_thread_mutex_unlock(&ch->cache_lock);
	if (!e.full && e.accessible && !e.exception) {
		*dest = home;
		return 0;
	}
	ret = _free_slot(ch, home, dest);
	if (ret < 0)
		return ret;
	ltfsmsg(ACL0014W, home, t->barcode[0] ? t->barcode : "the unlabeled cartridge", *dest);
	return 0;
}

/* ---------------------------------------------------------------------- */
/* Public API                                                             */
/* ---------------------------------------------------------------------- */

static int _check_ops(const struct changer_ops *ops)
{
	if (!ops || !ops->open || !ops->close || !ops->test_unit_ready || !ops->get_info
		|| !ops->get_elements || !ops->move || !ops->exchange || !ops->scan
		|| !ops->prevent_medium_removal || !ops->allow_medium_removal)
		return -LTFS_PLUGIN_INCOMPLETE;
	return 0;
}

int changer_open(struct changer **out, const char *devname, struct changer_ops *ops,
				 const struct changer_opts *opts)
{
	struct changer *ch;
	int ret;

	CHECK_ARG_NULL(out, -LTFS_NULL_ARG);
	CHECK_ARG_NULL(devname, -LTFS_NULL_ARG);
	ret = _check_ops(ops);
	if (ret < 0) {
		ltfsmsg(ACL0001E, devname);
		return ret;
	}
	ltfs_request_trace(CHANGER_REQ_ENTER(REQ_CHG_OPEN), 0, 0);

	ch = calloc(1, sizeof(*ch));
	if (!ch)
		return -LTFS_NO_MEMORY;
	ch->backend = ops;
	ch->devname = strdup(devname);
	if (!ch->devname) {
		free(ch);
		return -LTFS_NO_MEMORY;
	}
	if (opts)
		ch->opts = *opts;
	if (!ch->opts.ready_wait)
		ch->opts.ready_wait = DEFAULT_READY_WAIT;
	if (!ch->opts.move_wait)
		ch->opts.move_wait = DEFAULT_MOVE_WAIT;
	ltfs_thread_mutex_init(&ch->cmd_lock);
	ltfs_thread_mutex_init(&ch->cache_lock);

	ret = ops->open(devname, &ch->backend_data);
	if (ret < 0) {
		ltfsmsg(ACL0019E, devname, ret);
		goto fail;
	}
	ret = ops->get_info(ch->backend_data, &ch->info);
	if (ret < 0) {
		ops->close(ch->backend_data);
		goto fail;
	}

	/* A library with its door open still opens; the tables wait for it */
	ret = _rescan(ch, false, 0);
	if (ret < 0 && ret != -LTFS_CHANGER_NOT_READY) {
		ops->close(ch->backend_data);
		goto fail;
	}
	*out = ch;
	ltfs_request_trace(CHANGER_REQ_EXIT(REQ_CHG_OPEN), 0, 0);
	return 0;

fail:
	ltfs_thread_mutex_destroy(&ch->cmd_lock);
	ltfs_thread_mutex_destroy(&ch->cache_lock);
	free(ch->tapes);
	free(ch->drives);
	free(ch->devname);
	free(ch);
	ltfs_request_trace(CHANGER_REQ_EXIT(REQ_CHG_OPEN), ret, 0);
	return ret;
}

void changer_close(struct changer *ch)
{
	if (!ch)
		return;
	ch->backend->close(ch->backend_data);
	ltfs_thread_mutex_destroy(&ch->cmd_lock);
	ltfs_thread_mutex_destroy(&ch->cache_lock);
	free(ch->tapes);
	free(ch->drives);
	free(ch->devname);
	free(ch);
}

void *changer_backend_handle(struct changer *ch)
{
	return ch ? ch->backend_data : NULL;
}

int changer_rescan(struct changer *ch, bool deep)
{
	int ret;

	CHECK_ARG_NULL(ch, -LTFS_NULL_ARG);
	ltfs_request_trace(CHANGER_REQ_ENTER(REQ_CHG_RESCAN), deep, 0);
	ltfs_thread_mutex_lock(&ch->cmd_lock);
	ret = _rescan(ch, deep, 0);
	ltfs_thread_mutex_unlock(&ch->cmd_lock);
	ltfs_request_trace(CHANGER_REQ_EXIT(REQ_CHG_RESCAN), ret, 0);
	return ret;
}

int changer_inventory(struct changer *ch, struct changer_inventory *out)
{
	CHECK_ARG_NULL(ch, -LTFS_NULL_ARG);
	CHECK_ARG_NULL(out, -LTFS_NULL_ARG);

	memset(out, 0, sizeof(*out));
	ltfs_thread_mutex_lock(&ch->cache_lock);
	out->info = ch->info;
	out->ready = ch->ready;
	out->not_ready_reason = ch->not_ready_reason;
	out->stale = ch->stale;
	out->inventory_time = ch->inventory_time;
	out->last_ua = ch->last_ua;
	out->last_ua_time = ch->last_ua_time;
	out->storage_free = ch->storage_free;
	out->storage_unusable = ch->storage_unusable;
	out->ie_free = ch->ie_free;
	out->n_tapes = ch->n_tapes;
	out->n_unlabeled = ch->n_unlabeled;
	out->n_drives = ch->n_drives;
	out->tapes = calloc(ch->n_tapes ? ch->n_tapes : 1, sizeof(*out->tapes));
	out->drives = calloc(ch->n_drives ? ch->n_drives : 1, sizeof(*out->drives));
	if (!out->tapes || !out->drives) {
		ltfs_thread_mutex_unlock(&ch->cache_lock);
		changer_inventory_free(out);
		return -LTFS_NO_MEMORY;
	}
	if (ch->n_tapes)
		memcpy(out->tapes, ch->tapes, ch->n_tapes * sizeof(*out->tapes));
	if (ch->n_drives)
		memcpy(out->drives, ch->drives, ch->n_drives * sizeof(*out->drives));
	ltfs_thread_mutex_unlock(&ch->cache_lock);
	return 0;
}

void changer_inventory_free(struct changer_inventory *inv)
{
	if (!inv)
		return;
	free(inv->tapes);
	free(inv->drives);
	inv->tapes = NULL;
	inv->drives = NULL;
	inv->n_tapes = inv->n_unlabeled = inv->n_drives = 0;
}

int changer_find_tape(struct changer *ch, const char *barcode, struct changer_tape *out)
{
	struct changer_tape *t;
	int ret;

	CHECK_ARG_NULL(ch, -LTFS_NULL_ARG);
	CHECK_ARG_NULL(barcode, -LTFS_NULL_ARG);
	CHECK_ARG_NULL(out, -LTFS_NULL_ARG);

	ltfs_thread_mutex_lock(&ch->cache_lock);
	t = _tape_by_barcode(ch, barcode);
	if (t)
		*out = *t;
	ret = !t ? -LTFS_BARCODE_NOT_FOUND : t->state == CHANGER_TAPE_DUPLICATE ? -LTFS_BARCODE_AMBIGUOUS : 0;
	ltfs_thread_mutex_unlock(&ch->cache_lock);
	return ret;
}

int changer_find_drive(struct changer *ch, const char *serial, struct changer_drive *out)
{
	CHECK_ARG_NULL(ch, -LTFS_NULL_ARG);
	CHECK_ARG_NULL(serial, -LTFS_NULL_ARG);
	CHECK_ARG_NULL(out, -LTFS_NULL_ARG);
	return _lookup_drive(ch, serial, out);
}

int changer_element_at(struct changer *ch, uint16_t address, struct changer_element *out)
{
	int ret;

	CHECK_ARG_NULL(ch, -LTFS_NULL_ARG);
	CHECK_ARG_NULL(out, -LTFS_NULL_ARG);
	ltfs_thread_mutex_lock(&ch->cmd_lock);
	ret = _element_at(ch, address, out);
	ltfs_thread_mutex_unlock(&ch->cmd_lock);
	return ret;
}

int changer_free_slot(struct changer *ch, uint16_t near, uint16_t *address)
{
	int ret;

	CHECK_ARG_NULL(ch, -LTFS_NULL_ARG);
	CHECK_ARG_NULL(address, -LTFS_NULL_ARG);
	ltfs_thread_mutex_lock(&ch->cmd_lock);
	ret = _free_slot(ch, near, address);
	ltfs_thread_mutex_unlock(&ch->cmd_lock);
	return ret;
}

int changer_wait_ready(struct changer *ch, unsigned seconds)
{
	int ret;

	CHECK_ARG_NULL(ch, -LTFS_NULL_ARG);
	ltfs_thread_mutex_lock(&ch->cmd_lock);
	ret = _wait_ready(ch, seconds, 0);
	if (ret == 0 && ch->stale)
		ret = _rescan(ch, false, 0);
	ltfs_thread_mutex_unlock(&ch->cmd_lock);
	return ret;
}

int changer_check_attention(struct changer *ch)
{
	int ret;

	CHECK_ARG_NULL(ch, -LTFS_NULL_ARG);
	ltfs_thread_mutex_lock(&ch->cmd_lock);
	ret = ch->backend->test_unit_ready(ch->backend_data);
	if (_is_ua(ret))
		ret = _after_ua(ch, ret, 0);
	else if (_is_not_ready(ret)) {
		_set_ready(ch, false, -ret, true);
		ret = -LTFS_CHANGER_NOT_READY;
	} else if (ret == 0 && (!ch->ready || ch->stale)) {
		ret = _rescan(ch, false, 0);	/* it came back without telling us */
	}
	ltfs_thread_mutex_unlock(&ch->cmd_lock);
	return ret;
}

/*
 * The operations below run their checks, one move, and the table update.
 * When the device recovers from a unit attention or a not-ready state in
 * the middle (RETRY_FROM_CHECKS), the public function runs them again from
 * the checks, once.
 */
#define OPERATION(req, body) \
	do { \
		int attempt_; \
		ltfs_request_trace(CHANGER_REQ_ENTER(req), 0, 0); \
		ltfs_thread_mutex_lock(&ch->cmd_lock); \
		for (attempt_ = 0; attempt_ < 2; attempt_++) { \
			ret = (body); \
			if (ret != RETRY_FROM_CHECKS) \
				break; \
		} \
		if (ret == RETRY_FROM_CHECKS) \
			ret = -LTFS_INVENTORY_STALE; \
		ltfs_thread_mutex_unlock(&ch->cmd_lock); \
		ltfs_request_trace(CHANGER_REQ_EXIT(req), ret, 0); \
	} while (0)

/* Load: storage -> drive */
static int _load_once(struct changer *ch, const char *barcode, const char *serial)
{
	struct changer_tape t;
	struct changer_drive d;
	int ret;

	ret = _require_ready(ch);
	if (ret < 0)
		return ret;
	ret = _lookup_drive(ch, serial, &d);
	if (ret < 0)
		return ret;
	ret = _lookup_tape(ch, barcode, &t);
	if (ret < 0)
		return ret;
	if (t.where == CHANGER_ELEMENT_DATA_TRANSFER)
		return t.address == d.address ? 0 : -LTFS_TAPE_IN_DRIVE;
	ret = _loadable(&t);
	if (ret < 0)
		return ret;
	if (d.full)
		return -LTFS_DRIVE_OCCUPIED;

	ret = _expect(ch, t.address, true, barcode, NULL);
	if (ret < 0)
		return ret;
	ret = _expect(ch, d.address, false, NULL, NULL);
	if (ret < 0)
		return ret == -LTFS_ELEMENT_FULL ? -LTFS_DRIVE_OCCUPIED : ret;

	_set_state(ch, t.address, CHANGER_TAPE_MOVING);
	ret = _move(ch, t.address, d.address);
	ret = _settle_move(ch, ret, t.address, d.address, barcode, true);
	return ret == -EDEV_DEST_FULL ? -LTFS_DRIVE_OCCUPIED : ret;
}

int changer_load(struct changer *ch, const char *barcode, const char *serial)
{
	int ret;

	CHECK_ARG_NULL(ch, -LTFS_NULL_ARG);
	CHECK_ARG_NULL(barcode, -LTFS_NULL_ARG);
	CHECK_ARG_NULL(serial, -LTFS_NULL_ARG);
	OPERATION(REQ_CHG_LOAD, _load_once(ch, barcode, serial));
	return ret;
}

/* The cartridge in a drive, from a fresh read of the drive element */
static int _tape_in_drive(struct changer *ch, const struct changer_drive *d, struct changer_tape *t,
						  struct changer_element *drive_el)
{
	struct changer_tape *tp;
	int ret;

	ret = _expect(ch, d->address, true, NULL, drive_el);
	if (ret < 0)
		return ret == -LTFS_ELEMENT_EMPTY ? -LTFS_DRIVE_EMPTY : ret;
	ltfs_thread_mutex_lock(&ch->cache_lock);
	ret = _apply_element(ch, drive_el);
	tp = ret == 0 ? _tape_at(ch, d->address) : NULL;
	if (tp)
		*t = *tp;
	ltfs_thread_mutex_unlock(&ch->cache_lock);
	if (ret < 0)
		return ret;
	return tp ? 0 : -LTFS_DRIVE_EMPTY;
}

/* Return: drive -> home */
static int _return_once(struct changer *ch, const char *serial)
{
	struct changer_drive d;
	struct changer_tape t;
	struct changer_element drive_el;
	uint16_t dest;
	int ret;

	ret = _require_ready(ch);
	if (ret < 0)
		return ret;
	ret = _lookup_drive(ch, serial, &d);
	if (ret < 0)
		return ret;
	ret = _tape_in_drive(ch, &d, &t, &drive_el);
	if (ret < 0)
		return ret;
	ret = _return_target(ch, &t, &drive_el, &dest);
	if (ret < 0)
		return ret;
	ret = _expect(ch, dest, false, NULL, NULL);
	if (ret < 0)
		return ret;

	_set_state(ch, d.address, CHANGER_TAPE_MOVING);
	ret = _move(ch, d.address, dest);
	return _settle_move(ch, ret, d.address, dest, t.barcode[0] ? t.barcode : NULL, true);
}

int changer_return(struct changer *ch, const char *serial)
{
	int ret;

	CHECK_ARG_NULL(ch, -LTFS_NULL_ARG);
	CHECK_ARG_NULL(serial, -LTFS_NULL_ARG);
	OPERATION(REQ_CHG_RETURN, _return_once(ch, serial));
	return ret;
}

/* Swap: the cartridge in the drive goes home, the named one takes its place */
static int _swap_once(struct changer *ch, const char *barcode, const char *serial)
{
	struct changer_drive d;
	struct changer_tape x, y;
	struct changer_element drive_el;
	const char *ybc;
	uint16_t dest2;
	int ret;

	ret = _require_ready(ch);
	if (ret < 0)
		return ret;
	ret = _lookup_drive(ch, serial, &d);
	if (ret < 0)
		return ret;
	if (!d.full)
		return _load_once(ch, barcode, serial);	/* nothing to return */
	ret = _lookup_tape(ch, barcode, &x);
	if (ret < 0)
		return ret;
	if (x.where == CHANGER_ELEMENT_DATA_TRANSFER)
		return x.address == d.address ? 0 : -LTFS_TAPE_IN_DRIVE;
	ret = _loadable(&x);
	if (ret < 0)
		return ret;

	/* The three elements: X's slot, the drive with Y, and where Y goes */
	ret = _expect(ch, x.address, true, barcode, NULL);
	if (ret < 0)
		return ret;
	ret = _tape_in_drive(ch, &d, &y, &drive_el);
	if (ret < 0)
		return ret;
	ybc = y.barcode[0] ? y.barcode : NULL;
	ret = _return_target(ch, &y, &drive_el, &dest2);
	if (ret < 0)
		return ret;
	ret = _expect(ch, dest2, false, NULL, NULL);
	if (ret < 0)
		return ret;

	_set_state(ch, x.address, CHANGER_TAPE_MOVING);
	_set_state(ch, d.address, CHANGER_TAPE_MOVING);

	if (ch->info.exchange) {
		ret = _exchange(ch, x.address, d.address, dest2);
		if (ret == -EDEV_UNSUPPORTED_FUNCTION || ret == -EDEV_UNSUPPORETD_COMMAND) {
			ltfsmsg(ACL0015I, ch->devname);
			ch->info.exchange = false;
		} else if (ret == 0) {
			bool ok;
			ltfs_thread_mutex_lock(&ch->cache_lock);
			ok = _moved(ch, d.address, dest2, ybc);
			ok = _moved(ch, x.address, d.address, barcode) && ok;
			ltfs_thread_mutex_unlock(&ch->cache_lock);
			if (ok)
				return 0;
			ltfsmsg(ACL0017E, barcode);
			ret = _rescan(ch, false, 0);
			return ret < 0 ? ret : -LTFS_INVENTORY_STALE;
		} else if (ret == RETRY_FROM_CHECKS) {
			_set_state(ch, x.address, CHANGER_TAPE_AVAILABLE);
			_set_state(ch, d.address, CHANGER_TAPE_LOADED);
			return ret;
		} else if (_is_uncertain(ret)) {
			/* Settle each half from what the elements say; neither is repeated */
			ret = _settle_move(ch, ret, d.address, dest2, ybc, false);
			if (ret == 0)
				ret = _settle_move(ch, -EDEV_NEED_FAILOVER, x.address, d.address, barcode, false);
			else
				_set_state(ch, x.address, CHANGER_TAPE_AVAILABLE);
			return ret;
		} else {
			ret = _settle_move(ch, ret, d.address, dest2, ybc, false);
			_set_state(ch, x.address, CHANGER_TAPE_AVAILABLE);
			return ret;
		}
	}

	/* Two moves: Y out first, then X in */
	ret = _move(ch, d.address, dest2);
	ret = _settle_move(ch, ret, d.address, dest2, ybc, true);
	if (ret != 0) {
		_set_state(ch, x.address, CHANGER_TAPE_AVAILABLE);
		return ret;
	}
	ret = _move(ch, x.address, d.address);
	return _settle_move(ch, ret, x.address, d.address, barcode, true);
}

int changer_swap(struct changer *ch, const char *barcode, const char *serial)
{
	int ret;

	CHECK_ARG_NULL(ch, -LTFS_NULL_ARG);
	CHECK_ARG_NULL(barcode, -LTFS_NULL_ARG);
	CHECK_ARG_NULL(serial, -LTFS_NULL_ARG);
	OPERATION(REQ_CHG_SWAP, _swap_once(ch, barcode, serial));
	return ret;
}

/* Export: storage -> a free import/export element */
static int _export_once(struct changer *ch, const char *barcode)
{
	struct changer_tape t;
	struct changer_element *el = NULL;
	size_t n = 0, i;
	uint16_t dest = 0;
	bool any_usable = false;
	int ret;

	ret = _require_ready(ch);
	if (ret < 0)
		return ret;
	ret = _lookup_tape(ch, barcode, &t);
	if (ret < 0)
		return ret;
	if (t.where == CHANGER_ELEMENT_IMPORT_EXPORT)
		return 0;
	if (t.where == CHANGER_ELEMENT_DATA_TRANSFER)
		return -LTFS_TAPE_IN_DRIVE;
	ret = _loadable(&t);
	if (ret < 0)
		return ret;

	ret = _get_elements(ch, CHANGER_ELEMENT_IMPORT_EXPORT, 0, 0, &el, &n, 0);
	if (ret < 0)
		return ret;
	ltfs_thread_mutex_lock(&ch->cache_lock);
	for (i = 0; i < n; i++) {
		_apply_element(ch, &el[i]);
		if (el[i].accessible && !el[i].exception) {
			any_usable = true;
			if (!el[i].full && !dest)
				dest = el[i].address;
		}
	}
	ltfs_thread_mutex_unlock(&ch->cache_lock);
	free(el);
	if (!dest)
		return any_usable ? -LTFS_NO_FREE_SLOT : -LTFS_IE_NOT_ACCESSIBLE;

	ret = _expect(ch, t.address, true, barcode, NULL);
	if (ret < 0)
		return ret;
	_set_state(ch, t.address, CHANGER_TAPE_MOVING);
	ret = _move(ch, t.address, dest);
	ret = _settle_move(ch, ret, t.address, dest, barcode, true);
	return ret == -EDEV_MAGAZINE_INACCESSIBLE ? -LTFS_IE_NOT_ACCESSIBLE : ret;
}

int changer_export(struct changer *ch, const char *barcode)
{
	int ret;

	CHECK_ARG_NULL(ch, -LTFS_NULL_ARG);
	CHECK_ARG_NULL(barcode, -LTFS_NULL_ARG);
	OPERATION(REQ_CHG_EXPORT, _export_once(ch, barcode));
	return ret;
}

/* Import: import/export -> a free storage slot */
static int _import_once(struct changer *ch, const char *barcode)
{
	struct changer_tape t;
	uint16_t dest;
	int ret;

	ret = _require_ready(ch);
	if (ret < 0)
		return ret;
	ret = _lookup_tape(ch, barcode, &t);
	if (ret < 0)
		return ret;
	if (t.where == CHANGER_ELEMENT_STORAGE)
		return 0;
	if (t.where != CHANGER_ELEMENT_IMPORT_EXPORT)
		return -LTFS_TAPE_IN_DRIVE;
	if (t.state == CHANGER_TAPE_DUPLICATE)
		return -LTFS_BARCODE_AMBIGUOUS;
	if (t.state == CHANGER_TAPE_NOT_ACCESSIBLE)
		return -LTFS_IE_NOT_ACCESSIBLE;

	ret = _free_slot(ch, ch->info.storage_start, &dest);
	if (ret < 0)
		return ret;
	ret = _expect(ch, dest, false, NULL, NULL);
	if (ret < 0)
		return ret;
	ret = _expect(ch, t.address, true, barcode, NULL);
	if (ret < 0)
		return ret == -EDEV_MAGAZINE_INACCESSIBLE ? -LTFS_IE_NOT_ACCESSIBLE : ret;
	_set_state(ch, t.address, CHANGER_TAPE_MOVING);
	ret = _move(ch, t.address, dest);
	ret = _settle_move(ch, ret, t.address, dest, barcode, true);
	return ret == -EDEV_MAGAZINE_INACCESSIBLE ? -LTFS_IE_NOT_ACCESSIBLE : ret;
}

int changer_import(struct changer *ch, const char *barcode)
{
	int ret;

	CHECK_ARG_NULL(ch, -LTFS_NULL_ARG);
	CHECK_ARG_NULL(barcode, -LTFS_NULL_ARG);
	OPERATION(REQ_CHG_IMPORT, _import_once(ch, barcode));
	return ret;
}
