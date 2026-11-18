# altfschanger

Send single operations to the medium changer of a tape library. It is a
development tool for testing the changer plugins and the changer layer and
for driving a library by hand, and it keeps no state between runs.

It is built with the tree but not installed. Run it from the build tree,
after `make install` has put the plugins and the configuration file in
place:

```
contrib/altfschanger/altfschanger [-e <plugin>] [-i <config>] list
contrib/altfschanger/altfschanger -d <changer> [-e <plugin>] [-i <config>] [-o <option>] [--verbose=<n>]
    [--ready-wait=<s>] [--move-wait=<s>] <command> [<argument>...]
```

The plugin commands go straight to the changer plugin and name elements by
their address as the changer reports it. They check nothing: the library
is shared with its operator panel and with other hosts and is not
reserved, so read the element status before a move.

The cartridge commands go through the changer layer and name cartridges by
barcode and drives by serial number (by element address on a changer that
does not report drive serial numbers). Each one reads the whole library,
reads the elements a move touches right before the move, and prints the
inventory when it succeeds. The layer re-reads what a unit attention says
has changed and does not repeat a move whose outcome is unknown.

## Options

| Option | Meaning |
|:-------|:--------|
| `-d, --device=<name>` | The changer. For the `file` plugin, a library directory, or the name or serial number of a library directory under `$ALTFS_FILE_CHANGER_ROOT` |
| `-e, --backend=<name>` | Changer plugin (default: `default changer` of the configuration file) |
| `-i, --config=<file>` | Configuration file |
| `-o <option>` | Option for the plugin; `help` lists them |
| `--verbose=<n>` | Log level: 0 errors, 1 warnings, 2 informational (default), 3 to 6 debug |
| `--ready-wait=<s>` | How long a cartridge command waits for a changer that is not ready (door open) before it fails (default: 30) |
| `--move-wait=<s>` | How long a cartridge may be in neither element of a move (on the picker) before the layer re-reads the library (default: 5) |

## Plugin commands

| Command | What it does |
|:--------|:-------------|
| `list` | List the changers this host can reach |
| `info` | Identity, element address assignment, and whether the changer reads barcodes, reports drive serial numbers and accepts EXCHANGE MEDIUM |
| `elements [<type> [<start> [<count>]]]` | Element status, one element per line: type, address, `full`/`empty`, `voltag=`, `source=`, `dvcid=` and the flags `inaccessible`, `except=<ASC>/<ASCQ>`, `impexp`. `<type>` is `transport`, `storage`, `ie`, `drive` or `any` (default) |
| `move <source> <dest> [<transport>]` | MOVE MEDIUM |
| `exchange <source> <dest1> <dest2> [<transport>]` | EXCHANGE MEDIUM: `<source>` goes to `<dest1>`, and the cartridge at `<dest1>` goes to `<dest2>` (which may be `<source>`) |
| `scan [<start> <count>]` | INITIALIZE ELEMENT STATUS; minutes on a large library |
| `tur` | TEST UNIT READY |
| `prevent`, `allow` | Lock or unlock the import/export station |
| `help` | Options of the plugin |

## Cartridge commands

| Command | What it does |
|:--------|:-------------|
| `inventory` | The library (`library` line: identity, ready, stale, counts, last unit attention), its drives (`drive` lines: serial, address, what it holds) and its cartridges (`tape` lines: barcode, where, address, state, home slot). Cartridges without a readable barcode are listed as `unlabeled<n>` in address order |
| `rescan [deep]` | Read every element again; `deep` makes the changer re-read its elements first |
| `load <barcode> <drive>` | Move the cartridge into the drive. A duplicate barcode, a cleaning cartridge (`CLN`) and a cartridge in the import/export station are refused |
| `return <drive>` | Move the cartridge in the drive back to the slot it came from, or to a free slot when that one is taken or not known |
| `swap <barcode> <drive>` | Return the cartridge in the drive and load the other one, with EXCHANGE MEDIUM when the changer accepts it and two moves otherwise |
| `export <barcode>` | Move the cartridge to a free import/export element |
| `import <barcode>` | Move the cartridge from the import/export station to a free storage slot |

The cartridge commands only move cartridges: they do not load the tape in
the drive, mount it or unload it.

The exit status is 0 on success, 8 when the operation failed (`ACH0004E`
gives the internal error code) and 16 for a usage error.

A file-backed library to try it on is made with `tests/tools/filelib.py`.
