# Path failover and revalidation

A mounted volume assumes that the drive it opened is still the drive it talks
to, and that the cartridge in it is still the cartridge whose index it holds
in memory. Two things break that assumption while a volume is mounted: the
path to the drive goes away (a cable, a switch, an HBA reset, a drive power
cycle), or the drive reports that the cartridge may have been touched by
someone else (a unit attention, a lost reservation). libaltfs answers the
first with *path failover* in the tape backend and the second with
*revalidation* of the medium in the library. This document describes both,
where they live in the code, and what the user sees.

The code is in `src/libltfs/tape.c` and `src/libltfs/tape.h` (the error
classes, the device lock and its fence), `src/libltfs/ltfs.c`
(`ltfs_revalidate()` and the locking wrappers that call it),
`src/libltfs/ltfs_fsops_raw.c` (the read and write paths) and, for failover,
`src/tape_drivers/linux/sg/sg_tape.c` and
`src/tape_drivers/netbsd/scsipi-ibmtape/scsipi_ibmtape.c`.

## The errors that start it

A tape backend returns negative `EDEV_*` codes from `src/libltfs/ltfs_error.h`.
The SCSI sense data is decoded into them by the table in
`src/tape_drivers/vendor_compat.c` (sense key, ASC and ASCQ; for example
`06/2900` "Power On, Reset, or Bus Device Reset Occurred" becomes
`EDEV_POR_OR_BUS_RESET`). Two macros in `tape.h` sort these codes into the
classes that matter here:

| Macro | Codes | Meaning |
|:--|:--|:--|
| `NEED_REVAL(ret)` | `EDEV_POR_OR_BUS_RESET` (06/29xx), `EDEV_MEDIUM_MAY_BE_CHANGED` (06/2800), `EDEV_RESERVATION_PREEMPTED` (06/2A03), `EDEV_REGISTRATION_PREEMPTED` (06/2A05), `EDEV_REAL_POWER_ON_RESET`, `EDEV_NEED_FAILOVER` | The drive, or the cartridge in it, may not be in the state libaltfs remembers. The medium has to be revalidated before anything else touches it. |
| `IS_UNEXPECTED_MOVE(ret)` | `EDEV_MEDIUM_REMOVAL_REQ` (06/5A01) | The operator pressed the eject button. The cartridge is about to leave; the volume is given up without a revalidation attempt. |

The last two codes of the first row are not sense data. `EDEV_NEED_FAILOVER`
and `EDEV_REAL_POWER_ON_RESET` are produced by the backend itself at the end
of a reconnect, as described next. `EDEV_CONNECTION_LOST` and
`EDEV_NO_CONNECTION` are the codes of the lost path; they never reach the
library as such, the backend turns them into one of the above or into a plain
error.

## Path failover

Failover is a backend matter. The `sg` backend (Linux) and the
`scsipi-ibmtape` backend (NetBSD) implement it; the two are the same code.
The `iokit` (macOS) and `cam` (FreeBSD) backends log the error and take a
drive dump when one is due, but do not reconnect; the `file` and `itdtimg`
backends have no path to lose.

### Detecting the lost path

`sg_issue_cdb_command()` in `sg_scsi_tape.c` maps the outcome of the `SG_IO`
ioctl: `ENODEV` from the ioctl, and the host status codes `HOST_NO_CONNECT`,
`HOST_BAD_TARGET`, `HOST_RESET`, `HOST_TRANS_DISR`, `HOST_TRANS_FAIL` and
`HOST_TARGET_FAIL`, all become `EDEV_CONNECTION_LOST`. A command issued on a
file descriptor that is already closed returns `EDEV_NO_CONNECTION`.

Every SCSI command in `sg_tape.c` passes its error through
`_process_errors()`. On `EDEV_CONNECTION_LOST`, and only if a reconnect is
not already running (`priv->is_reconnecting`), it logs `ATG0047I`
("Connection down is detected, try to reconnect") and calls
`_reconnect_device()`. The result of the reconnect, when it is an error,
replaces the error of the command.

### Reconnecting

`_reconnect_device()` closes the dead file descriptor and looks for the same
drive again by **serial number**: it lists the `sg` devices
(`sg_get_device_list()`), keeps those whose serial matches
(`_create_open_order()`), and sorts them by how many drives are already open
through the same host and channel (`get_openfactor()`), so that a second path
is preferred over the one that just failed when both are present. The
candidates are opened in that order until one succeeds. With no candidate it
returns `EDEV_NO_CONNECTION` (`ATG0048I`), and the command fails for good.

