---
name: Drive report
about: Report a tape drive that works, works with limitations, or fails with Aurora LTFS
title: "Drive report: [drive vendor/model]"

---

**Fill in the information of the drive and the environment**

| Drive vendor | Model / generation / form factor | Firmware level | HBA and I/F type (SAS, FC etc) | OS  | Aurora LTFS version or commit hash |
| ------------ | -------------------------------- | -------------- | ------------------------------ | --- | ---------------------------------- |
|              |                                  |                |                                |     |                                    |

**Output of `altfs -o device_list` for the drive**

```
```

**What was tried**

Put `OK`, `NG` or `-` (not tried).

| mkaltfs | mount | write files | read files | unmount | remount | altfsck |
| ------- | ----- | ----------- | ---------- | ------- | ------- | ------- |
|         |       |             |            |         |         |         |

**Log output**
For a failure, attach the log around the first error, preferably taken with `-o loglevel=4` (terminal output, `/var/log/altfs.log` or the journal).

**Additional context**
Limitations you noticed, workarounds, anything else worth knowing about this drive.
