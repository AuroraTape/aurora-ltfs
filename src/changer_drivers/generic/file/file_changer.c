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
** FILE NAME:       changer_drivers/generic/file/file_changer.c
**
** DESCRIPTION:     A medium changer emulated on a directory, for tests without
**                  hardware. The layout:
**
**                    <libdir>/library.conf        identity, address assignment, features, delays
**                    <libdir>/state.conf          written by the plugin: source addresses, door
**                    <libdir>/inject              one-shot faults a test wants, consumed line by line
**                    <libdir>/faults              lasting element faults: "<address> inaccessible" or
**                                                 "<address> <ASCASCQ>" (except bit in READ ELEMENT
**                                                 STATUS, MOVE / EXCHANGE touching it fails with 05/that)
**                    <libdir>/slots/<address>     storage element: the cartridge name, or empty
**                    <libdir>/ie/<address>        import/export element, same content
**                    <libdir>/drives/Drive_<SERIAL>.<PRODUCT>
**                                                 data transfer element in the format of the tape
**                                                 file backend: "../cartridges/<name>" or "empty",
**                                                 NUL padded to 36 bytes
**                    <libdir>/cartridges/<name>/  the tape file backend directories
**
**                  A MOVE empties the source, sleeps move_ms and writes the
**                  destination, so a reader in between sees the cartridge in
**                  neither place, as with a real picker. The tape file
**                  backend opened on a drive file follows the cartridge
**                  without any change on its side.
**
*************************************************************************************
*/

#include <ctype.h>
#include <dirent.h>
#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <time.h>
#include <unistd.h>
#include <sys/stat.h>

#include "libltfs/ltfs.h"
#include "libltfs/ltfs_error.h"
#include "libltfs/ltfslogging.h"
#include "libaltfschanger/changer_ops.h"
#include "changer_drivers/smc_sense.h"

#define FILE_CHANGER_CONF        "library.conf"
#define FILE_CHANGER_STATE       "state.conf"
#define FILE_CHANGER_INJECT      "inject"
#define FILE_CHANGER_FAULTS      "faults"
#define FILE_CHANGER_SLOTS       "slots"
#define FILE_CHANGER_IE          "ie"
#define FILE_CHANGER_DRIVES      "drives"
#define FILE_CHANGER_CARTRIDGES  "cartridges"
#define FILE_CHANGER_DRIVE_PREFIX "Drive_"
#define FILE_CHANGER_DRIVE_LINK  (36)	/* BARCODE_SIZE of the tape file backend: the drive file is exactly this long */
#define FILE_CHANGER_EMPTY       "empty"
#define FILE_CHANGER_ROOT_ENV    "ALTFS_FILE_CHANGER_ROOT"
#define FILE_CHANGER_LINE_MAX    (1024)

struct file_changer {
	char               *dir;
	struct changer_info info;
	bool                prevent_supported;
	unsigned int        move_ms;
	unsigned int        inventory_ms;
	uint16_t            dt_start;	/* from the conf: drives are numbered from here in name order */
	uint16_t            transport_start;
	uint16_t            transport_count;
};

/* Message bundle */
extern char changer_generic_file_dat[];

const char *changer_get_message_bundle_name(void **message_data)
{
	*message_data = changer_generic_file_dat;
	return "changer_generic_file";
}

/* ---------------------------------------------------------------------- */
/* Small file helpers                                                     */
/* ---------------------------------------------------------------------- */

static void _path(char *out, size_t size, const char *dir, const char *a, const char *b)
{
	if (b)
		snprintf(out, size, "%s/%s/%s", dir, a, b);
	else
		snprintf(out, size, "%s/%s", dir, a);
}

static bool _is_dir(const char *path)
{
	struct stat st;
	return stat(path, &st) == 0 && S_ISDIR(st.st_mode);
}

static bool _is_file(const char *path)
{
	struct stat st;
	return stat(path, &st) == 0 && S_ISREG(st.st_mode);
}

static void _trim(char *s)
{
	size_t n = strlen(s);
	while (n > 0 && (s[n - 1] == '\n' || s[n - 1] == '\r' || s[n - 1] == ' ' || s[n - 1] == '\t'))
		s[--n] = '\0';
	while (*s == ' ' || *s == '\t') {
		memmove(s, s + 1, strlen(s));
	}
}

/* First line of a file, trimmed. An absent or empty file gives "". */
static int _read_first_line(const char *path, char *out, size_t size)
{
	FILE *f = fopen(path, "r");

	out[0] = '\0';
	if (!f) {
		if (errno == ENOENT)
			return 0;
		return -EDEV_DEVICE_UNOPENABLE;
	}
	if (!fgets(out, (int)size, f))
		out[0] = '\0';
	fclose(f);
	_trim(out);
	return 0;
}

static int _write_text(const char *path, const char *text)
{
	FILE *f = fopen(path, "w");
	if (!f) {
		ltfsmsg(ACF0004E, path, errno);
		return -EDEV_DEVICE_UNOPENABLE;
	}
	if (text && *text)
		fprintf(f, "%s\n", text);
	fclose(f);
	return 0;
}

/* Look a key up in a "key = value" file. Returns true when found. */
static bool _conf_get(const char *path, const char *key, char *value, size_t size)
{
	FILE *f = fopen(path, "r");
	char line[FILE_CHANGER_LINE_MAX];
	bool found = false;

	if (!f)
		return false;
	while (fgets(line, sizeof(line), f)) {
		char *eq, *k, *v;
		_trim(line);
		if (!line[0] || line[0] == '#')
			continue;
		eq = strchr(line, '=');
		if (!eq)
			continue;
		*eq = '\0';
		k = line;
		v = eq + 1;
		_trim(k);
		_trim(v);
		if (!strcmp(k, key)) {
			strncpy(value, v, size - 1);
			value[size - 1] = '\0';
			found = true;
			break;
		}
	}
	fclose(f);
	return found;
}