On the reopened descriptor the backend first wants a stable answer from the
drive: `_get_stable_tur_response()` issues TEST UNIT READY until three
answers in a row agree, discarding unit attentions on the way. The answer
decides how the session is restored:

- **Reservation conflict**: the drive is reserved, by another path of this
  node or by another host. The backend registers its key again and takes the
  reservation over with PERSISTENT RESERVE OUT, PREEMPT AND ABORT, using its
  own key as both the reservation key and the key to preempt (`ATG0070I`,
  `ATG0073I`). Result: `EDEV_NEED_FAILOVER`.
- **No reservation holder** (PERSISTENT RESERVE IN shows none): the drive
  lost its reservations, which only a power cycle does. The backend registers
  and reserves again (`ATG0071I`, "A power-on-reset happened"). Result:
  `EDEV_REAL_POWER_ON_RESET`.
- **Reservation held and not conflicting**: it is our own, the same path came
  back (`ATG0072I`). Result: `EDEV_NEED_FAILOVER`.

Two more outcomes end the command without a revalidation: when every
candidate fails to open (`ATG0011I`), the open error is returned, and when
the reservation cannot be restored (the PERSISTENT RESERVE OUT itself fails),
its error is returned; neither is in `NEED_REVAL`, so the command simply
fails.

Both revalidation results are in `NEED_REVAL`, so the library will revalidate the medium.
The difference is only in what the backend has learned: after a real power-on
reset the drive has lost everything (position, mode pages, the reservation),
after a path switch it may have kept its position.

### What happens to the command that was running

The command whose error started the reconnect is not re-issued by the
backend, with one exception. WRITE and WRITE FILEMARKS (`sg_write()`,
`sg_writefm()`) cannot be blindly repeated, a repeated write would duplicate
a block, so on `EDEV_NEED_FAILOVER` they read the position back: if the
drive sits exactly one block (or one filemark group) past where the command
started, the command took effect and the function returns success; if not,
it returns `EDEV_POR_OR_BUS_RESET`, and the revalidation that follows finds
out where the drive really is. Every other command returns the failover code
to the library, which revalidates and then repeats the whole operation from
the start, as the next section describes.

There is no retry counter around a reconnect. A path that fails again during
the revalidation goes through the same sequence once more. A reconnect that
finds no candidate at all is final, though: `_reconnect_device()` has
already closed the descriptor, every later command fails at once with
`EDEV_NO_CONNECTION` (`sg_issue_cdb_command()` checks the descriptor
first), and `_process_errors()` does not reconnect on that code. The volume
has to be unmounted and mounted again.

## Revalidation

Revalidation is the library's check that the cartridge in the drive is still
the volume it has in memory, and that the tape stands where libaltfs thinks
it does. It is in `ltfs_revalidate()`; the state that drives it is in
`struct ltfs_volume`:

```c
ltfs_thread_mutex_t reval_lock;
ltfs_thread_cond_t  reval_cond;
int reval;      /* 0, -LTFS_REVAL_RUNNING or -LTFS_REVAL_FAILED */
```

and in `struct device_data`, the `fence` flag that `tape_start_fence()` sets
and `tape_release_fence()` clears.

### Who notices

Every library entry point that talks to the drive is a locking wrapper of the
same shape, and the shape is the mechanism. There are two kinds. The outer
wrappers take the volume lock and revalidate themselves: in `ltfs.c`
`ltfs_test_unit_ready()`, `ltfs_capacity_data()`, `ltfs_sync_index()` and
`ltfs_unmount()`; in `ltfs_fsops_raw.c` `ltfs_fsraw_read()`,
`ltfs_fsraw_write()` and `ltfs_fsraw_write_data()`; in `ltfs_fsops.c`
`ltfs_fsops_setxattr()` and, for the virtual `ltfs.*` attributes that are
read from the drive, the getxattr path of `xattr.c`, which calls
`ltfs_revalidate()` and returns `-LTFS_RESTART_OPERATION` so that its caller
starts over. The inner helpers only take the device lock and, on a
`NEED_REVAL` error, raise the fence and return the code to the outer wrapper
that revalidates: `ltfs_get_cartridge_health()`, `ltfs_get_tape_alert()`,
`ltfs_clear_tape_alert()`, `ltfs_get_params_unlocked()`,
`ltfs_capacity_data_unlocked()` and the vendor-unique xattr accessors.
Simplified, the outer shape is:

