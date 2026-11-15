<!-- Generated from man/altfschanger.8 by man/make-markdown.sh: edit man/sgml/altfschanger.sgml instead -->

# altfschanger(8)

## NAME

altfschanger - Drive a tape library's medium changer through a changer plugin

## SYNOPSIS

**altfschanger** \[ **-e** *name* \] \[ **-i** *file* \] **list**

**altfschanger** **-d** *name* \[ **-e** *name* \] \[ **-i** *file* \] \[ **-o** *option* \] \[ **--verbose=** *num* \] *command* \[ *argument ...* \]

## DESCRIPTION

**altfschanger** sends single operations to the medium changer of a tape library through a changer plugin: it reads the element status, moves and exchanges cartridges between element addresses, and makes the changer re-read its elements. It is a tool for testing the changer plugins and for driving a library by hand; it keeps no state between runs.

Elements are named by their address as the changer reports it. The library is shared with its operator panel and with other hosts, and **altfschanger** does not reserve it: check the element status before a move.

## OPTIONS

**-d, --device=** *name*  
The medium changer. Its form depends on the plugin: for the file plugin, a library directory, or the name or serial number of a library directory under the directory that the environment variable **ALTFS_FILE_CHANGER_ROOT** names.

**-e, --backend=** *name*  
Use the specified changer plugin (default: the default changer of the configuration file)

**-i, --config=** *file*  
Use the specified configuration file

**-o** *option*  
Pass an option to the changer plugin; **altfschanger help** lists them

**--verbose=** *num*  
Set the log level: 0 errors, 1 warnings, 2 informational (the default), 3 to 6 debug.

**-h, --help**  
Show the usage

**-V, --version**  
Show the version

## COMMANDS

**list**  
List the medium changers this host can reach

**info**  
Show the identity of the changer, its element address assignment and whether it reads barcodes, reports drive serial numbers and accepts EXCHANGE MEDIUM

**elements \[** *type* ** \[** *start* ** \[** *count* **\]\]\]**  
Show the element status, one element per line: type, address, full or empty, then voltag= (the barcode), source=, dvcid= (the drive serial number) and the flags inaccessible, except=*ASC*/*ASCQ* and impexp. *type* is transport, storage, ie, drive or any (the default).

**move** *source* *dest** * \[***transport** *\]**  
MOVE MEDIUM from one element address to another

**exchange** *source* *dest1** * ***dest2** * \[***transport** *\]**  
EXCHANGE MEDIUM: the cartridge at *source* goes to *dest1* and the one at *dest1* goes to *dest2*, which may be *source*

**scan \[** *start* *count** *\]**  
Make the changer re-read its elements (INITIALIZE ELEMENT STATUS); on a large library this takes minutes

**tur**  
Send TEST UNIT READY

**prevent, allow**  
Lock or unlock the import/export station

**help**  
Show the options of the changer plugin

## EXIT STATUS

0 on success, 8 when the operation failed (the message ACH0004E gives the internal error code), 16 for a usage error.

## SEE ALSO

altfs(8), mkaltfs(8).