/* Set or remove (value NULL) a key in a "key = value" file, keeping the other lines */
static int _conf_set(const char *path, const char *key, const char *value)
{
	FILE *in, *out;
	char tmp[PATH_MAX + 8];
	char line[FILE_CHANGER_LINE_MAX];
	bool written = false;

	snprintf(tmp, sizeof(tmp), "%s.tmp", path);
	out = fopen(tmp, "w");
	if (!out) {
		ltfsmsg(ACF0004E, tmp, errno);
		return -EDEV_DEVICE_UNOPENABLE;
	}

	in = fopen(path, "r");
	if (in) {
		while (fgets(line, sizeof(line), in)) {
			char probe[FILE_CHANGER_LINE_MAX];
			char *eq;
			strncpy(probe, line, sizeof(probe) - 1);
			probe[sizeof(probe) - 1] = '\0';
			_trim(probe);
			eq = strchr(probe, '=');
			if (eq) {
				*eq = '\0';
				_trim(probe);
				if (!strcmp(probe, key)) {
					if (value && !written) {
						fprintf(out, "%s = %s\n", key, value);
						written = true;
					}
					continue;
				}
			}
			fputs(line, out);
		}
		fclose(in);
	}
	if (value && !written)
		fprintf(out, "%s = %s\n", key, value);
	fclose(out);

	if (rename(tmp, path) < 0) {
		ltfsmsg(ACF0004E, path, errno);
		unlink(tmp);
		return -EDEV_DEVICE_UNOPENABLE;
	}
	return 0;
}

static bool _conf_bool(const char *path, const char *key, bool dflt)
{
	char v[64];
	if (!_conf_get(path, key, v, sizeof(v)))
		return dflt;
	return !(!strcasecmp(v, "false") || !strcasecmp(v, "no") || !strcmp(v, "0") || !strcasecmp(v, "off"));
}

static unsigned long _conf_ulong(const char *path, const char *key, unsigned long dflt)
{
	char v[64];
	if (!_conf_get(path, key, v, sizeof(v)))
		return dflt;
	return strtoul(v, NULL, 0);
}

static void _sleep_ms(unsigned int ms)
{
	struct timespec ts;
	if (!ms)
		return;
	ts.tv_sec = ms / 1000;
	ts.tv_nsec = (long)(ms % 1000) * 1000000L;
	nanosleep(&ts, NULL);
}

/* A name the layer accepts as a barcode: upper case letters and digits */
static bool _is_barcode(const char *s)
{
	if (!*s || strlen(s) > CHANGER_VOLTAG_MAX)
		return false;
	for (; *s; s++)
		if (!(isupper((unsigned char)*s) || isdigit((unsigned char)*s)))
			return false;
	return true;
}

/* ---------------------------------------------------------------------- */
/* Fault injection and the not-ready state                                */
/* ---------------------------------------------------------------------- */

/*
 * The inject file holds one fault per line, consumed when it fires:
 *   ua <SK/ASCQ>              the next command fails with that unit attention (or any sense)
 *   fail <command> <SK/ASCQ>  the next <command> fails with that sense, not executed
 *   lost <command>            the next <command> reports a lost connection, not executed
 *   lost move_after           the next move is executed and then reports a lost connection
 *   door_open <seconds>       the library is not ready for that long
 */
static int _consume_inject(struct file_changer *priv, const char *command, bool *lost_after)
{
	char path[PATH_MAX], tmp[PATH_MAX + 8];
	char line[FILE_CHANGER_LINE_MAX];
	FILE *in, *out;
	int ret = 0;
	bool fired = false;

	*lost_after = false;
	_path(path, sizeof(path), priv->dir, FILE_CHANGER_INJECT, NULL);
	in = fopen(path, "r");
	if (!in)
		return 0;
	snprintf(tmp, sizeof(tmp), "%s.tmp", path);
	out = fopen(tmp, "w");
	if (!out) {
		fclose(in);
		return 0;
	}

	while (fgets(line, sizeof(line), in)) {
		char copy[FILE_CHANGER_LINE_MAX];
		char *what, *arg1, *arg2, *save = NULL;
		uint32_t sense;

		if (fired) {
			fputs(line, out);
			continue;
		}
		strncpy(copy, line, sizeof(copy) - 1);
		copy[sizeof(copy) - 1] = '\0';
		_trim(copy);
		if (!copy[0] || copy[0] == '#') {
			fputs(line, out);
			continue;
		}
		what = strtok_r(copy, " \t", &save);
		arg1 = strtok_r(NULL, " \t", &save);
		arg2 = strtok_r(NULL, " \t", &save);

		if (!strcmp(what, "door_open") && arg1) {
			char until[32];
			char state[PATH_MAX];
			snprintf(until, sizeof(until), "%lld", (long long)time(NULL) + atol(arg1));
			_path(state, sizeof(state), priv->dir, FILE_CHANGER_STATE, NULL);
			_conf_set(state, "not_ready_until", until);
			ltfsmsg(ACF0005I, "door_open", "library");
			fired = true;
			continue;
		}
		if (!strcmp(what, "ua") && arg1) {
			if (smc_parse_sense_string(arg1, &sense) == 0) {
				ret = smc_sense_to_errorcode(sense, NULL);
				ltfsmsg(ACF0005I, arg1, command);
				fired = true;
				continue;
			}
		}
		if (!strcmp(what, "fail") && arg1 && arg2 && !strcmp(arg1, command)) {
			if (smc_parse_sense_string(arg2, &sense) == 0) {
				ret = smc_sense_to_errorcode(sense, NULL);
				ltfsmsg(ACF0005I, arg2, command);
				fired = true;
				continue;
			}
		}
		if (!strcmp(what, "lost") && arg1) {
			if (!strcmp(arg1, command)) {
				ret = -EDEV_CONNECTION_LOST;
				ltfsmsg(ACF0005I, "lost", command);
				fired = true;
				continue;
			}
			if (!strcmp(arg1, "move_after") && !strcmp(command, "move")) {
				*lost_after = true;
				ltfsmsg(ACF0005I, "lost after", command);
				fired = true;
				continue;
			}
		}
		fputs(line, out);
	}
	fclose(in);
	fclose(out);
	if (fired)
		rename(tmp, path);
	else
		unlink(tmp);

	return ret;
}

