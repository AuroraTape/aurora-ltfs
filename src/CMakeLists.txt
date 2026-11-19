# libaltfs
add_library(libaltfs SHARED
    libltfs/base64.c
    libltfs/base64.h
    libltfs/config_file.c
    libltfs/config_file.h
    libltfs/dcache.c
    libltfs/dcache.h
    libltfs/dcache_ops.h
    libltfs/fs.c
    libltfs/fs.h
    libltfs/inc_journal.c
    libltfs/inc_journal.h
    libltfs/index_criteria.c
    libltfs/index_criteria.h
    libltfs/iosched.c
    libltfs/iosched.h
    libltfs/iosched_ops.h
    libltfs/kmi.c
    libltfs/kmi.h
    libltfs/kmi_ops.h
    libltfs/label.c
    libltfs/label.h
    libltfs/ltfs.c
    libltfs/ltfs_endian.h
    libltfs/ltfs_error.h
    libltfs/ltfs_fsops.c
    libltfs/ltfs_fsops.h
    libltfs/ltfs_fsops_raw.c
    libltfs/ltfs_fsops_raw.h
    libltfs/ltfs_fuse_version.h
    libltfs/ltfs.h
    libltfs/ltfs_internal.c
    libltfs/ltfs_internal.h
    libltfs/ltfs_locking.h
    libltfs/ltfs_locking_new.h
    libltfs/ltfs_locking_old.h
    libltfs/ltfslogging.c
    libltfs/ltfslogging.h
    libltfs/ltfs_thread.c
    libltfs/ltfs_thread.h
    libltfs/ltfstrace.c
    libltfs/ltfstrace.h
    libltfs/ltfs_types.h
    libltfs/pathname.c
    libltfs/pathname.h
    libltfs/periodic_sync.c
    libltfs/periodic_sync.h
    libltfs/plugin.c
    libltfs/plugin.h
    libltfs/queue.h
    libltfs/tape.c
    libltfs/tape.h
    libltfs/tape_ops.h
    libltfs/uthash_ext.h
    libltfs/uthash.h
    libltfs/xattr.c
    libltfs/xattr.h
    libltfs/xml_common.c
    libltfs/xml.h
    libltfs/xml_libltfs.h
    libltfs/xml_reader.c
    libltfs/xml_reader_libltfs.c
    libltfs/xml_writer.c
    libltfs/xml_writer_libltfs.c
    # arch
    libltfs/arch/arch_info.c
    libltfs/arch/arch_info.h
    libltfs/arch/errormap.c
    libltfs/arch/errormap.h
    libltfs/arch/filename_handling.c
    libltfs/arch/filename_handling.h
    libltfs/arch/signal_internal.h
    libltfs/arch/time_internal.c
    libltfs/arch/time_internal.h
    libltfs/arch/uuid_internal.c
    libltfs/arch/uuid_internal.h
    libltfs/arch/version.h
)

if(APPLE)
    target_sources(libaltfs
        libltfs/arch/osx/osx_string.c
        libltfs/arch/osx/osx_string.h
    )
elseif(BSD)
    target_sources(libaltfs
        libltfs/arch/freebsd/errno.h
        libltfs/arch/freebsd/freebsd_locking_old.h
        libltfs/arch/freebsd/xattr.h
    )
endif()

# Interal libraries

# iosched
add_library(iosched-fcfs MODULE)

add_library(iosched-unified MODULE)

# kmi
add_library(kmi-flatfile MODULE)

add_library(kmi-simple MODULE)

# tape
add_library(tape-file MODULE)

add_library(tape-itdtimg MODULE)

add_library(tape-sg MODULE)

# Exectuables

# altfs
add_executable(altfs
    cmd/altfs/altfs.c
    cmd/altfs/ltfs_fuse.c
    cmd/altfs/ltfs_fuse.h
)

# altfs_ordered_copy - python file, no compilation needed
# configure()

# altfsck
add_executable(altfsck
    cmd/altfsck/altfsck.c
)

# altfsctl - python file, no compilation needed
# configure()

# altfsindextool
add_executable(altfsindextool
    cmd/altfsindextool/altfsindextool.c
)

# mkaltfs
add_executable(mkaltfs
    cmd/mkaltfs/mkaltfs.c
)

# Libraries linking

# Installation rules