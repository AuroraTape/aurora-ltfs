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
**
*************************************************************************************
**
** COMPONENT NAME:  IBM Linear Tape File System
**
** FILE NAME:       errormap.c
**
** DESCRIPTION:     Platform-specific error code mapping implementation.
**
** AUTHORS:         Brian Biskeborn
**                  IBM Almaden Research Center
**                  bbiskebo@us.ibm.com
**
*************************************************************************************
*/

#ifdef mingw_PLATFORM
#include "libltfs/arch/win/win_util.h"
#endif

#ifdef __FreeBSD__
#include "libltfs/arch/freebsd/errno.h"
#endif

#include <stdlib.h>
#include <errno.h>

#include "libltfs/ltfslogging.h"
#include "libltfs/ltfs_error.h"
#include "libltfs/uthash.h"
#include "libltfs/arch/errormap.h"

/* Use the Bernstein hash function, which has the best lookup performance for this
 * data set on amd64. */
#undef HASH_FCN
#define HASH_FCN HASH_BER

struct error_map {
	int ltfs_error;
	char *msd_id;
	int general_error;
	UT_hash_handle hh;
};

/* Hash table of libltfs -> FUSE error codes */
static struct error_map *fuse_errormap = NULL;

/** Map from libltfs error codes to appropriate FUSE errors.
 * This should be kept in sync with libltfs/ltfs_error.h.
 * TODO: define the corresponding error mapping for Windows.
 */