static bool _not_ready(struct file_changer *priv)
{
	char state[PATH_MAX];
	unsigned long until;

	_path(state, sizeof(state), priv->dir, FILE_CHANGER_STATE, NULL);
	until = _conf_ulong(state, "not_ready_until", 0);
	return until > (unsigned long)time(NULL);
}

/* Every command starts here: injected faults first, then the door */
static int _enter(struct file_changer *priv, const char *command, bool *lost_after)
{
	bool dummy;
	int ret = _consume_inject(priv, command, lost_after ? lost_after : &dummy);
	if (ret < 0)
		return ret;
	if (_not_ready(priv))
		return -EDEV_DOOR_OPEN;
	return 0;
}

/* ---------------------------------------------------------------------- */
/* Elements                                                               */
/* ---------------------------------------------------------------------- */

/*
 * One element. The names are single path components, so NAME_MAX is enough;
 * a 60,000 slot library is read into memory on every command and PATH_MAX
 * sized fields would cost it half a gigabyte.
 */
struct file_element {
	struct changer_element e;
	char token[NAME_MAX + 1];	/* cartridge directory name when full */
	char name[NAME_MAX + 1];	/* the element file under subdir */
	const char *subdir;			/* slots, ie or drives */
};

static int _cmp_element(const void *a, const void *b)
{
	const struct file_element *x = a, *y = b;
	return (int)x->e.address - (int)y->e.address;
}

static int _cmp_name(const void *a, const void *b)
{
	return strcmp(*(char * const *)a, *(char * const *)b);
}

/* Names in a directory, sorted. The caller frees the array and its strings. */
static int _list_dir(const char *path, char ***names, size_t *n)
{
	DIR *dp;
	struct dirent *entry;
	char **list = NULL;
	size_t count = 0;

	*names = NULL;
	*n = 0;
	dp = opendir(path);
	if (!dp)
		return errno == ENOENT ? 0 : -EDEV_DEVICE_UNOPENABLE;
	while ((entry = readdir(dp)) != NULL) {
		char **grown;
		if (entry->d_name[0] == '.')
			continue;
		if (strlen(entry->d_name) > 4 && !strcmp(entry->d_name + strlen(entry->d_name) - 4, ".tmp"))
			continue;
		grown = realloc(list, (count + 1) * sizeof(char *));
		if (!grown) {
			closedir(dp);
			while (count--)
				free(list[count]);
			free(list);
			return -EDEV_NO_MEMORY;
		}
		list = grown;
		list[count] = strdup(entry->d_name);
		if (!list[count]) {
			closedir(dp);
			while (count--)
				free(list[count]);
			free(list);
			return -EDEV_NO_MEMORY;
		}
		count++;
	}
	closedir(dp);
	if (count)
		qsort(list, count, sizeof(char *), _cmp_name);
	*names = list;
	*n = count;
	return 0;
}

static void _free_names(char **names, size_t n)
{
	while (n--)
		free(names[n]);
	free(names);
}

static void _set_token(struct file_changer *priv, struct file_element *fe, const char *token)
{
	strncpy(fe->token, token, sizeof(fe->token) - 1);
	fe->token[sizeof(fe->token) - 1] = '\0';
	fe->e.full = fe->token[0] != '\0';
	fe->e.voltag_valid = false;
	fe->e.voltag[0] = '\0';
	if (fe->e.full && priv->info.barcode_reader && _is_barcode(fe->token)) {
		strncpy(fe->e.voltag, fe->token, CHANGER_VOLTAG_MAX);
		fe->e.voltag[CHANGER_VOLTAG_MAX] = '\0';
		fe->e.voltag_valid = true;
	}
}

static void _set_source(struct file_changer *priv, struct file_element *fe)
{
	char state[PATH_MAX], key[64], v[64];

	fe->e.source_valid = false;
	fe->e.source = 0;
	if (!fe->e.full)
		return;
	_path(state, sizeof(state), priv->dir, FILE_CHANGER_STATE, NULL);
	snprintf(key, sizeof(key), "source.%u", fe->e.address);
	if (_conf_get(state, key, v, sizeof(v))) {
		fe->e.source = (uint16_t)strtoul(v, NULL, 0);
		fe->e.source_valid = true;
	}
}

/* Cartridge name out of a drive file: "../cartridges/<name>" or "empty" */
static int _drive_token(const char *path, char *token, size_t size)
{
	char buf[FILE_CHANGER_DRIVE_LINK + 1];
	FILE *f = fopen(path, "r");
	size_t n;
	const char *slash;

	token[0] = '\0';
	if (!f)
		return -EDEV_DEVICE_UNOPENABLE;
	n = fread(buf, 1, FILE_CHANGER_DRIVE_LINK, f);
	fclose(f);
	buf[n] = '\0';
	_trim(buf);
	if (!buf[0] || !strcmp(buf, FILE_CHANGER_EMPTY))
		return 0;
	slash = strrchr(buf, '/');
	strncpy(token, slash ? slash + 1 : buf, size - 1);
	token[size - 1] = '\0';
	return 0;
}

static int _write_drive_file(const char *path, const char *token)
{
	char buf[FILE_CHANGER_DRIVE_LINK];
	FILE *f;
	int len;

	memset(buf, 0, sizeof(buf));
	if (token && *token)
		len = snprintf(buf, sizeof(buf), "../%s/%s", FILE_CHANGER_CARTRIDGES, token);
	else
		len = snprintf(buf, sizeof(buf), "%s", FILE_CHANGER_EMPTY);
	if (len < 0 || len >= (int)sizeof(buf)) {
		ltfsmsg(ACF0007E, token ? token : "", (int)sizeof(buf) - 1 - (int)strlen("../" FILE_CHANGER_CARTRIDGES "/"));
		return -EDEV_INVALID_ARG;
	}

	f = fopen(path, "w");
	if (!f) {
		ltfsmsg(ACF0004E, path, errno);
		return -EDEV_DEVICE_UNOPENABLE;
	}
	if (fwrite(buf, 1, sizeof(buf), f) != sizeof(buf)) {
		fclose(f);
		ltfsmsg(ACF0004E, path, errno);
		return -EDEV_DEVICE_UNOPENABLE;
	}
	fclose(f);
	return 0;
}

