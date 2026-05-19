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
	{ LTFS_NULL_ARG,                 "AEI1000E", EINVAL},
	{ LTFS_NO_MEMORY,                "AEI1001E", ENOMEM},
	{ LTFS_MUTEX_INVALID,            "AEI1002E", EINVAL},
	{ LTFS_MUTEX_UNLOCKED,           "AEI1003E", EINVAL},
	{ LTFS_BAD_DEVICE_DATA,          "AEI1004E", EINVAL},
	{ LTFS_BAD_PARTNUM,              "AEI1005E", EINVAL},
	{ LTFS_LIBXML2_FAILURE,          "AEI1006E", EINVAL},
	{ LTFS_DEVICE_UNREADY,           "AEI1007E", EAGAIN},
#ifdef ENOMEDIUM
	{ LTFS_NO_MEDIUM,                "AEI1008E", ENOMEDIUM},
#else
	{ LTFS_NO_MEDIUM,                "AEI1008E", EAGAIN},
#endif /* ENOMEDIUM */
	{ LTFS_LARGE_BLOCKSIZE,          "AEI1009E", EINVAL},
	{ LTFS_BAD_LOCATE,               "AEI1010E", EIO},
	{ LTFS_NOT_PARTITIONED,          "AEI1011E", EINVAL},
	{ LTFS_LABEL_INVALID,            "AEI1012E", EINVAL},
	{ LTFS_LABEL_MISMATCH,           "AEI1013E", EINVAL},
	{ LTFS_INDEX_INVALID,            "AEI1014E", EINVAL},
	{ LTFS_INCONSISTENT,             "AEI1015E", EINVAL},
	{ LTFS_UNSUPPORTED_MEDIUM,       "AEI1016E", EINVAL},
	{ LTFS_GENERATION_MISMATCH,      "AEI1017E", EINVAL},
	{ LTFS_MAM_CACHE_INVALID,        "AEI1018E", EINVAL},
	{ LTFS_INDEX_CACHE_INVALID,      "AEI1019E", EINVAL},
	{ LTFS_POLICY_EMPTY_RULE,        "AEI1020E", EINVAL},
	{ LTFS_MUTEX_INIT,               "AEI1021E", EINVAL},
	{ LTFS_BAD_ARG,                  "AEI1022E", EINVAL},
	{ LTFS_NAMETOOLONG,              "AEI1023E", ENAMETOOLONG},
	{ LTFS_NO_DENTRY,                "AEI1024E", ENOENT},
	{ LTFS_INVALID_PATH,             "AEI1025E", EINVAL},
	{ LTFS_INVALID_SRC_PATH,         "AEI1026E", ENOENT},
	{ LTFS_DENTRY_EXISTS,            "AEI1027E", EEXIST},
	{ LTFS_DIRNOTEMPTY,              "AEI1028E", ENOTEMPTY},
	{ LTFS_UNLINKROOT,               "AEI1029E", EBUSY},
	{ LTFS_DIRMOVE,                  "AEI1030E", EIO},
	{ LTFS_RENAMELOOP,               "AEI1031E", EINVAL},
	{ LTFS_SMALL_BLOCK,              "AEI1032E", EIO},
	{ LTFS_ISDIRECTORY,              "AEI1033E", EINVAL},
	{ LTFS_EOD_MISSING_MEDIUM,       "AEI1034E", EINVAL},
	{ LTFS_BOTH_EOD_MISSING,         "AEI1035E", EIO},
	{ LTFS_UNEXPECTED_VALUE,         "AEI1036E", EIO},
	{ LTFS_UNSUPPORTED,              "AEI1037E", EIO},
	{ LTFS_LABEL_POSSIBLE_VALID,     "AEI1038E", EIO},
	{ LTFS_CLOSE_FS_IF,              "AEI1039E", EIDRM},
#ifdef ENOATTR
	{ LTFS_NO_XATTR,                 "AEI1040E", ENOATTR},
#else
	{ LTFS_NO_XATTR,                 "AEI1040E", ENODATA},
