<!-- Generated from man/altfsindextool.8 by man/make-markdown.sh: edit man/sgml/altfsindextool.sgml instead -->

# altfsindextool(8)

## NAME

altfsindextool - Low level index checking tool for LTFS

## SYNOPSIS

**altfsindextool** \[ **-d** *name* \] \[ **-p** *part_num* \] \[ **-s** *block* \] \[ **-b** *num* \] \[ **-i** *file* \] \[ **-e** *name* \] \[ **-q** \] \[ **--verbose=** *num* \] \[ **-V** \] \[ **-h** \] \[ **-p** \] \[ *filename* \]

## DESCRIPTION

**altfsindextool** is a low level index checking tool.

There are 2 features. One is captureing indexes on a tape, the other is checking captured index from a file. The command runs as index checking mode when filename is specified. It runs as index capturing mode when -d option is specified. It runs as index checking mode when both filename and -d option are specified. -p, -s --output-dir, -b is available only when it runs under index captureing mode. They would be ignored when it runs under index checking mode.

## OPTIONS

**-d, --device=** *name*  
Tape device name to capture indexes. On Linux, *name* is like '/dev/IBMtape0', on OSX, *name* is like '0'.

**-p, --partition=** *part_num*  
Partition to capture indexes. Shall be 0 or 1. Capture indexes on both partitions

**-s, --start-pos=** *block*  
Block number to start capturing indexes

**--output-dir=** *dir*  
Directory to store captured indexes

**-b, --blocksize=** *num*  
Specify the LTFS record size, i.e. the read size for one block. Without this option the default (524288) is lowered to what the drive and the host transfer path support; a larger value given with this option is refused. Blocks larger than that limit cannot be read on this host

**-i, --config=** *name*  
Use the specified configuration file

**-e, --backend=** *name*  
Use the specified tape device backend

**--kmi-backend=** *name*  
Use the specified key manager interface backend (default: none)

**-q, --quiet**  
Suppress progress information and general messages

**--verbose=** *num*  
Set the log level: 0 errors, 1 warnings, 2 informational (the default), 3 to 6 debug. A number below 100 sets the level of the standard error output; syslog gets the same messages, up to informational ones. *syslog level* \* 100 + *stderr level* sets the two separately: --verbose=303 sends the debug messages to both.

**-V, --version**  
Version information

**-h, --help**  
Show help information

### USAGE EXAMPLE

              altfsindextool -d /dev/sg10
              altfsindextool -d /dev/sg10 -p 1 --output-dir=/foo
              altfsindextool -d ltfs-index-1-35.xml
            

## SEE ALSO

altfs(8), mkaltfs(8), altfsck(8).