/* Serial out of "Drive_<SERIAL>.<PRODUCT>" */
static void _drive_serial(const char *name, char *serial, size_t size)
{
	const char *start = name + strlen(FILE_CHANGER_DRIVE_PREFIX);
	const char *dot = strchr(start, '.');
	size_t n = dot ? (size_t)(dot - start) : strlen(start);

	if (n > size - 1)
		n = size - 1;
	memcpy(serial, start, n);
	serial[n] = '\0';
}

/* Every element of the library, sorted by address. The caller frees the array. */
/* ---------------------------------------------------------------------- */
/* Lasting element faults (the faults file)                               */
/* ---------------------------------------------------------------------- */

struct file_fault {
	uint16_t address;
	bool     inaccessible;	/**< Access bit cleared */
	uint8_t  asc, ascq;		/**< Except bit set with this sense, 0/0 when not */
};

/*
 * One fault per line: "<address> inaccessible" or "<address> <ASCASCQ>"
 * (four hex digits, e.g. 3B18 for element disabled, 3B1A for a removed
 * drive). Comments start with #. A malformed line is ignored.
 */
static int _load_faults(struct file_changer *priv, struct file_fault **out, size_t *n_out)
{
	char path[PATH_MAX];
	char line[FILE_CHANGER_LINE_MAX];
	struct file_fault *list = NULL;
	size_t n = 0, cap = 0;
	FILE *f;

	*out = NULL;
	*n_out = 0;
	_path(path, sizeof(path), priv->dir, FILE_CHANGER_FAULTS, NULL);
	f = fopen(path, "r");
	if (!f)
		return 0;
	while (fgets(line, sizeof(line), f)) {
		char *save, *addr_s, *what, *end;
		unsigned long addr, sense;
		struct file_fault fault;

		_trim(line);
		if (!line[0] || line[0] == '#')
			continue;
		addr_s = strtok_r(line, " \t", &save);
		what = strtok_r(NULL, " \t", &save);
		if (!addr_s || !what)
			continue;
		addr = strtoul(addr_s, &end, 10);
		if (*end || addr > 0xFFFF)
			continue;
		memset(&fault, 0, sizeof(fault));
		fault.address = (uint16_t)addr;
		if (!strcasecmp(what, "inaccessible")) {
			fault.inaccessible = true;
		} else {
			sense = strtoul(what, &end, 16);
			if (*end || sense > 0xFFFF || strlen(what) != 4)
				continue;
			fault.asc = (uint8_t)(sense >> 8);
			fault.ascq = (uint8_t)(sense & 0xFF);
		}
		if (n == cap) {
			size_t newcap = cap ? cap * 2 : 8;
			struct file_fault *grown = realloc(list, newcap * sizeof(*list));
			if (!grown) {
				free(list);
				fclose(f);
				return -EDEV_NO_MEMORY;
			}
			list = grown;
			cap = newcap;
		}
		list[n++] = fault;
	}
	fclose(f);
	*out = list;
	*n_out = n;
	return 0;
}

/* Mark the elements the faults file names */
static int _apply_faults(struct file_changer *priv, struct file_element *list, size_t n)
{
	struct file_fault *faults;
	size_t nf, i, j;
	int ret;

	ret = _load_faults(priv, &faults, &nf);
	if (ret < 0)
		return ret;
	for (i = 0; i < nf; i++) {
		for (j = 0; j < n; j++) {
			if (list[j].e.address != faults[i].address)
				continue;
			if (faults[i].inaccessible)
				list[j].e.accessible = false;
			if (faults[i].asc || faults[i].ascq) {
				list[j].e.exception = true;
				list[j].e.asc = faults[i].asc;
				list[j].e.ascq = faults[i].ascq;
			}
		}
	}
	free(faults);
	return 0;
}

/* The error a MOVE or EXCHANGE touching a faulty element gets, 0 when the element is fine */
static int _element_fault(const struct file_element *fe, const char *command)
{
	char desc[16];
	int ret;

	if (!fe->e.accessible) {
		ltfsmsg(ACF0009I, fe->e.address, "inaccessible", command);
		return -EDEV_MAGAZINE_INACCESSIBLE;
	}
	if (fe->e.exception) {
		snprintf(desc, sizeof(desc), "05/%02X%02X", fe->e.asc, fe->e.ascq);
		ret = smc_sense_to_errorcode(0x050000 | ((uint32_t)fe->e.asc << 8) | fe->e.ascq, NULL);
		ltfsmsg(ACF0009I, fe->e.address, desc, command);
		return ret;
	}
	return 0;
}

/* The file of an element */
static void _element_path(const struct file_changer *priv, const struct file_element *fe, char *path, size_t size)
{
	_path(path, size, priv->dir, fe->subdir, fe->name);
}

