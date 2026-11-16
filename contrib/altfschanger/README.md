# altfschanger

Send single operations to the medium changer of a tape library through a
changer plugin. It is a development tool for testing the changer plugins
and for driving a library by hand, and it keeps no state between runs.

It is built with the tree but not installed. Run it from the build tree,
after `make install` has put the plugins and the configuration file in
place:

```
contrib/altfschanger/altfschanger [-e <plugin>] [-i <config>] list
contrib/altfschanger/altfschanger -d <changer> [-e <plugin>] [-i <config>] [-o <option>] [--verbose=<n>] <command> [<argument>...]
```

Elements are named by their address as the changer reports it. The library
is shared with its operator panel and with other hosts, and altfschanger
does not reserve it: read the element status before a move.

## Options

| Option | Meaning |
|:-------|:--------|
| `-d, --device=<name>` | The changer. For the `file` plugin, a library directory, or the name or serial number of a library directory under `$ALTFS_FILE_CHANGER_ROOT` |
| `-e, --backend=<name>` | Changer plugin (default: `default changer` of the configuration file) |
| `-i, --config=<file>` | Configuration file |
| `-o <option>` | Option for the plugin; `help` lists them |
| `--verbose=<n>` | Log level: 0 errors, 1 warnings, 2 informational (default), 3 to 6 debug |

## Commands

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

The exit status is 0 on success, 8 when the operation failed (`ACH0004E`
gives the internal error code) and 16 for a usage error.

A file-backed library to try it on is made with `tests/tools/filelib.py`.
