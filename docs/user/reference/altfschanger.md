<!-- Generated from man/altfschanger.8 by man/make-markdown.sh: edit man/sgml/altfschanger.sgml instead -->

# altfschanger(8)

## NAME

altfschanger - Drive a tape library's medium changer through a changer plugin

## SYNOPSIS

**altfschanger** \[ **-e** *name* \] \[ **-i** *file* \] **list**

**altfschanger** **-d** *name* \[ **-e** *name* \] \[ **-i** *file* \] \[ **-o** *option* \] \[ **--verbose=** *num* \] \[ **--ready-wait=** *seconds* \] \[ **--move-wait=** *seconds* \] *command* \[ *argument ...* \]

## DESCRIPTION

**altfschanger** sends single operations to the medium changer of a tape library. It is a tool for testing the changer plugins and the changer layer and for driving a library by hand; it keeps no state between runs.

The plugin commands go straight to the changer plugin and name elements by their address as the changer reports it: they read the element status, move and exchange cartridges, and make the changer re-read its elements. They check nothing.

The cartridge commands go through the changer layer and name cartridges by barcode and drives by serial number (by element address on a changer that does not report drive serial numbers). Each one reads the whole library first, reads the elements a move touches right before the move, and prints the inventory when it succeeds. The library is shared with its operator panel and with other hosts and is not reserved; the layer re-reads what a unit attention says has changed and does not repeat a move whose outcome is unknown.

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

**--ready-wait=** *seconds*  
How long a cartridge command waits for a changer that is not ready (door open) before it fails (default: 30)

**--move-wait=** *seconds*  
How long a cartridge may be in neither element of a move (on the picker) before the layer re-reads the library (default: 5)

**-h, --help**  
Show the usage

**-V, --version**  
Show the version

## PLUGIN COMMANDS

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

## CARTRIDGE COMMANDS

**inventory**  
Show the library (library line: identity, ready, stale, counts, last unit attention), its drives (drive lines: serial, address, what it holds) and its cartridges (tape lines: barcode, where, address, state, home slot). Cartridges without a readable barcode are listed as unlabeled*n* in address order.

**rescan \[deep\]**  
Read every element again; deep makes the changer re-read its elements first

**load** *barcode* *drive*  
Move the cartridge into the drive. A duplicate barcode, a cleaning cartridge (CLN) and a cartridge in the import/export station are refused.

**return** *drive*  
Move the cartridge in the drive back to the slot it came from, or to a free slot when that one is taken

**swap** *barcode* *drive*  
Return the cartridge in the drive and load the other one, with EXCHANGE MEDIUM when the changer accepts it and two moves otherwise

**export** *barcode*  
Move the cartridge to a free import/export element

**import** *barcode*  
Move the cartridge from the import/export station to a free storage slot

The cartridge commands only move cartridges: they do not load the tape in the drive, mount it or unload it.

## EXIT STATUS

0 on success, 8 when the operation failed (the message ACH0004E gives the internal error code), 16 for a usage error.

## SEE ALSO

altfs(8), mkaltfs(8).