#endif /* ENOATTR */
	{ LTFS_SIG_HANDLER_ERR,          "AEI1041E", EINVAL},
	{ LTFS_INTERRUPTED,              "AEI1042E", ECANCELED},
	{ LTFS_UNSUPPORTED_INDEX_VERSION,"AEI1043E", EINVAL},
	{ LTFS_ICU_ERROR,                "AEI1044E", EINVAL},
	{ LTFS_PLUGIN_LOAD,              "AEI1045E", EINVAL},
	{ LTFS_PLUGIN_UNLOAD,            "AEI1046E", EINVAL},
	{ LTFS_RDONLY_XATTR,             "AEI1047E", EACCES},
	{ LTFS_XATTR_EXISTS,             "AEI1048E", EEXIST},
	{ LTFS_SMALL_BUFFER,             "AEI1049E", ERANGE},
	{ LTFS_RDONLY_VOLUME,            "AEI1050E", EROFS},
	{ LTFS_NO_SPACE,                 "AEI1051E", ENOSPC},
	{ LTFS_LARGE_XATTR,              "AEI1052E", ENOSPC},
	{ LTFS_NO_INDEX,                 "AEI1053E", ENODATA},
	{ LTFS_XATTR_NAMESPACE,          "AEI1054E", EOPNOTSUPP},
	{ LTFS_CONFIG_INVALID,           "AEI1055E", EINVAL},
	{ LTFS_PLUGIN_INCOMPLETE,        "AEI1056E", EINVAL},
	{ LTFS_NO_PLUGIN,                "AEI1057E", ENOENT},
	{ LTFS_POLICY_INVALID,           "AEI1058E", EINVAL},
	{ LTFS_ISFILE,                   "AEI1059E", ENOTDIR},
	{ LTFS_UNRESOLVED_VOLUME,        "AEI1060E", EBUSY},
	{ LTFS_POLICY_IMMUTABLE,         "AEI1061E", EPERM},
	{ LTFS_SMALL_BLOCKSIZE,          "AEI1062E", EINVAL},
	{ LTFS_BARCODE_LENGTH,           "AEI1063E", EINVAL},
	{ LTFS_BARCODE_INVALID,          "AEI1064E", EINVAL},
	{ LTFS_RESOURCE_SHORTAGE,        "AEI1065E", EBUSY},
	{ LTFS_DEVICE_FENCED,            "AEI1066E", EAGAIN},
	{ LTFS_REVAL_RUNNING,            "AEI1067E", EAGAIN},
	{ LTFS_REVAL_FAILED,             "AEI1068E", EFAULT},
	{ LTFS_SLOT_FULL,                "AEI1069E", EFAULT},
	{ LTFS_SLOT_SHORTAGE,            "AEI1070E", EFAULT},
	{ LTFS_CHANGER_ERROR,            "AEI1071E", EIO},
	{ LTFS_UNEXPECTED_TAPE,          "AEI1072E", EINVAL},
	{ LTFS_NO_HOMESLOT,              "AEI1073E", EINVAL},
	{ LTFS_MOVE_ACTIVE_CART,         "AEI1074E", ECANCELED},
	{ LTFS_NO_IE_SLOT,               "AEI1075E", ECANCELED},
	{ LTFS_INVALID_SLOT,             "AEI1076E", EINVAL},
	{ LTFS_UNSUPPORTED_CART,         "AEI1077E", EINVAL},
	{ LTFS_CART_STUCKED,             "AEI1078E", EIO},
	{ LTFS_OP_NOT_ALLOWED,           "AEI1079E", EINVAL},
	{ LTFS_OP_TO_DUP,                "AEI1080E", EINVAL},
	{ LTFS_OP_TO_NON_SUP,            "AEI1081E", EINVAL},
	{ LTFS_OP_TO_INACC,              "AEI1082E", EINVAL},
	{ LTFS_OP_TO_UNFMT,              "AEI1083E", EINVAL},
	{ LTFS_OP_TO_INV,                "AEI1084E", EINVAL},
	{ LTFS_OP_TO_ERR,                "AEI1085E", EINVAL},
	{ LTFS_OP_TO_CRIT,               "AEI1086E", EINVAL},
	{ LTFS_OP_TO_CLN,                "AEI1087E", EINVAL},
	{ LTFS_OP_TO_RO,                 "AEI1088E", EINVAL},
	{ LTFS_ALREADY_FS_INC,           "AEI1089E", EINVAL},
	{ LTFS_NOT_IN_FS,                "AEI1090E", EINVAL},
	{ LTFS_FS_CART_TO_IE,            "AEI1091E", EINVAL},
	{ LTFS_OP_TO_UNKN,               "AEI1092E", EINVAL},
	{ LTFS_DRV_LOCKED,               "AEI1093E", EINVAL},
	{ LTFS_DRV_ALRDY_ADDED,          "AEI1094E", EINVAL},
	{ LTFS_FORCE_INVENTORY,          "AEI1095E", EIO},
	{ LTFS_INVENTORY_FAILED,         "AEI1096E", EFAULT},
	{ LTFS_RESTART_OPERATION,        "AEI1097E", EIO},
	{ LTFS_NO_TARGET_DRIVE,          "AEI1098E", EINVAL},
	{ LTFS_NO_DCACHE_FSTYPE,         "AEI1099E", EINVAL},
	{ LTFS_IMAGE_EXISTED,            "AEI1100E", EINVAL},
	{ LTFS_IMAGE_MOUNTED,            "AEI1101E", EIO},
	{ LTFS_IMAGE_NOT_MOUNTED,        "AEI1102E", EIO},
	{ LTFS_MTAB_NOREGULAR,           "AEI1103E", EIO},
	{ LTFS_MTAB_OPEN,                "AEI1104E", EIO},
	{ LTFS_MTAB_LOCK,                "AEI1105E", EIO},
	{ LTFS_MTAB_SEEK,                "AEI1106E", EIO},
	{ LTFS_MTAB_UPDATE,              "AEI1107E", EIO},
	{ LTFS_MTAB_FLUSH,               "AEI1108E", EIO},
	{ LTFS_MTAB_UNLOCK,              "AEI1109E", EIO},
	{ LTFS_MTAB_CLOSE,               "AEI1110E", EIO},
	{ LTFS_MTAB_COPY,                "AEI1111E", EIO},
	{ LTFS_MTAB_TEMP_OPEN,           "AEI1112E", EIO},
	{ LTFS_MTAB_TEMP_SEEK,           "AEI1113E", EIO},
	{ LTFS_DCACHE_CREATION_FAIL,     "AEI1114E", EIO},
	{ LTFS_DCACHE_UNSUPPORTED,       "AEI1115E", EINVAL},
	{ LTFS_DCACHE_EXTRA_SPACE,       "AEI1116E", EINVAL},
	{ LTFS_KEY_NOT_FOUND,            "AEI1117E", EINVAL},
	{ LTFS_INVALID_SEQUENCE,         "AEI1118E", EINVAL},
	{ LTFS_RDONLY_ROOT,              "AEI1119E", EACCES},
	{ LTFS_SYMLINK_CONFLICT,         "AEI1120E", EIO},
	{ LTFS_NETWORK_INIT_FAIL,        "AEI1121E", EINVAL},
	{ LTFS_DRIVE_SHORTAGE,           "AEI1122E", ENODEV},
	{ LTFS_INVALID_VOLSER,           "AEI1123E", EINVAL},
	{ LTFS_LESS_SPACE,               "AEI1124E", ENOSPC},
	{ LTFS_WRITE_PROTECT,            "AEI1125E", EROFS},
	{ LTFS_WRITE_ERROR,              "AEI1126E", EROFS},
	{ LTFS_UNEXPECTED_BARCODE,       "AEI1127E", EIO},
	{ LTFS_STRING_CONVERSION,        "AEI1128E", EINVAL},
	{ LTFS_SESSION_INIT_FAIL,        "AEI1129E", EIO},
	{ LTFS_MESSAGE_INVALID,          "AEI1130E", EINVAL},
	{ LTFS_PASSWORD_INVALID,         "AEI1131E", EPERM},
	{ LTFS_NOT_AUTHENTICATERD,       "AEI1132E", EINVAL},
	{ LTFS_WORM_DEEP_RECOVERY,       "AEI1133E", EINVAL},
	{ LTFS_WORM_ROLLBACK,            "AEI1134E", EINVAL},
	{ LTFS_NONWORM_SALVAGE,          "AEI1135E", EINVAL},
	{ LTFS_FORMATTED,                "AEI1136E", EPERM},
	{ LTFS_RULES_WORM,               "AEI1137E", EINVAL},
	{ LTFS_BAD_BLOCKSIZE,            "AEI1138E", EINVAL},
	{ LTFS_BAD_VOLNAME,              "AEI1139E", EINVAL},
	{ LTFS_BAD_RULES,                "AEI1140E", EINVAL},
	{ LTFS_GEN_NEEDED,               "AEI1141E", EINVAL},
	{ LTFS_BAD_GENERATION,           "AEI1142E", EINVAL},
	{ LTFS_NO_ROLLBACK_TARGET,       "AEI1143E", EINVAL},
	{ LTFS_MANY_INDEXES,             "AEI1144E", EINVAL},
	{ LTFS_SALVAGE_NOT_NEEDED,       "AEI1145E", EINVAL},
	{ LTFS_WORM_ENABLED,             "AEI1146E", EACCES},
	{ LTFS_OUTSTANDING_REFS,         "AEI1147E", EBUSY},
	{ LTFS_REBUILD_IN_PROGRESS,      "AEI1148E", EBUSY},
	{ LTFS_MULTIPLE_START,           "AEI1149E", EINVAL},
	{ LTFS_CARTRIDGE_NOT_FOUND,      "AEI1150E", EINVAL},
	{ LTFS_CACHE_LOCK_ERR,           "AEI1151E", EIO},
	{ LTFS_CACHE_UNLOCK_ERR,         "AEI1152E", EIO},
	{ LTFS_CREPO_FILE_ERR,           "AEI1153E", EIO},
	{ LTFS_CREPO_READ_ERR,           "AEI1154E", EIO},
	{ LTFS_CREPO_WRITE_ERR,          "AEI1155E", EIO},
	{ LTFS_CREPO_INVALID_OP,         "AEI1156E", EINVAL},
	{ LTFS_FILE_ERR,                 "AEI1157E", EIO},
	{ LTFS_CARTRIDGE_IN_USE,         "AEI1158E", EBUSY},
	{ LTFS_NO_LOCK_ENTRY,            "AEI1159E", ENOENT},
	{ LTFS_MOUNT_ERR,                "AEI1160E", EIO},
	{ LTFS_NO_DEVICE,                "AEI1161E", ENODEV},
	{ LTFS_XATTR_ERR,                "AEI1162E", EIO},
	{ LTFS_FTW_ERR,                  "AEI1163E", EIO},
	{ LTFS_TIME_ERR,                 "AEI1164E", EIO},
	{ LTFS_NOT_BLOCK_DEVICE,         "AEI1165E", ENOTBLK},
	{ LTFS_QUOTA_EXCEEDED,           "AEI1166E", EDQUOT},
	{ LTFS_TOO_MANY_OPEN_FILES,      "AEI1167E", ENFILE},
	{ LTFS_LINKDIR_EXISTS,           "AEI1168E", EEXIST},
	{ LTFS_NO_DMAP_ENTRY,            "AEI1169E", ENOENT},
	{ LTFS_RECOVERABLE_FILE_ERR,     "AEI1170E", EAGAIN},
	{ LTFS_NO_DCACHE_SPC,            "AEI1171E", ENOSPC},
	{ LTFS_POS_SUSPECT_BOP,          "AEI1172E", EIO},
	{ LTFS_IOSCHED_INIT,             "AEI1173E", EIO},
	/* Unused 1174 - 1179 */
	{ LTFS_CACHE_IO,                 "AEI1180E", EIO },
	{ LTFS_CACHE_DISCARDED,          "AEI1181E", ENOENT },
	{ LTFS_LONG_WRITE_LOCK,          "AEI1182E", EAGAIN },
	{ LTFS_INCOMPATIBLE_CACHE,       "AEI1183E", EINVAL },
	{ LTFS_DCACHE_NOT_INITIALIZED,   "AEI1184E", EIO },
	{ LTFS_CONFIG_FILE_WLOCKED,      "AEI1185E", EINVAL },
	{ LTFS_CREATE_QUEUE,             "AEI1186E", EIO },
	{ LTFS_FORK_ERROR,               "AEI1187E", EIO },
	{ LTFS_NOACK,                    "AEI1188E", EIO },
	{ LTFS_NODE_DETECT_FAIL,         "AEI1189E", EIO },
	{ LTFS_INVALID_MESSAGE,          "AEI1190E", EIO },
	{ LTFS_NODE_DEGATE_FAIL,         "AEI1191E", EIO },
	{ LTFS_CLUSTER_MRSW_FAIL,        "AEI1192E", EIO },
	{ LTFS_CART_NOT_MOUNTED,         "AEI1193E", EBUSY},
	{ LTFS_RDONLY_DEN_DRV,           "AEI1194E", EINVAL},
	{ LTFS_NEED_DRIVE_SELECTION,     "AEI1195E", EINVAL},
	{ LTFS_MUTEX_ALREADY_LOCKED,     "AEI1196E", EINVAL},
	{ LTFS_TAPE_UNDER_PROCESS,       "AEI1197E", EBUSY},
	{ LTFS_TAPE_REMOVED,             "AEI1198E", EIDRM},
	{ LTFS_NEED_MOVE,                "AEI1199E", EINVAL},
	{ LTFS_NEED_START_OVER,          "AEI1200E", EINVAL},
	{ LTFS_LOCATE_ERROR,             "AEI1201E", EIO},
	{ LTFS_STATS_DB_OPEN,            "AEI1202E", EIO},
	{ LTFS_NO_TRAIL_FM,              "AEI1203E", EINVAL},
	{ LTFS_SAFENAME_FAIL,            "AEI1204E", EINVAL},
	{ LTFS_SYNC_FAIL_ON_DP,          "AEI1205E", EIO},
	{ LTFS_XML_READ_FAIL,            "AEI5000E", EINVAL},
	{ LTFS_XML_CONST_FAIL,           "AEI5001E", EINVAL},
	{ LTFS_XML_WRONG_NODE,           "AEI5002E", EINVAL},
	{ LTFS_XML_UNEXPECTED_EOF,       "AEI5003E", EINVAL},
	{ LTFS_XML_EMPTY_UNKNOWN,        "AEI5004E", EINVAL},
	{ LTFS_XML_EMPTY,                "AEI5005E", EINVAL},
	{ LTFS_XML_SKIP_FAIL,            "AEI5006E", EINVAL},
	{ LTFS_XML_NO_REQUIRED_TAG,      "AEI5007E", EINVAL},
	{ LTFS_XML_DUPLICATED_TAG,       "AEI5008E", EINVAL},
	{ LTFS_XML_OPEN_TAG,             "AEI5009E", EINVAL},
	{ LTFS_XML_SAVE_FAIL,            "AEI5010E", EINVAL},
	{ LTFS_XML_WRONG_TOPTAG,         "AEI5011E", EINVAL},
	{ LTFS_XML_WRONG_ENCODING,       "AEI5012E", EINVAL},
	{ LTFS_XML_TOP_ATTR_FAIL,        "AEI5013E", EINVAL},
	{ LTFS_XML_WRONG_UUID,           "AEI5014E", EINVAL},
	{ LTFS_XML_WRONG_GEN,            "AEI5015E", EINVAL},
	{ LTFS_XML_WRONG_UTIME,          "AEI5016E", EINVAL},
	{ LTFS_XML_WRONG_LOC,            "AEI5017E", EINVAL},
	{ LTFS_XML_WRONG_LOC_PREV,       "AEI5018E", EINVAL},
	{ LTFS_XML_WRONG_PA,             "AEI5019E", EINVAL},
	{ LTFS_XML_WRONG_POLICY,         "AEI5020E", EINVAL},
	{ LTFS_XML_TOO_LONG_COMMENT,     "AEI5021E", EINVAL},
	{ LTFS_XML_WRONG_NEXT,           "AEI5022E", EINVAL},
	{ LTFS_XML_WRONG_RO_DIR,         "AEI5023E", EINVAL},
	{ LTFS_XML_WRONG_MTIME_DIR,      "AEI5024E", EINVAL},
	{ LTFS_XML_WRONG_CRTIME_DIR,     "AEI5025E", EINVAL},
	{ LTFS_XML_WRONG_ATIME_DIR,      "AEI5026E", EINVAL},
	{ LTFS_XML_WRONG_CTIME_DIR,      "AEI5027E", EINVAL},
	{ LTFS_XML_WRONG_BTIME_DIR,      "AEI5028E", EINVAL},
	{ LTFS_XML_XATTR_TYPE,           "AEI5029E", EINVAL},
	{ LTFS_XML_XATTR_SIZE,           "AEI5030E", EINVAL},
	{ LTFS_XML_WRONG_UID,            "AEI5031E", EINVAL},
	{ LTFS_XML_INVALID_UID,          "AEI5032E", EINVAL},
	{ LTFS_XML_WRONG_RO_F,           "AEI5033E", EINVAL},
	{ LTFS_XML_WRONG_MTIME_F,        "AEI5034E", EINVAL},
	{ LTFS_XML_WRONG_CRTIME_F,       "AEI5035E", EINVAL},
	{ LTFS_XML_WRONG_ATIME_F,        "AEI5036E", EINVAL},
	{ LTFS_XML_WRONG_CTIME_F,        "AEI5037E", EINVAL},
	{ LTFS_XML_WRONG_BTIME_F,        "AEI5038E", EINVAL},
	{ LTFS_XML_WRONG_SIZE,           "AEI5039E", EINVAL},
	{ LTFS_XML_WRONG_PART,           "AEI5040E", EINVAL},
	{ LTFS_XML_WRONG_START_BLK,      "AEI5041E", EINVAL},
	{ LTFS_XML_WRONG_OFFSET,         "AEI5042E", EINVAL},
	{ LTFS_XML_WRONG_BYTE_CNT,       "AEI5043E", EINVAL},
	{ LTFS_XML_WRONG_FILE_OFST,      "AEI5044E", EINVAL},
	{ LTFS_XML_EXT_OVERLAP,          "AEI5045E", EINVAL},
	{ LTFS_XML_EXT_TOO_LONG,         "AEI5046E", EINVAL},
	{ LTFS_XML_WRONG_FTIME_L,        "AEI5047E", EINVAL},
	{ LTFS_XML_WRONG_PART_MAP,       "AEI5048E", EINVAL},
	{ LTFS_XML_WRONG_BLOCKSIZE,      "AEI5049E", EINVAL},
	{ LTFS_XML_WRONG_COMP,           "AEI5050E", EINVAL},
    { LTFS_BAD_INDEX_TYPE,           "AEI5051E", EINVAL},
	{ EDEV_NO_SENSE,                 "AED0000E", EIO},
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
	{ EDEV_CLEANING_REQUIRED,        "AED0098E", EUCLEAN},
