<!-- Generated from man/altfsctl.8 by man/make-markdown.sh: edit man/sgml/altfsctl.sgml instead -->

# altfsctl(8)

## NAME

altfsctl - Set up LTFS mounts as system services

## SYNOPSIS

**altfsctl** **check** \[ **--device** *DEVICE* \] \[ **--fix-fuse-conf** \] \[ *SERIAL* \]

**altfsctl** **add** \[ **--device** *DEVICE* \] \[ **--gid** *GROUP* \] \[ **--umask** *MASK* \] \[ **--no-wait-medium** \] \[ **-o** *OPTION ...* \] \[ **--fix-fuse-conf** \] \[ **--enable** \] \[ **--force** \] *SERIAL* *MOUNTPOINT*

**altfsctl** { **remove** \| **enable** \| **disable** } *SERIAL*

**altfsctl** **list**

## DESCRIPTION

**altfsctl** sets up the mount of a tape drive as a system service: an instance *altfs@SERIAL.service* of the unit template *altfs@.service*, named after the serial number of the drive (see **altfs -o device_list**), which does not change across reboots unlike */dev/sgN*.

A mount started from a login shell belongs to the login session, and systemd stops a session with a short timeout at shutdown, which can kill **altfs** before the index has reached the tape. A service instance has its own stop timeout that leaves time for the index write. It also runs **altfs** as the unprivileged user altfs instead of root.

**altfsctl** checks the environment the service needs, writes the settings of each instance and enables or disables it. Starting and stopping an instance stay with **systemctl**. Linux with systemd only. Except for **check** and **list**, run it as root.

## COMMANDS

**check \[** *SERIAL* **\]**  
Checks that user_allow_other is set in */etc/fuse.conf*, that the user altfs and the group tape exist and that **altfs** is installed. With *SERIAL*, also that the drive is listed by **altfs -o device_list** and that its device node is readable and writable by the group tape. Each item is reported as OK or FAIL with what to do; the exit status is 1 when an item fails. Run it as root to find the drive.

**add** *SERIAL* *MOUNTPOINT*  
Runs the checks of **check** and stops without changing anything when one fails. Otherwise creates *MOUNTPOINT* (an absolute path; an existing directory has to be empty and belong to the user altfs already), gives it to that user and writes the settings of the instance. The instance waits for the drive and for a cartridge when they are not ready (**-o wait_medium** of **altfs**) unless **--no-wait-medium** is given.

**remove** *SERIAL*  
Disables the instance and removes its settings. A running instance is refused: stop it with **systemctl stop** first. The mount point is left in place.

**enable** *SERIAL* **, disable** *SERIAL*  
Starts the instance at boot, or no longer does. A running instance keeps running.

**list**  
Lists the instances that are set up, whether they are enabled and active, and their mount points.

## OPTIONS

**--device** *DEVICE*  
The device the instance opens (**-o devname=** of **altfs**), instead of looking the drive up by *SERIAL*.

**--gid** *GROUP*  
Group, by name or number, shown as the owner of the files and directories on the volume. LTFS does not record owners or permissions; without this option they belong to the user and group altfs.

**--umask** *MASK*  
Permission bits, in octal, removed from all files and directories. Without it they are 0777, which lets every local user read and write the volume. **--gid tapeusers --umask 007** limits access to the members of tapeusers.

**--no-wait-medium**  
The instance fails when the drive cannot be opened or is empty instead of waiting.

**-o, --option** *OPTION*  
A further option for **altfs**, without **-o**, for example **-o sync_type=time@10** or **-o eject**. Repeatable.

**--fix-fuse-conf**  
Adds user_allow_other to */etc/fuse.conf* when it is missing, once all other checks have passed. The instance mounts with **-o allow_other** so that users other than altfs can see the volume, and **fusermount** refuses that option for users other than root unless this line is present. The line lets every local user create FUSE mounts with **allow_other**, which is why **altfsctl** does not add it unless asked.

**--enable**  
Also starts the instance at boot.

**--force**  
Replaces the settings of an instance that is already set up.

## THE SERVICE

An instance runs **altfs -f** as the user altfs with the supplementary group tape and the capability CAP_SYS_RAWIO; without that capability the Linux sg driver rejects most tape commands even for members of the group. Its work directory is */var/lib/altfs/SERIAL*.

It counts as started as soon as **altfs** runs, so an empty drive does not hold up the boot; whether the volume is mounted shows in **systemctl status** and in the log. **systemctl stop** sends SIGTERM, on which **altfs** writes the index and unmounts, or stops waiting for a cartridge; the instance gets up to 11 minutes for that. At shutdown the instances stop before *altfs.service*, which unmounts the volumes mounted in other ways.

The messages of **altfs** go to syslog: to the journal, and to */var/log/altfs.log* where the rsyslog rule of the package is in place. The standard error output, which also lands in the journal, gets the errors only (**-o verbose=200**); add **-o verbose=300** to the options of an instance for debug messages.

To start an instance again after it ends, for example to wait for the next cartridge after the volume has been unmounted, add Restart=always with **systemctl edit altfs@** *SERIAL* **.service**.

## FILES

*/etc/altfs/SERIAL.conf*  
Settings of an instance, read by the unit: MOUNTPOINT=, OPTIONS= (further **altfs** options) and, with **--device**, DEVICE=.

*/usr/lib/systemd/system/altfs@.service*  
The unit template.

*/usr/lib/sysusers.d/altfs.conf*  
Creates the user and group altfs when the package is installed: ID 5432 when it is free, otherwise a free system ID.

## COMMAND EXAMPLES

Check the environment and the drive 10WT019481:

> \# altfsctl check 10WT019481

Mount it on /mnt/ltfs at boot, readable and writable for the group tapeusers only, and start it now:

> \# altfsctl add --gid tapeusers --umask 007 --enable 10WT019481 /mnt/ltfs

> \# systemctl start altfs@10WT019481.service

Unmount and stop, then remove the setup:

> \# systemctl stop altfs@10WT019481.service

> \# altfsctl remove 10WT019481

## SEE ALSO

altfs(8), systemctl(1), sysusers.d(5)
