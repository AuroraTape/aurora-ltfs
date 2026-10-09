<!-- Generated from man/altfsck.8 by man/make-markdown.sh: edit man/sgml/altfsck.sgml instead -->

# altfsck(8)

## NAME

altfsck - Recover and rollback utility for LTFS formatted tape

## SYNOPSIS

**altfsck** \[ **-g** *generation* \] \[ **-r** \] \[ **-n** \] \[ **-f** \] \[ **-z** \] \[ **-l** \] \[ **-m** \] \[ **-v** *strategy* \] \[ **-j** \] \[ **-k** \] \[ **-q** \] \[ **-t** \] \[ **-V** \] \[ **-h** \] \[ **-p** \] *device_name*

On Linux, *device_name* is like '/dev/IBMtape0', on OSX, *device_name* is like '0'(default: )

## DESCRIPTION

**altfsck** is a program to recover an inconsistent LTFS formatted medium and roll back utility of the LTFS.

## OPTIONS

**-g, --generation=** *generation*  
Specify the generation to roll back

**-r, --rollback**  
Roll back to the point specified by -g

**-n, --no-rollback**  
Do not roll back. Verify the point specified by -g (default)

**-f, --full-recovery**  
Recover extra data blocks into directory \_ltfs_lostandfound

**-z, --deep-recovery**  
Recover EOD missing cartridge. Some blocks might be erased, but recover to final unmount point with an index version of at least 2.0.0 or earlier.

**-l, --list-rollback-points**  
List rollback points

**-m, --full-index-info**  
Display full index information (Effective only for -l option)

**-v, --traverse=** *strategy*  
Set traverse mode for listing roll back points. Strategy should be forward or backward. (default: backward)

**-j, --erase-history**  
Erase history at rollback

**-k, --keep-history**  
Keep history at rollback (default)

**-q, --quiet**  
Suppress progress information and general messages

**-t, --trace**  
Enable function call tracing

**--syslogtrace**  
Enable diagnostic output to stderr and syslog

**-V, --version**  
Version information

**-h, --help**  
Show help information

**-p, --advanced-help**  
Full help, including advanced options

## ADVANCED OPTIONS (EXPERIMENTAL)

The options described here is experimental functions.

**-i, --config=** *name*  
Use the specified configuration file (default: )

**-e, --backend=** *name*  
Use the specified tape device backend (default: )

**--kmi-backend=** *name*  
Use the specified key manager interface backend (default: none)

**-x, --fulltrace**  
Enable full function call tracing (slow)

**--capture-index=** *dir*  
Capture indexes read successfully to the specified directory by dir. (-g is effective for this option) File name of each index is \[BARCODE\]-\[GEN\]-\[PARTITION\].xml if tape serial (barcode) is specified at format time. Otherwise it is \[VOL_UUID\]-\[GEN\]-\[PARTITION\].xml.

**--salvage-rollback-points**  
List the rollback points of the cartridge that has no EOD

## SEE ALSO

altfs(8), mkaltfs(8), altfsindextool(8), tape-backend(4), kmi-backend(4), altfs.conf(5).
