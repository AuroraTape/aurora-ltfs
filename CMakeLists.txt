cmake_minimum_required(VERSION 3.28)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

project(aurora-ltfs
    VERSION 1.5.0
    LANGUAGES C
)

option(ENABLE_TESTS "Build tests" OFF)
option(INSTALL_EXAMPLES "Install examples" ON)
option(INSTALL_DOCS "Install documentation files" ON)

add_subdirectory(src)

if(ENABLE_TESTS)
    add_subdirectory(tests)
endif()

# Find libraries
find_package(PkgConfig)

pkg_check_modules(LIBFUSE REQUIRED IMPORTED_TARGET GLOBAL fuse)
pkg_check_modules(LIBXML2 REQUIRED IMPORTED_TARGET GLOBAL libxml-2.0)
# pkg_check_modules(LIBICUIO REQUIRED IMPORTED_TARGET GLOBAL icu-io) # Which ICU?
pkg_check_modules(LIBUUID REQUIRED IMPORTED_TARGET GLOBAL uuid)

# Misc installs

include(GNUInstallDirs)

# Configuration files
add_subdirectory(conf)

# Manual pages
add_subdirectory(man)

# Examples
if(INSTALL_EXAMPLES)
    add_subdirectory(examples)
endif()

# Documentation
if(INSTALL_DOCS)
    add_subdirectory(docs)
endif()