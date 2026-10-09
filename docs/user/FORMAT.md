# LTFS format versions

The LTFS Format Specification defines data placement, index structure, and
extended attribute names. The specification is published by
[SNIA](https://www.snia.org/tech_activities/standards/curr_standards/ltfs) and
forwarded to [ISO](https://www.iso.org/home.html) as ISO/IEC 20919.

| Version | Status of SNIA                                                                                                        | Status of ISO                                                        |
|:-------:|:---------------------------------------------------------------------------------------------------------------------:|:--------------------------------------------------------------------:|
| 2.2     | [Published](https://www.snia.org/sites/default/files/LTFS_Format_2.2.0_Technical_Position.pdf)                             | [Published as `20919:2016`](https://www.iso.org/standard/69458.html) |
| 2.3.1   | [Published](https://www.snia.org/sites/default/files/technical-work/ltfs/release/SNIA-LTFS-Format-2.3.1-TechPosition.pdf)  | -                                                                    |
| 2.4     | [Published](https://www.snia.org/sites/default/files/technical_work/LTFS/LTFS_Format_2.4.0_TechPosition.pdf)               | -                                                                    |
| 2.5.1   | [Published](https://www.snia.org/sites/default/files/technical-work/ltfs/release/SNIA-LTFS-Format-2-5-1-Standard.pdf) | [Published as `20919:2021`](https://www.iso.org/standard/80598.html) |

Aurora LTFS targets version 2.5.1.

## What Aurora LTFS reads and writes

Aurora LTFS reads volumes of any format version from 1.0 to 2.x and writes
labels and indexes at version 2.5.0. Version 2.5 changes nothing in the label
or the full index; its one on-tape addition is the incremental index.

The syncs that promise nothing about the state of the files (periodic sync,
sync on close) write incremental indexes by default;
`-o full_index_interval=<num>` changes that (`0`: full indexes only, like the
reference implementation; `N`: N incremental indexes, then a full one;
negative: incremental only, the default). An unmount and an explicit sync
(`ltfs.sync`, `ltfs.commitMessage`, `ltfs.vendor.Aurora.FullSync`) write a
full index whatever the setting, `ltfs.vendor.Aurora.IncrementalSync` an
incremental one, and only full indexes are rollback points. After a failure
`altfsck` replays the incremental indexes on top of the last full index, or
leaves the volume at its last full index if they cannot be applied.

When a volume written at an older version is modified, its next index is
written at 2.5.0 (announced by `ALX0074W` at mount).

## Interoperability

The LTFS reference implementation and the products built on it (IBM, HPE,
Quantum, the macOS LTFS applications) accept labels and indexes of any 2.x
version, so a cleanly unmounted volume written by Aurora LTFS mounts there,
with a warning that the index is newer than the software. That is what the
specification intends: version 2.5.1 asks implementations to read volumes
with a higher minor version than their own (section 2.2) and states that a
consistent volume containing incremental indexes poses no problem for earlier
implementations (Annex H.2).

What they cannot use is an incremental index: a volume that a failure left
with incremental indexes after its last full index is recovered by them to
that last full index, and the changes recorded only incrementally are lost
until `altfsck` has replayed them. For a tape that other implementations will
read after a failure, mount with `-o full_index_interval=0`.

Independent implementations that are not derived from the reference code may
check the version string strictly; none has been verified.
