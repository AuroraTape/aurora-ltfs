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

The version of the document and the version written to the tape differ in
the last digit. A version number is M.N.R, and the specification defines R as
a textual revision that changes neither the on-media format nor the
semantics; the 2.5.1 document says of itself that it describes format version
2.5.0, and the `version` attribute of its label and index examples is 2.5.0.
That is what the labels and indexes carry.

## What Aurora LTFS reads and writes

Aurora LTFS reads volumes of any format version from 1.0 to 2.x. A volume it
formats is written at version 2.5.0. An existing volume keeps the version it
was written at, so it stays what it was for the implementation that formatted
it:

- a 2.5 volume stays at 2.5.0;
- a 2.4 volume stays at 2.4.0;
- an older volume is written at 2.4.0, the oldest version whose full index
  this software writes, from its next index on (announced by `ALX0074W` at
  mount);
- a volume of a newer version is written at 2.5.0, the newest version this
  software writes (announced by `ALX0075W` or `ALX0089W` at mount), and so
  receives incremental indexes like a 2.5 volume.

The version of a volume is the higher of its label and its last index: a
volume labelled 2.5.0 is written at 2.5.0 even if another implementation
wrote its last index at 2.4.0.

Version 2.5 changes nothing in the label or the full index; its one on-tape
addition is the incremental index, so only a 2.5 volume receives incremental
indexes. A volume below 2.5 is announced at mount by `ALB0287I`, which names
the version it keeps.

On a 2.5 volume, the syncs that promise nothing about the state of the files
(periodic sync, sync on close) write incremental indexes by default;
`-o full_index_interval=<num>` changes that (`0`: full indexes only, like the
reference implementation; `N`: N incremental indexes, then a full one;
negative: incremental only, the default). An unmount and an explicit sync
(`ltfs.sync`, `ltfs.commitMessage`, `ltfs.vendor.Aurora.FullSync`) write a
full index whatever the setting, `ltfs.vendor.Aurora.IncrementalSync` an
incremental one, and only full indexes are rollback points. After a failure
`altfsck` replays the incremental indexes on top of the last full index, or
leaves the volume at its last full index if they cannot be applied.

On a volume below 2.5 every index is a full index, whatever
`-o full_index_interval` says, and writing `ltfs.vendor.Aurora.IncrementalSync`
fails with `EINVAL`.

## Interoperability

The LTFS reference implementation and the products built on it (IBM, HPE,
Quantum, the macOS LTFS applications) accept labels and indexes of any 2.x
version, so a cleanly unmounted volume written by Aurora LTFS mounts there;
a 2.5 volume mounts with a warning that the index is newer than the software,
a volume that kept an older version looks to them as before. That is what the
specification intends: version 2.5.1 asks implementations to read volumes
with a higher minor version than their own (section 2.2) and states that a
consistent volume containing incremental indexes poses no problem for earlier
implementations (Annex H.2).

What they cannot use is an incremental index: a 2.5 volume that a failure left
with incremental indexes after its last full index is recovered by them to
that last full index, and the changes recorded only incrementally are lost
until `altfsck` has replayed them. For a tape that other implementations will
read after a failure, mount with `-o full_index_interval=0`.

Independent implementations that are not derived from the reference code may
check the version string strictly; none has been verified.
