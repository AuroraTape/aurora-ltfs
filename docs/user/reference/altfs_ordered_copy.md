<!-- Generated from man/altfs_ordered_copy.1 by man/make-markdown.sh: edit man/sgml/altfs_ordered_copy.sgml instead -->

# altfs_ordered_copy(1)

## NAME

altfs_ordered_copy - Copy files from source to destination with LTFS order optimization

## SYNOPSIS

**altfs_ordered_copy** \[ **-p** \] \[ **-r** \] \[ **-t** *TARGET_DIRECTORY* \] \[ **--keep-tree** *CUTOFF_PREFIX* \] \[ **-a** \] \[ **-v** \] \[ **--verbose** *LOG_LEVEL* \] \[ **-q** \] \[ **-h** \] \[ **SOURCE** * ...* \] \[ **DESTINATION** \]

## DESCRIPTION

**altfs_ordered_copy** is a program to copy files from source to destination with LTFS order optimization. This command tries to acquire file list to copy to DESTINATION when no SOURCE is specified.

## OPTIONS

**-p**  
preserve attributes with shutil.copy2() in Python interpriter

**-r, --recursive**  
copy directories recursively

**-t, --target-directory=** *TARGET_DIRECTORY*  
copy all SOURCE arguments into TARGET_DIRECTORY

**--keep_tree=** *CUTOFF_PREFIX*  
CUTOFF_PREFIX, effective only when file list is provided from stdin and keep-tree option is enabled. CUTOFF_PREFIX is removed from the file paths copied to the destination.

**-a, --all**  
achieve files recursively and preserve attributes

**-v**  
Verbose output. Set VERBOSE level 5

**--verbose=** *LOG_LEVEL*  
Configure verbosity of logger. VERBOSE shall be 0-6. (Default: 4)

**-q, --quiet**  
No message outout

## COMMAND EXAMPLES

This section shows various command examples.

### SIMPLE USAGE

Copy file /foo/aaa to file /foo/bbb

> \$ altfs_ordered_copy /foo/aaa /foo/bbb

Copy file /foo/aaa and /foo/bbb to directory /bar/

> % altfs_ordered_copy /foo/aaa /foo/bbb /bar

Copy directory /foo/ddd and /foo/DDD to directory /bar/

> % altfs_ordered_copy /foo/ddd /foo/DDD /bar

### HOW TO USE WITH FIND COMMAND

Copy all files under /foo/ddd to directory /bar

> \$ find /foo/ddd -type f \| altfs_ordered_copy -t /bar

Copy all directories just under /foo/ddd to directory /bar

> \$ find /foo/ddd -type d -maxdepth 1 \| altfs_ordered_copy -t /bar

Copy all files just under /foo/ddd to directory /bar with keeping tree (Chop /foo/ddd from source list)

> \$ find /foo/ddd -type f \| altfs_ordered_copy -t /bar --keep-tree=/foo/ddd