```c
start:
	ret = ltfs_get_volume_lock(false, vol);      /* waits while reval is RUNNING,
	                                                fails when it is FAILED */
	if (ret < 0)
		return ret;
	ret = tape_device_lock(vol->device);
	if (ret == -LTFS_DEVICE_FENCED) {            /* somebody else is revalidating */
		ret = ltfs_wait_revalidation(vol);
		if (ret == 0)
			goto start;
		return ret;
	}
	ret = <the tape operation>;
	if (NEED_REVAL(ret)) {
		tape_start_fence(vol->device);           /* nobody else takes the device */
		tape_device_unlock(vol->device);
		ret = ltfs_revalidate(false, vol);
		if (ret == 0)
			goto start;                          /* the operation is repeated */
	} else if (IS_UNEXPECTED_MOVE(ret)) {
		vol->reval = -LTFS_REVAL_FAILED;         /* eject requested: give up */
		...
	}
```

The thread that sees a `NEED_REVAL` error becomes the revalidating thread.
It raises the fence first, while still holding the device lock, so that from
that moment `tape_device_lock()` returns `-LTFS_DEVICE_FENCED` to every other
thread instead of handing out the device; those threads park in
`ltfs_wait_revalidation()` on `reval_cond`. Threads that have not reached
the device yet park in `ltfs_get_volume_lock()`, which does not return while
`reval` is `-LTFS_REVAL_RUNNING`. The read and write paths of the I/O
scheduler end in `ltfs_fsraw_read()` and `ltfs_fsraw_write()`, so FUSE
requests queue up there.

Inside `tape.c` a few operations handle `NEED_REVAL` themselves, by
repeating the backend call in a `do { } while (NEED_REVAL(ret))` loop
without revalidating: `tape_reserve_device()`, `tape_release_device()`,
`tape_prevent_medium_removal()`, `tape_allow_medium_removal()`, the LOAD in
`tape_load_tape()` and the REWIND in `tape_unload_tape()`. These are the
operations revalidation itself needs, or that run before a volume exists.
The loops have no bound; they rely on the unit attention being reported
once.

```
                 NEED_REVAL error seen
                 by thread T
   +----------+  ------------------>  +-------------------+
   | reval=0  |                       | reval=RUNNING     |
   | fence=0  |  <------------------  | fence=1           |
   +----------+   revalidation OK:    | T: ltfs_revalidate|
        ^         fence=0, reval=0,   | others: wait      |
        |         T repeats its op    +---------+---------+
        |                                       | failed
        | a revalidation that fails             v
        | during the unmount's own    +-------------------+
        | index write resets reval    | reval=FAILED      |
        | to 0 instead (see below)    | fence=0           |
        +-----------------------------| every op fails,   |
                                      | unmount only      |
                                      +-------------------+
   IS_UNEXPECTED_MOVE goes straight to FAILED. FAILED is left only by
   unmounting, which frees the volume.
```

### What ltfs_revalidate() checks

`ltfs_revalidate(have_write_lock, vol)` sets `reval` to `-LTFS_REVAL_RUNNING`,
takes the write lock on the volume (upgrading from the read lock most callers
hold) and saves the append positions of both partitions. Then, against the
drive:

1. `ltfs_setup_device()`: waits for the cartridge to be loadable and sets the
   mode pages again. After a real power-on reset the drive has defaults.
2. Clears `device_reserved` and `medium_locked` and calls
   `tape_reserve_device()`: the reservation is taken again whatever the
   backend did during the reconnect.
3. `ltfs_start_mount(false, vol)` with a fresh label structure: loads the
   tape, reads the labels of both partitions. The new label is compared with
   the one in memory by `label_compare()` in `src/libltfs/label.c` (barcode,
   volume UUID, format time, block size, compression flag, partition
   identifiers). A different cartridge fails here.
4. `ltfs_check_eod_status()`: both partitions still have an EOD.
5. `_ltfs_revalidate_mam()`: the MAM coherency attributes of both partitions
   (volume change reference, index generation `count`, `set_id`, UUID,
   version) are read and compared field by field with the `ip_coh` and
   `dp_coh` that libaltfs wrote or read last. Anyone who wrote an index on
   this cartridge in the meantime changed them.