#else
	{ EDEV_CLEANING_REQUIRED,        "AED0098E", EAGAIN},
#endif
	{ EDEV_RECOVERED_ERROR,          "AED0100E", EIO},
	{ EDEV_MODE_PARAMETER_ROUNDED,   "AED0101E", EIO},
	{ EDEV_DEGRADED_MEDIA,           "AED0198E", EIO},
	{ EDEV_NOT_READY,                "AED0200E", EAGAIN},
	{ EDEV_NOT_REPORTABLE,           "AED0201E", EAGAIN},
	{ EDEV_BECOMING_READY,           "AED0202E", EAGAIN},
	{ EDEV_NEED_INITIALIZE,          "AED0203E", EIO},
	{ EDEV_MANUAL_INTERVENTION,      "AED0204E", EAGAIN},
	{ EDEV_OPERATION_IN_PROGRESS,    "AED0205E", EAGAIN},
	{ EDEV_OFFLINE,                  "AED0206E", EAGAIN},
	{ EDEV_DOOR_OPEN,                "AED0207E", EAGAIN},
	{ EDEV_OVER_TEMPERATURE,         "AED0208E", EAGAIN},
#ifdef ENOMEDIUM
	{ EDEV_NO_MEDIUM,                "AED0209E", ENOMEDIUM},