static struct error_map fuse_error_list[] = {
	{ LTFS_NULL_ARG,                 "AEI0001E", EINVAL},
	{ LTFS_NO_MEMORY,                "AEI0002E", ENOMEM},
	{ LTFS_MUTEX_INVALID,            "AEI0003E", EINVAL},
	{ LTFS_MUTEX_UNLOCKED,           "AEI0004E", EINVAL},
	{ LTFS_BAD_DEVICE_DATA,          "AEI0005E", EINVAL},
	{ LTFS_BAD_PARTNUM,              "AEI0006E", EINVAL},
	{ LTFS_LIBXML2_FAILURE,          "AEI0007E", EINVAL},
	{ LTFS_DEVICE_UNREADY,           "AEI0008E", EAGAIN},
#ifdef ENOMEDIUM
	{ LTFS_NO_MEDIUM,                "AEI0009E", ENOMEDIUM},
#else
	{ LTFS_NO_MEDIUM,                "AEI0009E", EAGAIN},
#endif /* ENOMEDIUM */
	{ LTFS_LARGE_BLOCKSIZE,          "AEI0010E", EINVAL},
	{ LTFS_BAD_LOCATE,               "AEI0011E", EIO},
	{ LTFS_NOT_PARTITIONED,          "AEI0012E", EINVAL},
	{ LTFS_LABEL_INVALID,            "AEI0013E", EINVAL},
	{ LTFS_LABEL_MISMATCH,           "AEI0014E", EINVAL},
	{ LTFS_INDEX_INVALID,            "AEI0015E", EINVAL},
	{ LTFS_INCONSISTENT,             "AEI0016E", EINVAL},
	{ LTFS_UNSUPPORTED_MEDIUM,       "AEI0017E", EINVAL},
	{ LTFS_GENERATION_MISMATCH,      "AEI0018E", EINVAL},
	{ LTFS_MAM_CACHE_INVALID,        "AEI0019E", EINVAL},
	{ LTFS_INDEX_CACHE_INVALID,      "AEI0020E", EINVAL},
	{ LTFS_POLICY_EMPTY_RULE,        "AEI0021E", EINVAL},
	{ LTFS_MUTEX_INIT,               "AEI0022E", EINVAL},
	{ LTFS_BAD_ARG,                  "AEI0023E", EINVAL},
	{ LTFS_NAMETOOLONG,              "AEI0024E", ENAMETOOLONG},
	{ LTFS_NO_DENTRY,                "AEI0025E", ENOENT},
	{ LTFS_INVALID_PATH,             "AEI0026E", EINVAL},
	{ LTFS_INVALID_SRC_PATH,         "AEI0027E", ENOENT},
	{ LTFS_DENTRY_EXISTS,            "AEI0028E", EEXIST},
	{ LTFS_DIRNOTEMPTY,              "AEI0029E", ENOTEMPTY},
	{ LTFS_UNLINKROOT,               "AEI0030E", EBUSY},
	{ LTFS_DIRMOVE,                  "AEI0031E", EIO},
	{ LTFS_RENAMELOOP,               "AEI0032E", EINVAL},
	{ LTFS_SMALL_BLOCK,              "AEI0033E", EIO},
	{ LTFS_ISDIRECTORY,              "AEI0034E", EINVAL},
	{ LTFS_EOD_MISSING_MEDIUM,       "AEI0035E", EINVAL},
	{ LTFS_BOTH_EOD_MISSING,         "AEI0036E", EIO},
	{ LTFS_UNEXPECTED_VALUE,         "AEI0037E", EIO},
	{ LTFS_UNSUPPORTED,              "AEI0038E", EIO},
	{ LTFS_LABEL_POSSIBLE_VALID,     "AEI0039E", EIO},
	{ LTFS_CLOSE_FS_IF,              "AEI0040E", EIDRM},
#ifdef ENOATTR
	{ LTFS_NO_XATTR,                 "AEI0041E", ENOATTR},
#else
	{ LTFS_NO_XATTR,                 "AEI0041E", ENODATA},
#endif /* ENOATTR */
	{ LTFS_SIG_HANDLER_ERR,          "AEI0042E", EINVAL},
	{ LTFS_INTERRUPTED,              "AEI0043E", ECANCELED},
	{ LTFS_UNSUPPORTED_INDEX_VERSION,"AEI0044E", EINVAL},
	{ LTFS_ICU_ERROR,                "AEI0045E", EINVAL},
	{ LTFS_PLUGIN_LOAD,              "AEI0046E", EINVAL},
	{ LTFS_PLUGIN_UNLOAD,            "AEI0047E", EINVAL},
	{ LTFS_RDONLY_XATTR,             "AEI0048E", EACCES},
	{ LTFS_XATTR_EXISTS,             "AEI0049E", EEXIST},
	{ LTFS_SMALL_BUFFER,             "AEI0050E", ERANGE},
	{ LTFS_RDONLY_VOLUME,            "AEI0051E", EROFS},
	{ LTFS_NO_SPACE,                 "AEI0052E", ENOSPC},
	{ LTFS_LARGE_XATTR,              "AEI0053E", ENOSPC},
	{ LTFS_NO_INDEX,                 "AEI0054E", ENODATA},
	{ LTFS_XATTR_NAMESPACE,          "AEI0055E", EOPNOTSUPP},
	{ LTFS_CONFIG_INVALID,           "AEI0056E", EINVAL},
	{ LTFS_PLUGIN_INCOMPLETE,        "AEI0057E", EINVAL},
	{ LTFS_NO_PLUGIN,                "AEI0058E", ENOENT},
	{ LTFS_POLICY_INVALID,           "AEI0059E", EINVAL},
	{ LTFS_ISFILE,                   "AEI0060E", ENOTDIR},
	{ LTFS_UNRESOLVED_VOLUME,        "AEI0061E", EBUSY},
	{ LTFS_POLICY_IMMUTABLE,         "AEI0062E", EPERM},
	{ LTFS_SMALL_BLOCKSIZE,          "AEI0063E", EINVAL},
	{ LTFS_BARCODE_LENGTH,           "AEI0064E", EINVAL},
	{ LTFS_BARCODE_INVALID,          "AEI0065E", EINVAL},
	{ LTFS_RESOURCE_SHORTAGE,        "AEI0066E", EBUSY},
	{ LTFS_DEVICE_FENCED,            "AEI0067E", EAGAIN},
	{ LTFS_REVAL_RUNNING,            "AEI0068E", EAGAIN},
	{ LTFS_REVAL_FAILED,             "AEI0069E", EFAULT},
	{ LTFS_SLOT_FULL,                "AEI0070E", EFAULT},
	{ LTFS_SLOT_SHORTAGE,            "AEI0071E", EFAULT},
	{ LTFS_CHANGER_ERROR,            "AEI0072E", EIO},
	{ LTFS_UNEXPECTED_TAPE,          "AEI0073E", EINVAL},
	{ LTFS_NO_HOMESLOT,              "AEI0074E", EINVAL},
	{ LTFS_MOVE_ACTIVE_CART,         "AEI0075E", ECANCELED},
	{ LTFS_NO_IE_SLOT,               "AEI0076E", ECANCELED},
	{ LTFS_INVALID_SLOT,             "AEI0077E", EINVAL},
	{ LTFS_UNSUPPORTED_CART,         "AEI0078E", EINVAL},
	{ LTFS_CART_STUCKED,             "AEI0079E", EIO},
	{ LTFS_OP_NOT_ALLOWED,           "AEI0080E", EINVAL},
	{ LTFS_OP_TO_DUP,                "AEI0081E", EINVAL},
	{ LTFS_OP_TO_NON_SUP,            "AEI0082E", EINVAL},
	{ LTFS_OP_TO_INACC,              "AEI0083E", EINVAL},
	{ LTFS_OP_TO_UNFMT,              "AEI0084E", EINVAL},
	{ LTFS_OP_TO_INV,                "AEI0085E", EINVAL},
	{ LTFS_OP_TO_ERR,                "AEI0086E", EINVAL},
	{ LTFS_OP_TO_CRIT,               "AEI0087E", EINVAL},
	{ LTFS_OP_TO_CLN,                "AEI0088E", EINVAL},
	{ LTFS_OP_TO_RO,                 "AEI0089E", EINVAL},
	{ LTFS_ALREADY_FS_INC,           "AEI0090E", EINVAL},
	{ LTFS_NOT_IN_FS,                "AEI0091E", EINVAL},
	{ LTFS_FS_CART_TO_IE,            "AEI0092E", EINVAL},
	{ LTFS_OP_TO_UNKN,               "AEI0093E", EINVAL},
	{ LTFS_DRV_LOCKED,               "AEI0094E", EINVAL},
	{ LTFS_DRV_ALRDY_ADDED,          "AEI0095E", EINVAL},
	{ LTFS_FORCE_INVENTORY,          "AEI0096E", EIO},
	{ LTFS_INVENTORY_FAILED,         "AEI0097E", EFAULT},
	{ LTFS_RESTART_OPERATION,        "AEI0098E", EIO},
	{ LTFS_NO_TARGET_DRIVE,          "AEI0099E", EINVAL},
	{ LTFS_NO_DCACHE_FSTYPE,         "AEI0100E", EINVAL},
	{ LTFS_IMAGE_EXISTED,            "AEI0101E", EINVAL},
	{ LTFS_IMAGE_MOUNTED,            "AEI0102E", EIO},
	{ LTFS_IMAGE_NOT_MOUNTED,        "AEI0103E", EIO},
	{ LTFS_MTAB_NOREGULAR,           "AEI0104E", EIO},
	{ LTFS_MTAB_OPEN,                "AEI0105E", EIO},
	{ LTFS_MTAB_LOCK,                "AEI0106E", EIO},
	{ LTFS_MTAB_SEEK,                "AEI0107E", EIO},
	{ LTFS_MTAB_UPDATE,              "AEI0108E", EIO},
	{ LTFS_MTAB_FLUSH,               "AEI0109E", EIO},
	{ LTFS_MTAB_UNLOCK,              "AEI0110E", EIO},
	{ LTFS_MTAB_CLOSE,               "AEI0111E", EIO},
	{ LTFS_MTAB_COPY,                "AEI0112E", EIO},
	{ LTFS_MTAB_TEMP_OPEN,           "AEI0113E", EIO},
	{ LTFS_MTAB_TEMP_SEEK,           "AEI0114E", EIO},
	{ LTFS_DCACHE_CREATION_FAIL,     "AEI0115E", EIO},
	{ LTFS_DCACHE_UNSUPPORTED,       "AEI0116E", EINVAL},
	{ LTFS_DCACHE_EXTRA_SPACE,       "AEI0117E", EINVAL},
	{ LTFS_KEY_NOT_FOUND,            "AEI0118E", EINVAL},
	{ LTFS_INVALID_SEQUENCE,         "AEI0119E", EINVAL},
	{ LTFS_RDONLY_ROOT,              "AEI0120E", EACCES},
	{ LTFS_SYMLINK_CONFLICT,         "AEI0121E", EIO},
	{ LTFS_NETWORK_INIT_FAIL,        "AEI0122E", EINVAL},
	{ LTFS_DRIVE_SHORTAGE,           "AEI0123E", ENODEV},
	{ LTFS_INVALID_VOLSER,           "AEI0124E", EINVAL},
	{ LTFS_LESS_SPACE,               "AEI0125E", ENOSPC},
	{ LTFS_WRITE_PROTECT,            "AEI0126E", EROFS},
	{ LTFS_WRITE_ERROR,              "AEI0127E", EROFS},
	{ LTFS_UNEXPECTED_BARCODE,       "AEI0128E", EIO},
	{ LTFS_STRING_CONVERSION,        "AEI0129E", EINVAL},
	{ LTFS_SESSION_INIT_FAIL,        "AEI0130E", EIO},
	{ LTFS_MESSAGE_INVALID,          "AEI0131E", EINVAL},
	{ LTFS_PASSWORD_INVALID,         "AEI0132E", EPERM},
	{ LTFS_NOT_AUTHENTICATERD,       "AEI0133E", EINVAL},
	{ LTFS_WORM_DEEP_RECOVERY,       "AEI0134E", EINVAL},
	{ LTFS_WORM_ROLLBACK,            "AEI0135E", EINVAL},
	{ LTFS_NONWORM_SALVAGE,          "AEI0136E", EINVAL},
	{ LTFS_FORMATTED,                "AEI0137E", EPERM},
	{ LTFS_RULES_WORM,               "AEI0138E", EINVAL},
	{ LTFS_BAD_BLOCKSIZE,            "AEI0139E", EINVAL},
	{ LTFS_BAD_VOLNAME,              "AEI0140E", EINVAL},
	{ LTFS_BAD_RULES,                "AEI0141E", EINVAL},
	{ LTFS_GEN_NEEDED,               "AEI0142E", EINVAL},
	{ LTFS_BAD_GENERATION,           "AEI0143E", EINVAL},
	{ LTFS_NO_ROLLBACK_TARGET,       "AEI0144E", EINVAL},
	{ LTFS_MANY_INDEXES,             "AEI0145E", EINVAL},
	{ LTFS_SALVAGE_NOT_NEEDED,       "AEI0146E", EINVAL},
	{ LTFS_WORM_ENABLED,             "AEI0147E", EACCES},
	{ LTFS_OUTSTANDING_REFS,         "AEI0148E", EBUSY},
	{ LTFS_REBUILD_IN_PROGRESS,      "AEI0149E", EBUSY},
	{ LTFS_MULTIPLE_START,           "AEI0150E", EINVAL},
	{ LTFS_CARTRIDGE_NOT_FOUND,      "AEI0151E", EINVAL},
	{ LTFS_CACHE_LOCK_ERR,           "AEI0152E", EIO},
	{ LTFS_CACHE_UNLOCK_ERR,         "AEI0153E", EIO},
	{ LTFS_CREPO_FILE_ERR,           "AEI0154E", EIO},
	{ LTFS_CREPO_READ_ERR,           "AEI0155E", EIO},
	{ LTFS_CREPO_WRITE_ERR,          "AEI0156E", EIO},
	{ LTFS_CREPO_INVALID_OP,         "AEI0157E", EINVAL},
	{ LTFS_FILE_ERR,                 "AEI0158E", EIO},
	{ LTFS_CARTRIDGE_IN_USE,         "AEI0159E", EBUSY},
	{ LTFS_NO_LOCK_ENTRY,            "AEI0160E", ENOENT},
	{ LTFS_MOUNT_ERR,                "AEI0161E", EIO},
	{ LTFS_NO_DEVICE,                "AEI0162E", ENODEV},
	{ LTFS_XATTR_ERR,                "AEI0163E", EIO},
	{ LTFS_FTW_ERR,                  "AEI0164E", EIO},
	{ LTFS_TIME_ERR,                 "AEI0165E", EIO},
	{ LTFS_NOT_BLOCK_DEVICE,         "AEI0166E", ENOTBLK},
	{ LTFS_QUOTA_EXCEEDED,           "AEI0167E", EDQUOT},
	{ LTFS_TOO_MANY_OPEN_FILES,      "AEI0168E", ENFILE},
	{ LTFS_LINKDIR_EXISTS,           "AEI0169E", EEXIST},
	{ LTFS_NO_DMAP_ENTRY,            "AEI0170E", ENOENT},
	{ LTFS_RECOVERABLE_FILE_ERR,     "AEI0171E", EAGAIN},
	{ LTFS_NO_DCACHE_SPC,            "AEI0172E", ENOSPC},
	{ LTFS_POS_SUSPECT_BOP,          "AEI0173E", EIO},
	/* Unused 1175 - 1179 */
	{ LTFS_CACHE_IO,                 "AEI0174E", EIO },
	{ LTFS_CACHE_DISCARDED,          "AEI0175E", ENOENT },
	{ LTFS_LONG_WRITE_LOCK,          "AEI0176E", EAGAIN },
	{ LTFS_INCOMPATIBLE_CACHE,       "AEI0177E", EINVAL },
	{ LTFS_DCACHE_NOT_INITIALIZED,   "AEI0178E", EIO },
	{ LTFS_CONFIG_FILE_WLOCKED,      "AEI0179E", EINVAL },
	{ LTFS_CREATE_QUEUE,             "AEI0180E", EIO },
	{ LTFS_FORK_ERROR,               "AEI0181E", EIO },
	{ LTFS_NOACK,                    "AEI0182E", EIO },
	{ LTFS_NODE_DETECT_FAIL,         "AEI0183E", EIO },
	{ LTFS_INVALID_MESSAGE,          "AEI0184E", EIO },
	{ LTFS_NODE_DEGATE_FAIL,         "AEI0185E", EIO },
	{ LTFS_CLUSTER_MRSW_FAIL,        "AEI0186E", EIO },
	{ LTFS_CART_NOT_MOUNTED,         "AEI0187E", EBUSY},
	{ LTFS_RDONLY_DEN_DRV,           "AEI0188E", EINVAL},
	{ LTFS_NEED_DRIVE_SELECTION,     "AEI0189E", EINVAL},
	{ LTFS_MUTEX_ALREADY_LOCKED,     "AEI0190E", EINVAL},
	{ LTFS_TAPE_UNDER_PROCESS,       "AEI0191E", EBUSY},
	{ LTFS_TAPE_REMOVED,             "AEI0192E", EIDRM},
	{ LTFS_NEED_MOVE,                "AEI0193E", EINVAL},
	{ LTFS_NEED_START_OVER,          "AEI0194E", EINVAL},
	{ LTFS_LOCATE_ERROR,             "AEI0195E", EIO},
	{ LTFS_STATS_DB_OPEN,            "AEI0196E", EIO},
	{ LTFS_NO_TRAIL_FM,              "AEI0197E", EINVAL},
	{ LTFS_SAFENAME_FAIL,            "AEI0198E", EINVAL},
	{ LTFS_SYNC_FAIL_ON_DP,          "AEI0199E", EIO},
	{ LTFS_XML_READ_FAIL,            "AEI0200E", EINVAL},
	{ LTFS_XML_CONST_FAIL,           "AEI0201E", EINVAL},
	{ LTFS_XML_WRONG_NODE,           "AEI0202E", EINVAL},
	{ LTFS_XML_UNEXPECTED_EOF,       "AEI0203E", EINVAL},
	{ LTFS_XML_EMPTY_UNKNOWN,        "AEI0204E", EINVAL},
	{ LTFS_XML_EMPTY,                "AEI0205E", EINVAL},
	{ LTFS_XML_SKIP_FAIL,            "AEI0206E", EINVAL},
	{ LTFS_XML_NO_REQUIRED_TAG,      "AEI0207E", EINVAL},
	{ LTFS_XML_DUPLICATED_TAG,       "AEI0208E", EINVAL},
	{ LTFS_XML_OPEN_TAG,             "AEI0209E", EINVAL},
	{ LTFS_XML_SAVE_FAIL,            "AEI0210E", EINVAL},
	{ LTFS_XML_WRONG_TOPTAG,         "AEI0211E", EINVAL},
	{ LTFS_XML_WRONG_ENCODING,       "AEI0212E", EINVAL},
	{ LTFS_XML_TOP_ATTR_FAIL,        "AEI0213E", EINVAL},
	{ LTFS_XML_WRONG_UUID,           "AEI0214E", EINVAL},
	{ LTFS_XML_WRONG_GEN,            "AEI0215E", EINVAL},
	{ LTFS_XML_WRONG_UTIME,          "AEI0216E", EINVAL},
	{ LTFS_XML_WRONG_LOC,            "AEI0217E", EINVAL},
	{ LTFS_XML_WRONG_LOC_PREV,       "AEI0218E", EINVAL},
	{ LTFS_XML_WRONG_PA,             "AEI0219E", EINVAL},
	{ LTFS_XML_WRONG_POLICY,         "AEI0220E", EINVAL},
	{ LTFS_XML_TOO_LONG_COMMENT,     "AEI0221E", EINVAL},
	{ LTFS_XML_WRONG_NEXT,           "AEI0222E", EINVAL},
	{ LTFS_XML_WRONG_RO_DIR,         "AEI0223E", EINVAL},
	{ LTFS_XML_WRONG_MTIME_DIR,      "AEI0224E", EINVAL},
	{ LTFS_XML_WRONG_CRTIME_DIR,     "AEI0225E", EINVAL},
	{ LTFS_XML_WRONG_ATIME_DIR,      "AEI0226E", EINVAL},
	{ LTFS_XML_WRONG_CTIME_DIR,      "AEI0227E", EINVAL},
	{ LTFS_XML_WRONG_BTIME_DIR,      "AEI0228E", EINVAL},
	{ LTFS_XML_XATTR_TYPE,           "AEI0229E", EINVAL},
	{ LTFS_XML_XATTR_SIZE,           "AEI0230E", EINVAL},
	{ LTFS_XML_WRONG_UID,            "AEI0231E", EINVAL},
	{ LTFS_XML_INVALID_UID,          "AEI0232E", EINVAL},
	{ LTFS_XML_WRONG_RO_F,           "AEI0233E", EINVAL},
	{ LTFS_XML_WRONG_MTIME_F,        "AEI0234E", EINVAL},
	{ LTFS_XML_WRONG_CRTIME_F,       "AEI0235E", EINVAL},
	{ LTFS_XML_WRONG_ATIME_F,        "AEI0236E", EINVAL},
	{ LTFS_XML_WRONG_CTIME_F,        "AEI0237E", EINVAL},
	{ LTFS_XML_WRONG_BTIME_F,        "AEI0238E", EINVAL},
	{ LTFS_XML_WRONG_SIZE,           "AEI0239E", EINVAL},
	{ LTFS_XML_WRONG_PART,           "AEI0240E", EINVAL},
	{ LTFS_XML_WRONG_START_BLK,      "AEI0241E", EINVAL},
	{ LTFS_XML_WRONG_OFFSET,         "AEI0242E", EINVAL},
	{ LTFS_XML_WRONG_BYTE_CNT,       "AEI0243E", EINVAL},
	{ LTFS_XML_WRONG_FILE_OFST,      "AEI0244E", EINVAL},
	{ LTFS_XML_EXT_OVERLAP,          "AEI0245E", EINVAL},
	{ LTFS_XML_EXT_TOO_LONG,         "AEI0246E", EINVAL},
	{ LTFS_XML_WRONG_FTIME_L,        "AEI0247E", EINVAL},
	{ LTFS_XML_WRONG_PART_MAP,       "AEI0248E", EINVAL},
	{ LTFS_XML_WRONG_BLOCKSIZE,      "AEI0249E", EINVAL},
	{ LTFS_XML_WRONG_COMP,           "AEI0250E", EINVAL},
    { LTFS_BAD_INDEX_TYPE,           "AEI0251E", EINVAL},
	{ EDEV_NO_SENSE,                 "AED0001E", EIO},
	{ EDEV_OVERRUN,                  "AED0002E", EIO},
	{ EDEV_UNDERRUN,                 "AED0003E", ENODATA},
	{ EDEV_FILEMARK_DETECTED,        "AED0004E", EIO},
	{ EDEV_EARLY_WARNING,            "AED0005E", EIO},
	{ EDEV_BOP_DETECTED,             "AED0006E", EIO},
	{ EDEV_PROG_EARLY_WARNING,       "AED0007E", EIO},
	{ EDEV_CLEANING_CART,            "AED0008E", EINVAL},
	{ EDEV_VOLTAG_NOT_READABLE,      "AED0009E", EINVAL},
	{ EDEV_LOCATION_NOT_PRESENT,     "AED0010E", EINVAL},
	{ EDEV_MEDIA_PRESENSE_UNKNOWN,   "AED0011E", EINVAL},
	{ EDEV_SLOT_UNKNOWN_STATE,       "AED0012E", EINVAL},
	{ EDEV_DRIVE_NOT_PRESENT,        "AED0013E", EINVAL},
	{ EDEV_RECORD_NOT_FOUND,         "AED0014E", ESPIPE},
	{ EDEV_INSUFFICIENT_TIME,        "AED0015E", EIO},
#ifdef EUCLEAN
	{ EDEV_CLEANING_REQUIRED,        "AED0016E", EUCLEAN},
#else
	{ EDEV_CLEANING_REQUIRED,        "AED0016E", EAGAIN},
#endif
	{ EDEV_RECOVERED_ERROR,          "AED0017E", EIO},
	{ EDEV_MODE_PARAMETER_ROUNDED,   "AED0018E", EIO},
	{ EDEV_DEGRADED_MEDIA,           "AED0019E", EIO},
	{ EDEV_NOT_READY,                "AED0020E", EAGAIN},
	{ EDEV_NOT_REPORTABLE,           "AED0021E", EAGAIN},
	{ EDEV_BECOMING_READY,           "AED0022E", EAGAIN},
	{ EDEV_NEED_INITIALIZE,          "AED0023E", EIO},
	{ EDEV_MANUAL_INTERVENTION,      "AED0024E", EAGAIN},
	{ EDEV_OPERATION_IN_PROGRESS,    "AED0025E", EAGAIN},
	{ EDEV_OFFLINE,                  "AED0026E", EAGAIN},
	{ EDEV_DOOR_OPEN,                "AED0027E", EAGAIN},
	{ EDEV_OVER_TEMPERATURE,         "AED0028E", EAGAIN},
#ifdef ENOMEDIUM
	{ EDEV_NO_MEDIUM,                "AED0029E", ENOMEDIUM},
#else
	{ EDEV_NO_MEDIUM,                "AED0029E", EAGAIN},
#endif /* ENOMEDIUM */
	{ EDEV_NOT_SELF_CONFIGURED_YET,  "AED0030E", EAGAIN},
	{ EDEV_PARAMETER_VALUE_REJECTED, "AED0031E", EINVAL},
	{ EDEV_CLEANING_IN_PROGRESS,     "AED0032E", EAGAIN},
	{ EDEV_IE_OPEN,                  "AED0033E", EAGAIN},
	{ EDEV_MEDIUM_ERROR,             "AED0034E", EIO},
	{ EDEV_RW_PERM,                  "AED0035E", EIO},
	{ EDEV_CM_PERM,                  "AED0036E", EIO},
	{ EDEV_MEDIUM_FORMAT_ERROR,      "AED0037E", EIO},
	{ EDEV_MEDIUM_FORMAT_CORRUPTED,  "AED0038E", EIO},
	{ EDEV_INTEGRITY_CHECK,          "AED0039E", EILSEQ},
	{ EDEV_LOAD_UNLOAD_ERROR,        "AED0040E", EIO},
	{ EDEV_CLEANING_FALIURE,         "AED0041E", EIO},
	{ EDEV_READ_PERM,                "AED0042E", EIO},
	{ EDEV_WRITE_PERM,               "AED0043E", EIO},
	{ EDEV_HARDWARE_ERROR,           "AED0044E", EIO},
	{ EDEV_LBP_WRITE_ERROR,          "AED0045E", EIO},
	{ EDEV_LBP_READ_ERROR,           "AED0046E", EIO},
	{ EDEV_NO_CONNECTION,            "AED0047E", EIO},
	{ EDEV_ILLEGAL_REQUEST,          "AED0048E", EILSEQ},
	{ EDEV_INVALID_FIELD_CDB,        "AED0049E", EILSEQ},
	{ EDEV_DEST_FULL,                "AED0050E", EIO},
	{ EDEV_SRC_EMPTY,                "AED0051E", EIO},
	{ EDEV_MAGAZINE_INACCESSIBLE,    "AED0052E", EIO},
	{ EDEV_INVALID_ADDRESS,          "AED0053E", EIDRM},
	{ EDEV_MEDIUM_LOCKED,            "AED0054E", EIO},
	{ EDEV_UNIT_ATTENTION,           "AED0055E", EIO},
	{ EDEV_MEDIUM_MAY_BE_CHANGED,    "AED0056E", EIO},
	{ EDEV_IE_ACCESSED,              "AED0057E", EIO},
	{ EDEV_POR_OR_BUS_RESET,         "AED0058E", EIO},
	{ EDEV_CONFIGURE_CHANGED,        "AED0059E", EIO},
	{ EDEV_COMMAND_CLEARED,          "AED0060E", EIO},
	{ EDEV_MEDIUM_REMOVAL_REQ,       "AED0061E", EIO},
	{ EDEV_MEDIA_REMOVAL_PREV,       "AED0062E", EIO},
	{ EDEV_DOOR_CLOSED,              "AED0063E", EIO},
	{ EDEV_TIME_STAMP_CHANGED,       "AED0064E", EIO},
	{ EDEV_RESERVATION_PREEMPTED,    "AED0065E", EIO},
	{ EDEV_RESERVATION_RELEASED,     "AED0066E", EIO},
	{ EDEV_REGISTRATION_PREEMPTED,   "AED0067E", EIO},
	{ EDEV_DATA_PROTECT,             "AED0068E", EIO},
	{ EDEV_WRITE_PROTECTED,          "AED0069E", EIO},
	{ EDEV_WRITE_PROTECTED_WORM,     "AED0070E", EIO},
	{ EDEV_WRITE_PROTECTED_OPERATOR, "AED0071E", EIO},
	{ EDEV_BLANK_CHECK,              "AED0072E", EIO},
	{ EDEV_EOD_DETECTED,             "AED0073E", ESPIPE},
	{ EDEV_EOD_NOT_FOUND,            "AED0074E", ESPIPE},
	{ EDEV_ABORTED_COMMAND,          "AED0075E", EIO},
	{ EDEV_OVERLAPPED,               "AED0076E", EIO},
	{ EDEV_TIMEOUT,                  "AED0077E", ETIMEDOUT},
	{ EDEV_ABORT_WAIT_READY,         "AED0078E", EIO},
	{ EDEV_OVERFLOW,                 "AED0079E", EIO},
	{ EDEV_CRYPTO_ERROR,             "AED0080E", EIO},
	{ EDEV_KEY_SERVICE_ERROR,        "AED0081E", EIO},
	{ EDEV_KEY_CHANGE_DETECTED,      "AED0082E", EIO},
	{ EDEV_KEY_REQUIRED,             "AED0083E", EIO},
	{ EDEV_INTERNAL_ERROR,           "AED0084E", EIO},
	{ EDEV_DRIVER_ERROR,             "AED0085E", EIO},
	{ EDEV_HOST_ERROR,               "AED0086E", EIO},
	{ EDEV_TARGET_ERROR,             "AED0087E", EIO},
	{ EDEV_DRIVER_ERROR,             "AED0085E", EIO},
	{ EDEV_NO_MEMORY,                "AED0088E", EIO},
	{ EDEV_UNSUPPORTED_FUNCTION,     "AED0089E", EIO},
	{ EDEV_PARAMETER_NOT_FOUND,      "AED0090E", EIO},
	{ EDEV_CANNOT_GET_SENSE,         "AED0091E", EIO},
	{ EDEV_INVALID_ARG,              "AED0092E", EINVAL},
	{ EDEV_DUMP_EIO,                 "AED0093E", EIO},
	{ EDEV_UNKNOWN,                  "AED0110E", EIO},
	{ EDEV_VENDOR_UNIQUE,            "AED0111E", EIO},
	{ EDEV_DEVICE_BUSY,              "AED0094E", EAGAIN},
	{ EDEV_DEVICE_UNOPENABLE,        "AED0095E", EIO},
	{ EDEV_DEVICE_UNSUPPORTABLE,     "AED0096E", EOPNOTSUPP},
	{ EDEV_INVALID_LICENSE,          "AED0097E", EOPNOTSUPP},
	{ EDEV_UNSUPPORTED_FIRMWARE,     "AED0098E", EOPNOTSUPP},
	{ EDEV_UNSUPPORETD_COMMAND,      "AED0099E", EOPNOTSUPP},
	{ EDEV_LENGTH_MISMATCH,          "AED0100E", EINVAL},
	{ EDEV_BUFFER_OVERFLOW,          "AED0101E", EINVAL},
	{ EDEV_DRIVES_MISMATCH,          "AED0102E", EINVAL},
	{ EDEV_RESERVATION_CONFLICT,     "AED0103E", EIO},
	{ EDEV_CONNECTION_LOST,          "AED0104E", EIO},
	{ EDEV_NO_RESERVATION_HOLDER,    "AED0105E", EIO},
	{ EDEV_NEED_FAILOVER,            "AED0106E", EIO},
	{ EDEV_REAL_POWER_ON_RESET,      "AED0107E", EIO},
	{ EDEV_BUFFER_ALLOCATE_ERROR,    "AED0108E", EIO},
	{ EDEV_RETRY,                    "AED0109E", EIO},
	{ -1, NULL, 0 }
};

int errormap_init()
{
	struct error_map *err;

	HASH_ADD_INT(fuse_errormap, ltfs_error, fuse_error_list);
	if (! fuse_errormap) {
		ltfsmsg(ALC0002E, __FUNCTION__);
		return -LTFS_NO_MEMORY;
	}
	for (err=fuse_error_list+1; err->ltfs_error!=-1; ++err)
		HASH_ADD_INT(fuse_errormap, ltfs_error, err);

	return 0;
}

void errormap_finish()
{
	HASH_CLEAR(hh, fuse_errormap);
}

int errormap_fuse_error(int val)
{
	struct error_map *out;

	val = -val;
	if (val < LTFS_ERR_MIN)
		return -val;

	HASH_FIND_INT(fuse_errormap, &val, out);
	if (out)
		return -out->general_error;

	return -EIO;
}

char* errormap_msg_id(int val)
{
	struct error_map *out;

	val = -val;
	if (val < LTFS_ERR_MIN)
		return NULL;

	HASH_FIND_INT(fuse_errormap, &val, out);
	if (out)
		return out->msd_id;

	return NULL;
}
