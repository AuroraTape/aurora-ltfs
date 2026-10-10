<!-- Generated from man/mkaltfs.8 by man/make-markdown.sh: edit man/sgml/mkaltfs.sgml instead -->

# mkaltfs(8)

## NAME

mkaltfs - Format a tape in the drive to LTFS format

## SYNOPSIS

**mkaltfs** **-d** *name* \[ **-f** \] \[ **-s** *id* \] \[ **-n** *name* \] \[ **-r** *rules* \] \[ **-w** \] \[ **-q** \] \[ **--verbose=** *num* \] \[ **-V** \] \[ **-h** \] \[ **-p** \]

## DESCRIPTION

**mkaltfs** is a program to format a media for use with the LTFS.

## OPTIONS

**-d, --device=** *name*  
Tape device name (required). On Linux, *name* is like '/dev/IBMtape0', on OSX, *name* is like '0'

**-f, --force**  
Force to format medium

**-s, --tape-serial=** *id*  
Tape serial number (6 alphanumeric ASCII characters)

**-n, --volume-name=** *name*  
Tape volume name (empty by default)

**-r, --rules=** *rules*  
Rules for choosing files to write to the index partition. The syntax of the rule argument is:

size=1M

size=1M/name=pattern

size=1M/name=pattern1:pattern2:pattern3

A file is written to the index partition if it is no larger than the given size AND matches at least one of the name patterns (if specified). The size argument accepts K, M, and G suffixes. Name patterns might contain the special characters '?' (match any single character) and '\*' (match zero or more characters).

**--no-override**  
Disallow mount-time data placement policy changes

**-w, --wipe**  
Restore the LTFS medium to an unpartitioned medium (format to a legacy scratch medium)

**-q, --quiet**  
Suppress progress information and general messages

**--verbose=** *num*  
Set the log level: 0 errors, 1 warnings, 2 informational (the default), 3 to 6 debug. A number below 100 sets the level of the standard error output; syslog gets the same messages, up to informational ones. *syslog level* \* 100 + *stderr level* sets the two separately: --verbose=303 sends the debug messages to both.

**-V, --version**  
Version information

**-h, --help**  
Show help information

**-p, --advanced-help**  
Full help, including advanced options

### USAGE EXAMPLE

              mkaltfs --device=/dev/sg0 --rules="size=100K"
              mkaltfs --device=/dev/sg0 --rules="size=1M/name=*.jpg"
              mkaltfs --device=/dev/sg0 --rules="size=1M/name=*.jpg:*.png"
            

## ADVANCED OPTIONS (EXPERIMENTAL)

The options described here is experimental functions.

**-i, --config=** *name*  
Use the specified configuration file (default: )

**-e, --backend=** *name*  
Use the specified tape device backend (default: )

**--kmi-backend=** *name*  
Use the specified key manager interface backend (default: none)

**-b, --blocksize=** *num*  
Set the LTFS record size (default: 524288). Every block is transferred to the drive with one command, so the record size cannot exceed what the drive and the host transfer path support; an HBA behind a Thunderbolt or USB4 port, for example, is typically limited to 262144 bytes. Without this option a lower limit lowers the default to the largest power of two within the limit; a larger value given with this option is refused, because the volume could not be read back on this host

**-c, --no-compression**  
Disable compression on the volume

**-k, --keep-capacity**  
Keep the tape medium's total capacity proportion

**--long-wipe**  
Unformat the medium and erase any data on the tape by overwriting special data pattern. This operation takes over 3 hours. Once you start, you cannot interrupt it.

**--destructive**  
Use destructive format/unformat. This operation takes longer time in the LTO9 drive or later because of the media optimization procedure.

## SEE ALSO

altfs(8), altfsck(8).