static int _load_elements(struct file_changer *priv, struct file_element **out, size_t *n_out)
{
	struct file_element *list = NULL;
	size_t n = 0, cap = 0, i, count;
	char **names = NULL;
	char dir[PATH_MAX], path[PATH_MAX];
	int ret;
	uint16_t addr;
	static const struct { const char *subdir; enum changer_element_type type; } kinds[] = {
		{ FILE_CHANGER_SLOTS, CHANGER_ELEMENT_STORAGE },
		{ FILE_CHANGER_IE,    CHANGER_ELEMENT_IMPORT_EXPORT },
	};
	size_t k;

#define GROW() do { \
		if (n == cap) { \
			size_t newcap = cap ? cap * 2 : 64; \
			struct file_element *grown = realloc(list, newcap * sizeof(*list)); \
			if (!grown) { free(list); return -EDEV_NO_MEMORY; } \
			list = grown; cap = newcap; \
		} \
		memset(&list[n], 0, sizeof(list[n])); \
	} while (0)

	/* Transport elements exist only in the conf */
	for (i = 0; i < priv->transport_count; i++) {
		GROW();
		list[n].e.type = CHANGER_ELEMENT_TRANSPORT;
		list[n].e.address = (uint16_t)(priv->transport_start + i);
		list[n].e.accessible = true;
		n++;
	}

	for (k = 0; k < sizeof(kinds) / sizeof(kinds[0]); k++) {
		_path(dir, sizeof(dir), priv->dir, kinds[k].subdir, NULL);
		ret = _list_dir(dir, &names, &count);
		if (ret < 0) {
			free(list);
			return ret;
		}
		for (i = 0; i < count; i++) {
			char *end;
			unsigned long a = strtoul(names[i], &end, 10);
			char token[PATH_MAX];
			if (*end || a > 0xFFFF)
				continue;	/* not an element file */
			GROW();
			list[n].e.type = kinds[k].type;
			list[n].e.address = (uint16_t)a;
			list[n].e.accessible = true;
			if (kinds[k].type == CHANGER_ELEMENT_IMPORT_EXPORT) {
				list[n].e.inenab = true;
				list[n].e.exenab = true;
			}
			list[n].subdir = kinds[k].subdir;
			strncpy(list[n].name, names[i], sizeof(list[n].name) - 1);
			_element_path(priv, &list[n], path, sizeof(path));
			ret = _read_first_line(path, token, sizeof(token));
			if (ret < 0) {
				ltfsmsg(ACF0003E, path, errno);
				_free_names(names, count);
				free(list);
				return ret;
			}
			_set_token(priv, &list[n], token);
			_set_source(priv, &list[n]);
			n++;
		}
		_free_names(names, count);
	}

	/* Drives: numbered from dt_start in name order */
	_path(dir, sizeof(dir), priv->dir, FILE_CHANGER_DRIVES, NULL);
	ret = _list_dir(dir, &names, &count);
	if (ret < 0) {
		free(list);
		return ret;
	}
	addr = priv->dt_start;
	for (i = 0; i < count; i++) {
		char token[PATH_MAX];
		if (strncmp(names[i], FILE_CHANGER_DRIVE_PREFIX, strlen(FILE_CHANGER_DRIVE_PREFIX)))
			continue;
		GROW();
		list[n].e.type = CHANGER_ELEMENT_DATA_TRANSFER;
		list[n].e.address = addr++;
		list[n].e.accessible = true;
		list[n].subdir = FILE_CHANGER_DRIVES;
		strncpy(list[n].name, names[i], sizeof(list[n].name) - 1);
		_element_path(priv, &list[n], path, sizeof(path));
		ret = _drive_token(path, token, sizeof(token));
		if (ret < 0) {
			ltfsmsg(ACF0003E, path, errno);
			_free_names(names, count);
			free(list);
			return ret;
		}
		_set_token(priv, &list[n], token);
		_set_source(priv, &list[n]);
		if (priv->info.drive_id)
			_drive_serial(names[i], list[n].e.dvcid, sizeof(list[n].e.dvcid));
		n++;
	}
	_free_names(names, count);
#undef GROW

	ret = _apply_faults(priv, list, n);
	if (ret < 0) {
		free(list);
		return ret;
	}
	if (n)
		qsort(list, n, sizeof(*list), _cmp_element);
	*out = list;
	*n_out = n;
	return 0;
}

static struct file_element *_find(struct file_element *list, size_t n, uint16_t address)
{
	size_t i;
	for (i = 0; i < n; i++)
		if (list[i].e.address == address)
			return &list[i];
	return NULL;
}

/* Put a cartridge (or nothing) into an element file */
static int _store(struct file_changer *priv, struct file_element *fe, const char *token)
{
	char path[PATH_MAX];

	_element_path(priv, fe, path, sizeof(path));
	if (fe->e.type == CHANGER_ELEMENT_DATA_TRANSFER)
		return _write_drive_file(path, token);
	return _write_text(path, token);
}

static int _record_source(struct file_changer *priv, uint16_t address, const struct file_element *from,
						  bool keep)
{
	char state[PATH_MAX], key[64], v[64];

	_path(state, sizeof(state), priv->dir, FILE_CHANGER_STATE, NULL);
	snprintf(key, sizeof(key), "source.%u", address);
	if (!keep)
		return _conf_set(state, key, NULL);

	/* The source a device reports is the storage element the cartridge last rested in */
	if (from->e.type == CHANGER_ELEMENT_STORAGE)
		snprintf(v, sizeof(v), "%u", from->e.address);
	else if (from->e.source_valid)
		snprintf(v, sizeof(v), "%u", from->e.source);
	else
		return _conf_set(state, key, NULL);
	return _conf_set(state, key, v);
}

/* Refresh the address assignment of the info from what is on disk */
static int _refresh_info(struct file_changer *priv)
{
	struct file_element *list;
	size_t n, i;
	int ret;
	uint32_t lo[5], hi[5];

	ret = _load_elements(priv, &list, &n);
	if (ret < 0)
		return ret;

	for (i = 0; i < 5; i++) {
		lo[i] = 0xFFFF;
		hi[i] = 0;
	}
	for (i = 0; i < n; i++) {
		int t = list[i].e.type;
		if (list[i].e.address < lo[t])
			lo[t] = list[i].e.address;
		if (list[i].e.address > hi[t])
			hi[t] = list[i].e.address;
	}
	free(list);

#define RANGE(T, S, C) do { \
		if (hi[T] >= lo[T]) { S = (uint16_t)lo[T]; C = (uint16_t)(hi[T] - lo[T] + 1); } \
		else { C = 0; } \
	} while (0)
	RANGE(CHANGER_ELEMENT_TRANSPORT,     priv->info.transport_start, priv->info.transport_count);
	RANGE(CHANGER_ELEMENT_STORAGE,       priv->info.storage_start,   priv->info.storage_count);
	RANGE(CHANGER_ELEMENT_IMPORT_EXPORT, priv->info.ie_start,        priv->info.ie_count);
	RANGE(CHANGER_ELEMENT_DATA_TRANSFER, priv->info.dt_start,        priv->info.dt_count);