6. Data partition: seek to EOD and check that the position equals the saved
   append position, when there is one. If the partition ends in an index,
   space back over the filemarks and check that the block before EOD is the
   filemark and that the block the index starts at is the one the in-memory
   index points to (its own position if it is on the DP, its back pointer
   otherwise). A write that completed on the tape but not in libaltfs'
   bookkeeping, or the reverse, fails here.
7. Index partition: seek to EOD and compare with the saved append position
   as well, except that the IP always ends in an index, so the position
   compared is the one just before the EOD block (`pos.block - 1`) and only
   the index's self pointer is checked, not a back pointer.

The saved append positions are put back on both partitions, so the next
write appends where it would have appended before the interruption. On
success `reval` becomes 0, the fence is lowered, all waiting threads wake
up, and the caller repeats its operation (`ALB0158I`). On failure `reval`
becomes `-LTFS_REVAL_FAILED` (`ALB0144E`, "Medium revalidation failed.
Unmount the tape before continuing"). The label that was read is freed; the
volume keeps its old label and index in every case.

Note that the check is against what libaltfs itself wrote last: it is a test
that nothing happened to the cartridge, not a re-read of its content. A
cartridge that was unloaded and loaded again untouched passes; a cartridge
on which another host appended one block fails.

### The failed state

After a failed revalidation every operation that reaches
`ltfs_get_volume_lock()` returns `-LTFS_REVAL_FAILED`, which
`src/libltfs/arch/errormap.c` maps to `EFAULT` (`AEI1068E`). The state is
not cleared by a later retry: the only way out is to unmount.

`ltfs_unmount()` is itself such an operation. It takes the volume lock, and
when `reval` is `-LTFS_REVAL_FAILED` the lock request fails and the function
returns without writing an index. `ltfs_fuse_umount()`, the FUSE `destroy`
handler in `src/cmd/altfs/ltfs_fuse.c`, ignores that return value, so the
FUSE unmount completes; `altfs` then ejects the cartridge if asked to, and
closes the device (`ltfs_device_close()`, which releases the reservation)
after `fuse_main()` returns in `altfs.c`. The index on the tape stays
the one written at the last sync. The data written since is on the tape but
not in any index until `altfsck` recovers it. That is what "unmount the tape
before continuing" in the message means.

Two cases end differently:

- A `NEED_REVAL` error during the index write of the unmount itself:
  `ltfs_unmount()` revalidates and tries the index write once more. If that
  revalidation fails, `reval` is reset to 0 ("to allow future mount
  attempts") and the unmount returns the error.
- `IS_UNEXPECTED_MOVE`, the operator's eject request: `reval` is set to
  `-LTFS_REVAL_FAILED` on the spot, without revalidating.

## Reservations and the medium lock

Both are the protection against the situation revalidation detects, and
revalidation restores both.

**Reservation.** `tape_device_open()` reserves the drive right after the
backend open, with up to three attempts a second apart (`ALP0021E` when all
fail), and `tape_device_close()` releases it. The `sg`, `scsipi-ibmtape`
and `iokit` backends use PERSISTENT RESERVE OUT with an exclusive-access
reservation and a key generated per node (`ibm_tape_genkey()`), registered
at open (`_register_key()`) and unregistered at close. `sg_reserve()` retries
once after registering again when the reservation or registration was
preempted or a conflict is reported (`ATG0069I`); a conflict that stays is
reported with the holder's identity (`ATG0067W`, `ATG0068W`). The `cam`
backend relies on the FreeBSD `sa(4)` driver, which issues RESERVE and
RELEASE itself at open and close; its `reserve_unit` and `release_unit` are
empty. The `file` backend keeps a flag and refuses a second reservation.

`sg_open()` also uses the reservation to choose among several paths to the
same serial number: a path whose drive is unreserved is taken; one reserved
with this node's own key is tried, because a previous session on this node
may have left it (`ATG0092I` when it succeeds, `ATG0093I` when another
instance holds it); one reserved by another key is skipped with the holder
in the log (`ATG0094I`). A serial number that no `sg` device carries gives
`EDEV_DEVICE_UNOPENABLE`, on which `altfs -o wait_medium` waits for the
drive to appear. `altfs -o release_device` clears a reservation left behind by a
crashed session: it opens the device, unloads the cartridge if one is
loaded, releases and closes, and exits.

**Medium lock.** `tape_load_tape()` issues PREVENT ALLOW MEDIUM REMOVAL
(prevent) once the cartridge is ready, and `tape_unload_tape()` allows
removal before the rewind. `tape_device_open()` issues an allow at open
regardless of state, to clear a lock left by a crashed session.
`EDEV_MEDIUM_REMOVAL_REQ` is the drive telling us that the operator pressed
eject while the lock was on; the cartridge stays in, but libaltfs gives the
volume up as described above.

## What the user sees

| Situation | Log | Result of the operation |
|:--|:--|:--|
| Path lost, another path or the same one comes back, cartridge untouched | `ATG0047I`, `ATG0050I`, `ATG0070I`/`ATG0072I`, `ATG0073I`, then `ALB0143I` and `ALB0158I` | The request completes after a pause; nothing to do |
| Drive power cycled, cartridge still in | `ATG0071I`, `ALB0143I`, `ALB0158I` | Same |
| Unit attention from the drive (reset, medium may have changed) | `ALB0143I`, `ALB0158I` | Same |
| Path lost and no other path to the drive | `ATG0047I`, `ATG0048I` | `EIO` (`AED0403E`) for this and every later request: the descriptor is closed and no further reconnect is attempted. Unmount and mount again |
| Cartridge changed, written by another host, or the drive's position does not match | `ALB0143I`, `ALB0144E` | `EFAULT` for this and every later request until unmount; the index is not written at unmount |
| Operator pressed eject | `AED0606E` in the log of the failing command | Same as above, without the revalidation messages |
| A request arrives while a revalidation runs | — | It waits, then runs normally (or fails with the revalidation) |

The errno values come from `errormap.c`: `LTFS_DEVICE_FENCED` and
`LTFS_REVAL_RUNNING` map to `EAGAIN`, but in practice neither reaches FUSE,
because the wrappers wait instead of returning them; `LTFS_REVAL_FAILED` maps
to `EFAULT`; `EDEV_NEED_FAILOVER`, `EDEV_REAL_POWER_ON_RESET` and the unit
attention codes map to `EIO`, and reach FUSE only from a place that does not
revalidate.

## What is tested

The automated suites run on the `file` backend, which cannot report a unit
attention, lose a path or hold a real reservation, so the revalidation and
failover paths themselves are not exercised by `tests/scenarios` or
`tests/fsapi`. `tests/scenarios/test_volume_lifecycle.py` covers the
neighbouring case that can be tested there, a cartridge rewritten out of band
(`altfsck --rollback`) while no daemon runs, where the next mount must read
the new state.

Everything in this document that involves the drive is real-drive only:
pulling a cable or power cycling the drive during a copy (the sg reconnect,
both outcomes), a second host appending to the cartridge between two
operations (revalidation failure), and the eject button while mounted.
`tests/realdrive/` has no script for these; they are checked by hand.

## Open points in the code

These are observations from reading the code, recorded here so that the next
change in this area starts from them.

- `sg_writefm()` checks `pos->block + count == cur_pos.block` after a failover
  but then advances `pos->block` by one, not by `count`. libaltfs writes one
  filemark at a time, so the difference does not show today.
- The `do { } while (NEED_REVAL(ret))` loops in `tape.c` have no bound. A
  backend that returned `EDEV_NEED_FAILOVER` on every call would spin.
- In `sg_open()`, when every path to the serial number is reserved by another
  key, the search loop ends with `ret` at 0 (the last PERSISTENT RESERVE IN
  succeeded) and no open descriptor. The open then fails on the
  `SG_GET_RESERVED_SIZE` ioctl (`ATG0085I`) with the ioctl's -1 instead of a
  device error code that says the drive is in use.
- `ltfs_set_vendorunique_xattr()` returns `LTFS_NO_DEVICE` as a positive
  value when the volume has no device, unlike every other error path.
- `ltfs_release_medium()` ignores the result of `tape_unload_tape()` and
  always returns 0, so `altfs -o release_device` reports success even when the
  unload failed; the release itself is done by the device close that follows.
- Only the `sg` and `scsipi-ibmtape` backends reconnect. On macOS and
  FreeBSD a lost path is a plain `EIO` and the volume is left as it is, with a
  reservation the drive may still hold.
- A reconnect that finds no path closes the descriptor for good; later
  requests fail with `EDEV_NO_CONNECTION` and never try again, even when the
  drive comes back. Only a new mount recovers.
