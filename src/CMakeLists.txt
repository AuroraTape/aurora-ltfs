# Add present directory to includes
include_directories(${CMAKE_CURRENT_SOURCE_DIR})

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

set_target_properties(libaltfs PROPERTIES OUTPUT_NAME "altfs")

target_compile_definitions(libaltfs 
    PRIVATE
        FUSE_USE_VERSION=26
)

# Interal libraries

# iosched
add_library(iosched-fcfs MODULE
    iosched/fcfs.c
)

add_library(iosched-unified MODULE
    iosched/cache_manager.c
    iosched/cache_manager.h
    iosched/unified.c
)

# kmi
add_library(kmi-simple MODULE
    kmi/simple.c 
    kmi/key_format_ltfs.c
    kmi/key_format_ltfs.h
)

add_library(kmi-flatfile MODULE
    kmi/flatfile.c
    kmi/key_format_ltfs.c
    kmi/key_format_ltfs.h
)

# tape
add_library(tape-file MODULE
    tape_drivers/generic/file/filedebug_conf_tc.c
    tape_drivers/generic/file/filedebug_conf_tc.h
    tape_drivers/generic/file/filedebug_tc.c
)

add_library(tape-itdtimg MODULE
    tape_drivers/generic/itdtimg/itdtimg_tc.c
)

# Platform-specific library
add_library(tape-sys-specific MODULE)

if(LINUX)
    target_sources(tape-sys-specific
        tape_drivers/linux/sg/sg_scsi_tape.c
        tape_drivers/linux/sg/sg_scsi_tape.h
        tape_drivers/linux/sg/sg_tape.c
        tape_drivers/linux/sg/sg_tape.h
    )

    set_target_properties(tape-sys-specific PROPERTIES OUTPUT_NAME "tape-sg")
elseif(APPLE)
    target_sources(tape-sys-specific
        tape_drivers/osx/iokit/iokit_scsi.c
        tape_drivers/osx/iokit/iokit_scsi.h
        tape_drivers/osx/iokit/iokit_service.c
        tape_drivers/osx/iokit/iokit_service.h
        tape_drivers/osx/iokit/iokit_tape.c
        tape_drivers/osx/iokit/iokit_tape.h
    )

    set_target_properties(tape-sys-specific PROPERTIES OUTPUT_NAME "tape-iokit")
elseif(BSD)
    if(CMAKE_SYSTEM_NAME STREQUAL "FreeBSD")
        target_sources(tape-sys-specific
            tape_drivers/freebsd/cam/cam_cmn.c
            tape_drivers/freebsd/cam/cam_cmn.h
            tape_drivers/freebsd/cam/cam_tc.c
            tape_drivers/freebsd/cam/IBM_tape.h
        )

        set_target_properties(tape-sys-specific PROPERTIES OUTPUT_NAME "tape-cam")
    elseif(CMAKE_SYSTEM_NAME STREQUAL "NetBSD")
        target_sources(tape-sys-specific
            tape_drivers/netbsd/scsipi-ibmtape/scsipi_ibmtape.c
            tape_drivers/netbsd/scsipi-ibmtape/scsipi_ibmtape.h
            tape_drivers/netbsd/scsipi-ibmtape/scsipi_scsi_tape.c
            tape_drivers/netbsd/scsipi-ibmtape/scsipi_scsi_tape.h
        )

        set_target_properties(tape-sys-specific PROPERTIES OUTPUT_NAME "tape-scsipi-ibmtape")
    endif()
endif()

# Exectuables

# altfs
add_executable(altfs
    cmd/altfs/altfs.c
    cmd/altfs/ltfs_fuse.c
    cmd/altfs/ltfs_fuse.h
)

# altfs_ordered_copy - python file, no compilation needed

# altfsck
add_executable(altfsck
    cmd/altfsck/altfsck.c
)

# altfsctl - python file, no compilation needed
include(GNUInstallDirs)

set(sysconfdir "${CMAKE_INSTALL_FULL_SYSCONFDIR}")
set(bindir "${CMAKE_INSTALL_FULL_BINDIR}")

configure_file(
    cmd/altfsctl/altfsctl.in
    "${CMAKE_CURRENT_BINARY_DIR}/altfsctl"
    @ONLY
)

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

install(TARGETS
        altfs
        altfsck
        altfsindextool
        mkaltfs
    RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}"
)

install(FILES
        cmd/altfs_ordered_copy/altfs_ordered_copy
        "${CMAKE_CURRENT_BINARY_DIR}/altfsctl"
    DESTINATION "${CMAKE_INSTALL_BINDIR}"
)

install(TARGETS
        iosched-fcfs
        iosched-unified
        kmi-simple
        kmi-flatfile
        tape-file
        tape-itdtimg
        tape-sys-specific
    LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}/altfs"
)

install(TARGETS libaltfs
    LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    PUBLIC_HEADER DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}/altfs"
)