#undef RANGE
	if (!priv->info.transport_count)
		priv->info.transport_start = priv->transport_start;
	if (!priv->info.dt_count)
		priv->info.dt_start = priv->dt_start;

	return 0;
}

/* ---------------------------------------------------------------------- */
/* Finding a library                                                      */
/* ---------------------------------------------------------------------- */

static bool _is_library(const char *dir)
{
	char conf[PATH_MAX];
	if (!_is_dir(dir))
		return false;
	_path(conf, sizeof(conf), dir, FILE_CHANGER_CONF, NULL);
	return _is_file(conf);
}

static void _library_identity(const char *dir, struct changer_info *info)
{
	char conf[PATH_MAX], v[256];
	const char *base;

	_path(conf, sizeof(conf), dir, FILE_CHANGER_CONF, NULL);

	strncpy(info->vendor, _conf_get(conf, "vendor", v, sizeof(v)) ? v : "AURORA", TAPE_VENDOR_NAME_LEN_MAX);
	info->vendor[TAPE_VENDOR_NAME_LEN_MAX] = '\0';
	strncpy(info->model, _conf_get(conf, "model", v, sizeof(v)) ? v : "FILECHANGER", TAPE_MODEL_NAME_LEN_MAX);
	info->model[TAPE_MODEL_NAME_LEN_MAX] = '\0';
	strncpy(info->product_rev, _conf_get(conf, "product_rev", v, sizeof(v)) ? v : "0001", PRODUCT_REV_LENGTH);
	info->product_rev[PRODUCT_REV_LENGTH] = '\0';

	base = strrchr(dir, '/');
	base = base ? base + 1 : dir;
	strncpy(info->serial_number, _conf_get(conf, "serial", v, sizeof(v)) ? v : base, TAPE_SERIAL_LEN_MAX);
	info->serial_number[TAPE_SERIAL_LEN_MAX] = '\0';
}

/* Resolve a device name: a directory, or a name / serial under the root directory */
static int _resolve(const char *devname, char *dir, size_t size)
{
	const char *root = getenv(FILE_CHANGER_ROOT_ENV);
	char **names;
	size_t n, i;
	int ret;

	if (_is_library(devname)) {
		strncpy(dir, devname, size - 1);
		dir[size - 1] = '\0';
		return 0;
	}
	if (!root)
		return -EDEV_DEVICE_UNOPENABLE;

	snprintf(dir, size, "%s/%s", root, devname);
	if (_is_library(dir))
		return 0;

	ret = _list_dir(root, &names, &n);
	if (ret < 0)
		return ret;
	ret = -EDEV_DEVICE_UNOPENABLE;
	for (i = 0; i < n; i++) {
		struct changer_info info;
		snprintf(dir, size, "%s/%s", root, names[i]);
		if (!_is_library(dir))
			continue;
		memset(&info, 0, sizeof(info));
		_library_identity(dir, &info);
		if (!strcmp(info.serial_number, devname)) {
			ret = 0;
			break;
		}
	}
	_free_names(names, n);
	return ret;
}

/* ---------------------------------------------------------------------- */
/* struct changer_ops                                                     */
/* ---------------------------------------------------------------------- */

int file_changer_open(const char *devname, void **handle)
{
	struct file_changer *priv;
	char dir[PATH_MAX], conf[PATH_MAX];
	int ret;

	CHECK_ARG_NULL(devname, -LTFS_NULL_ARG);
	CHECK_ARG_NULL(handle, -LTFS_NULL_ARG);
	*handle = NULL;

	ltfsmsg(ACF0001I, devname);

	ret = _resolve(devname, dir, sizeof(dir));
	if (ret < 0) {
		ltfsmsg(ACF0002E, devname);
		return ret;
	}

	priv = calloc(1, sizeof(*priv));
	if (!priv)
		return -EDEV_NO_MEMORY;
	priv->dir = strdup(dir);
	if (!priv->dir) {
		free(priv);
		return -EDEV_NO_MEMORY;
	}

	_path(conf, sizeof(conf), dir, FILE_CHANGER_CONF, NULL);
	_library_identity(dir, &priv->info);
	priv->info.barcode_reader = _conf_bool(conf, "barcode_reader", true);
	priv->info.drive_id       = _conf_bool(conf, "dvcid", true);
	priv->info.exchange       = _conf_bool(conf, "exchange", true);
	priv->info.probed         = true;
	priv->prevent_supported   = _conf_bool(conf, "prevent_supported", true);
	priv->move_ms             = (unsigned int)_conf_ulong(conf, "move_ms", 0);
	priv->inventory_ms        = (unsigned int)_conf_ulong(conf, "inventory_ms", 0);
	priv->transport_start     = (uint16_t)_conf_ulong(conf, "transport_start", 1);
	priv->transport_count     = (uint16_t)_conf_ulong(conf, "transport_count", 1);
	priv->dt_start            = (uint16_t)_conf_ulong(conf, "dt_start", 257);

	ret = _refresh_info(priv);
	if (ret < 0) {
		free(priv->dir);
		free(priv);
		return ret;
	}

	ltfsmsg(ACF0006I, priv->dir, priv->info.storage_count, priv->info.ie_count, priv->info.dt_count);

	*handle = priv;
	return 0;
}

int file_changer_close(void *handle)
{
	struct file_changer *priv = handle;

	CHECK_ARG_NULL(handle, -LTFS_NULL_ARG);
	free(priv->dir);
	free(priv);
	return 0;
}

int file_changer_is_connected(const char *devname)
{
	char dir[PATH_MAX];

	CHECK_ARG_NULL(devname, -LTFS_NULL_ARG);
	return _resolve(devname, dir, sizeof(dir));
}