#else
	{ EDEV_NO_MEDIUM,                "AED0209E", EAGAIN},
#endif /* ENOMEDIUM */
	{ EDEV_NOT_SELF_CONFIGURED_YET,  "AED0210E", EAGAIN},
	{ EDEV_PARAMETER_VALUE_REJECTED, "AED0211E", EINVAL},
	{ EDEV_CLEANING_IN_PROGRESS,     "AED0297E", EAGAIN},
	{ EDEV_IE_OPEN,                  "AED0298E", EAGAIN},
	{ EDEV_MEDIUM_ERROR,             "AED0300E", EIO},
	{ EDEV_RW_PERM,                  "AED0301E", EIO},
	{ EDEV_CM_PERM,                  "AED0302E", EIO},
	{ EDEV_MEDIUM_FORMAT_ERROR,      "AED0303E", EIO},
	{ EDEV_MEDIUM_FORMAT_CORRUPTED,  "AED0304E", EIO},
	{ EDEV_INTEGRITY_CHECK,          "AED0305E", EILSEQ},
	{ EDEV_LOAD_UNLOAD_ERROR,        "AED0306E", EIO},
	{ EDEV_CLEANING_FALIURE,         "AED0307E", EIO},
	{ EDEV_READ_PERM,                "AED0308E", EIO},
	{ EDEV_WRITE_PERM,               "AED0309E", EIO},
	{ EDEV_HARDWARE_ERROR,           "AED0400E", EIO},
	{ EDEV_LBP_WRITE_ERROR,          "AED0401E", EIO},
	{ EDEV_LBP_READ_ERROR,           "AED0402E", EIO},
	{ EDEV_NO_CONNECTION,            "AED0403E", EIO},
	{ EDEV_ILLEGAL_REQUEST,          "AED0500E", EILSEQ},
	{ EDEV_INVALID_FIELD_CDB,        "AED0501E", EILSEQ},
	{ EDEV_DEST_FULL,                "AED0502E", EIO},
	{ EDEV_SRC_EMPTY,                "AED0503E", EIO},
	{ EDEV_MAGAZINE_INACCESSIBLE,    "AED0504E", EIO},
	{ EDEV_INVALID_ADDRESS,          "AED0505E", EIDRM},
	{ EDEV_MEDIUM_LOCKED,            "AED0506E", EIO},
	{ EDEV_UNIT_ATTENTION,           "AED0600E", EIO},
	{ EDEV_MEDIUM_MAY_BE_CHANGED,    "AED0601E", EIO},
	{ EDEV_IE_ACCESSED,              "AED0602E", EIO},
	{ EDEV_POR_OR_BUS_RESET,         "AED0603E", EIO},
	{ EDEV_CONFIGURE_CHANGED,        "AED0604E", EIO},
	{ EDEV_COMMAND_CLEARED,          "AED0605E", EIO},
	{ EDEV_MEDIUM_REMOVAL_REQ,       "AED0606E", EIO},
	{ EDEV_MEDIA_REMOVAL_PREV,       "AED0607E", EIO},
	{ EDEV_DOOR_CLOSED,              "AED0608E", EIO},
	{ EDEV_TIME_STAMP_CHANGED,       "AED0609E", EIO},
	{ EDEV_RESERVATION_PREEMPTED,    "AED0610E", EIO},
	{ EDEV_RESERVATION_RELEASED,     "AED0611E", EIO},
	{ EDEV_REGISTRATION_PREEMPTED,   "AED0612E", EIO},
	{ EDEV_DATA_PROTECT,             "AED0700E", EIO},
	{ EDEV_WRITE_PROTECTED,          "AED0701E", EIO},
	{ EDEV_WRITE_PROTECTED_WORM,     "AED0702E", EIO},
	{ EDEV_WRITE_PROTECTED_OPERATOR, "AED0703E", EIO},
	{ EDEV_BLANK_CHECK,              "AED0800E", EIO},
	{ EDEV_EOD_DETECTED,             "AED0801E", ESPIPE},
	{ EDEV_EOD_NOT_FOUND,            "AED0802E", ESPIPE},
	{ EDEV_ABORTED_COMMAND,          "AED1100E", EIO},
	{ EDEV_OVERLAPPED,               "AED1101E", EIO},
	{ EDEV_TIMEOUT,                  "AED1102E", ETIMEDOUT},
	{ EDEV_ABORT_WAIT_READY,         "AED1103E", EIO},
	{ EDEV_OVERFLOW,                 "AED1300E", EIO},
	{ EDEV_CRYPTO_ERROR,             "AED1600E", EIO},
	{ EDEV_KEY_SERVICE_ERROR,        "AED1601E", EIO},
	{ EDEV_KEY_CHANGE_DETECTED,      "AED1602E", EIO},
	{ EDEV_KEY_REQUIRED,             "AED1603E", EIO},
	{ EDEV_INTERNAL_ERROR,           "AED1700E", EIO},
	{ EDEV_DRIVER_ERROR,             "AED1701E", EIO},
	{ EDEV_DRIVER_ERROR,             "AED1701E", EIO},
	{ EDEV_HOST_ERROR,               "AED1702E", EIO},
	{ EDEV_TARGET_ERROR,             "AED1703E", EIO},
	{ EDEV_NO_MEMORY,                "AED1704E", EIO},
	{ EDEV_UNSUPPORTED_FUNCTION,     "AED1705E", EIO},
	{ EDEV_PARAMETER_NOT_FOUND,      "AED1706E", EIO},
	{ EDEV_CANNOT_GET_SENSE,         "AED1707E", EIO},
	{ EDEV_INVALID_ARG,              "AED1708E", EINVAL},
	{ EDEV_DUMP_EIO,                 "AED1709E", EIO},
	{ EDEV_DEVICE_BUSY,              "AED1710E", EAGAIN},
	{ EDEV_DEVICE_UNOPENABLE,        "AED1711E", EIO},
	{ EDEV_DEVICE_UNSUPPORTABLE,     "AED1712E", EOPNOTSUPP},
	{ EDEV_INVALID_LICENSE,          "AED1713E", EOPNOTSUPP},
	{ EDEV_UNSUPPORTED_FIRMWARE,     "AED1714E", EOPNOTSUPP},
	{ EDEV_UNSUPPORETD_COMMAND,      "AED1715E", EOPNOTSUPP},
	{ EDEV_LENGTH_MISMATCH,          "AED1716E", EINVAL},
	{ EDEV_BUFFER_OVERFLOW,          "AED1717E", EINVAL},
	{ EDEV_DRIVES_MISMATCH,          "AED1718E", EINVAL},
	{ EDEV_RESERVATION_CONFLICT,     "AED1719E", EIO},
	{ EDEV_CONNECTION_LOST,          "AED1720E", EIO},
	{ EDEV_NO_RESERVATION_HOLDER,    "AED1721E", EIO},
	{ EDEV_NEED_FAILOVER,            "AED1722E", EIO},
	{ EDEV_REAL_POWER_ON_RESET,      "AED1723E", EIO},
	{ EDEV_BUFFER_ALLOCATE_ERROR,    "AED1724E", EIO},
	{ EDEV_RETRY,                    "AED1725E", EIO},
	{ EDEV_UNKNOWN,                  "AED9998E", EIO},
	{ EDEV_VENDOR_UNIQUE,            "AED9999E", EIO},
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