int file_changer_test_unit_ready(void *handle)
{
	struct file_changer *priv = handle;

	CHECK_ARG_NULL(handle, -LTFS_NULL_ARG);
	return _enter(priv, "tur", NULL);
}

int file_changer_inquiry(void *handle, struct tc_inq *inq)
{
	struct file_changer *priv = handle;

	CHECK_ARG_NULL(handle, -LTFS_NULL_ARG);
	CHECK_ARG_NULL(inq, -LTFS_NULL_ARG);

	memset(inq, 0, sizeof(*inq));
	inq->devicetype = 0x08;
	snprintf((char *)inq->vid, sizeof(inq->vid), "%-8s", priv->info.vendor);
	snprintf((char *)inq->pid, sizeof(inq->pid), "%-16s", priv->info.model);
	snprintf((char *)inq->revision, sizeof(inq->revision), "%-4s", priv->info.product_rev);
	return 0;
}

int file_changer_get_serialnumber(void *handle, char **result)
{
	struct file_changer *priv = handle;

	CHECK_ARG_NULL(handle, -LTFS_NULL_ARG);
	CHECK_ARG_NULL(result, -LTFS_NULL_ARG);

	*result = strdup(priv->info.serial_number);
	return *result ? 0 : -EDEV_NO_MEMORY;
}

int file_changer_get_info(void *handle, struct changer_info *info)
{
	struct file_changer *priv = handle;
	int ret;

	CHECK_ARG_NULL(handle, -LTFS_NULL_ARG);
	CHECK_ARG_NULL(info, -LTFS_NULL_ARG);

	ret = _refresh_info(priv);
	if (ret < 0)
		return ret;
	*info = priv->info;
	return 0;
}

int file_changer_get_device_list(struct tc_drive_info *buf, int count)
{
	const char *root = getenv(FILE_CHANGER_ROOT_ENV);
	char **names;
	size_t n, i;
	int found = 0, ret;

	if (!root)
		return 0;
	ret = _list_dir(root, &names, &n);
	if (ret < 0)
		return ret;

	for (i = 0; i < n; i++) {
		char dir[PATH_MAX];
		struct changer_info info;

		snprintf(dir, sizeof(dir), "%s/%s", root, names[i]);
		if (!_is_library(dir))
			continue;
		if (buf && found < count) {
			memset(&info, 0, sizeof(info));
			_library_identity(dir, &info);
			memset(&buf[found], 0, sizeof(buf[found]));
			strncpy(buf[found].name,          dir,                TAPE_DEVNAME_LEN_MAX);
			strncpy(buf[found].vendor,        info.vendor,        TAPE_VENDOR_NAME_LEN_MAX);
			strncpy(buf[found].model,         info.model,         TAPE_MODEL_NAME_LEN_MAX);
			strncpy(buf[found].serial_number, info.serial_number, TAPE_SERIAL_LEN_MAX);
			strncpy(buf[found].product_rev,   info.product_rev,   PRODUCT_REV_LENGTH);
			snprintf(buf[found].product_name, PRODUCT_NAME_LENGTH + 1, " [%s]", info.model);
			buf[found].lun = -1;
		}
		found++;
	}
	_free_names(names, n);
	return found;
}

int file_changer_get_elements(void *handle, enum changer_element_type type, uint16_t start,
							  uint16_t count, struct changer_element **elements, size_t *n)
{
	struct file_changer *priv = handle;
	struct file_element *list;
	size_t total, i, out = 0;
	uint32_t end;
	int ret;

	CHECK_ARG_NULL(handle, -LTFS_NULL_ARG);
	CHECK_ARG_NULL(elements, -LTFS_NULL_ARG);
	CHECK_ARG_NULL(n, -LTFS_NULL_ARG);

	*elements = NULL;
	*n = 0;

	ret = _enter(priv, "get_elements", NULL);
	if (ret < 0)
		return ret;

	ret = _load_elements(priv, &list, &total);
	if (ret < 0)
		return ret;

	end = count ? (uint32_t)start + count : 0x10000;
	*elements = calloc(total ? total : 1, sizeof(**elements));
	if (!*elements) {
		free(list);
		return -EDEV_NO_MEMORY;
	}
	for (i = 0; i < total; i++) {
		if (type != CHANGER_ELEMENT_ANY && list[i].e.type != type)
			continue;
		if (count && (list[i].e.address < start || list[i].e.address >= end))
			continue;
		(*elements)[out++] = list[i].e;
	}
	free(list);
	*n = out;
	return 0;
}

static int _check_transport(struct file_changer *priv, uint16_t transport)
{
	if (transport == 0)
		return 0;
	if (transport >= priv->transport_start && transport < priv->transport_start + priv->transport_count)
		return 0;
	return -EDEV_INVALID_ADDRESS;
}

int file_changer_move(void *handle, uint16_t transport, uint16_t source, uint16_t dest)
{
	struct file_changer *priv = handle;
	struct file_element *list, *src, *dst;
	size_t n;
	int ret;
	bool lost_after = false;
	char token[PATH_MAX];
	struct file_element from;

	CHECK_ARG_NULL(handle, -LTFS_NULL_ARG);

	ret = _enter(priv, "move", &lost_after);
	if (ret < 0)
		return ret;
	ret = _check_transport(priv, transport);
	if (ret < 0)
		return ret;

	ret = _load_elements(priv, &list, &n);
	if (ret < 0)
		return ret;

	src = _find(list, n, source);
	dst = _find(list, n, dest);
	if (!src || !dst || dst->e.type == CHANGER_ELEMENT_TRANSPORT || src->e.type == CHANGER_ELEMENT_TRANSPORT) {
		free(list);
		return -EDEV_INVALID_ADDRESS;
	}
	if (!src->e.full) {
		free(list);
		return -EDEV_SRC_EMPTY;
	}
	if (dst->e.full) {
		free(list);
		return -EDEV_DEST_FULL;
	}
	ret = _element_fault(src, "move");
	if (ret == 0)
		ret = _element_fault(dst, "move");
	if (ret < 0) {
		free(list);
		return ret;
	}

	strncpy(token, src->token, sizeof(token) - 1);
	token[sizeof(token) - 1] = '\0';
	from = *src;

	ret = _store(priv, src, "");
	if (ret < 0) {
		free(list);
		return ret;
	}
	_record_source(priv, source, &from, false);

	_sleep_ms(priv->move_ms);	/* the cartridge is on the picker: in neither element */

	ret = _store(priv, dst, token);
	if (ret < 0) {
		_store(priv, src, token);	/* put it back rather than lose it */
		free(list);
		return ret;
	}
	_record_source(priv, dest, &from, dst->e.type != CHANGER_ELEMENT_STORAGE);
	free(list);

	if (lost_after)
		return -EDEV_CONNECTION_LOST;
	return 0;
}

int file_changer_exchange(void *handle, uint16_t transport, uint16_t source, uint16_t dest1, uint16_t dest2)
{
	struct file_changer *priv = handle;
	struct file_element *list, *src, *d1, *d2;
	size_t n;
	int ret;
	char token_a[PATH_MAX], token_b[PATH_MAX];
	struct file_element from_a, from_b;

	CHECK_ARG_NULL(handle, -LTFS_NULL_ARG);

	ret = _enter(priv, "exchange", NULL);
	if (ret < 0)
		return ret;
	if (!priv->info.exchange)
		return -EDEV_UNSUPPORTED_FUNCTION;
	ret = _check_transport(priv, transport);
	if (ret < 0)
		return ret;

	ret = _load_elements(priv, &list, &n);
	if (ret < 0)
		return ret;

	src = _find(list, n, source);
	d1  = _find(list, n, dest1);
	d2  = _find(list, n, dest2);
	if (!src || !d1 || !d2 || src->e.type == CHANGER_ELEMENT_TRANSPORT
		|| d1->e.type == CHANGER_ELEMENT_TRANSPORT || d2->e.type == CHANGER_ELEMENT_TRANSPORT) {
		free(list);
		return -EDEV_INVALID_ADDRESS;
	}
	if (!src->e.full || !d1->e.full) {
		free(list);
		return -EDEV_SRC_EMPTY;
	}
	if (d2 != src && d2->e.full) {
		free(list);
		return -EDEV_DEST_FULL;
	}
	ret = _element_fault(src, "exchange");
	if (ret == 0)
		ret = _element_fault(d1, "exchange");
	if (ret == 0)
		ret = _element_fault(d2, "exchange");
	if (ret < 0) {
		free(list);
		return ret;
	}

	strncpy(token_a, src->token, sizeof(token_a) - 1);
	token_a[sizeof(token_a) - 1] = '\0';
	strncpy(token_b, d1->token, sizeof(token_b) - 1);
	token_b[sizeof(token_b) - 1] = '\0';
	from_a = *src;
	from_b = *d1;

	ret = _store(priv, src, "");
	if (ret == 0)
		ret = _store(priv, d1, "");
	if (ret < 0) {
		free(list);
		return ret;
	}
	_record_source(priv, source, &from_a, false);
	_record_source(priv, dest1, &from_b, false);

	_sleep_ms(priv->move_ms);

	ret = _store(priv, d1, token_a);
	if (ret == 0)
		ret = _store(priv, d2, token_b);
	if (ret < 0) {
		free(list);
		return ret;
	}
	_record_source(priv, dest1, &from_a, d1->e.type != CHANGER_ELEMENT_STORAGE);
	_record_source(priv, dest2, &from_b, d2->e.type != CHANGER_ELEMENT_STORAGE);
	free(list);
	return 0;
}

static int _prevent_allow(struct file_changer *priv, bool prevent)
{
	char state[PATH_MAX];
	int ret;

	ret = _enter(priv, "prevent", NULL);
	if (ret < 0)
		return ret;
	if (!priv->prevent_supported)
		return -EDEV_UNSUPPORTED_FUNCTION;
	_path(state, sizeof(state), priv->dir, FILE_CHANGER_STATE, NULL);
	return _conf_set(state, "ie_locked", prevent ? "1" : "0");
}

int file_changer_prevent_medium_removal(void *handle)
{
	CHECK_ARG_NULL(handle, -LTFS_NULL_ARG);
	return _prevent_allow(handle, true);
}

int file_changer_allow_medium_removal(void *handle)
{
	CHECK_ARG_NULL(handle, -LTFS_NULL_ARG);
	return _prevent_allow(handle, false);
}

int file_changer_scan(void *handle, uint16_t start, uint16_t count)
{
	struct file_changer *priv = handle;
	int ret;

	(void)start;
	(void)count;
	CHECK_ARG_NULL(handle, -LTFS_NULL_ARG);

	ret = _enter(priv, "scan", NULL);
	if (ret < 0)
		return ret;
	_sleep_ms(priv->inventory_ms);
	return 0;
}

void file_changer_help_message(const char *progname)
{
	(void)progname;
	ltfsresult(ACF0008I);
}

int file_changer_parse_opts(void *handle, void *opt_args)
{
	(void)handle;
	(void)opt_args;
	return 0;
}

struct changer_ops file_changer_handler = {
	.open                   = file_changer_open,
	.close                  = file_changer_close,
	.is_connected           = file_changer_is_connected,
	.test_unit_ready        = file_changer_test_unit_ready,
	.inquiry                = file_changer_inquiry,
	.get_serialnumber       = file_changer_get_serialnumber,
	.get_info               = file_changer_get_info,
	.get_device_list        = file_changer_get_device_list,
	.get_elements           = file_changer_get_elements,
	.move                   = file_changer_move,
	.exchange               = file_changer_exchange,
	.prevent_medium_removal = file_changer_prevent_medium_removal,
	.allow_medium_removal   = file_changer_allow_medium_removal,
	.scan                   = file_changer_scan,
	.help_message           = file_changer_help_message,
	.parse_opts             = file_changer_parse_opts,
};

struct changer_ops *changer_get_ops(void)
{
	return &file_changer_handler;
}
