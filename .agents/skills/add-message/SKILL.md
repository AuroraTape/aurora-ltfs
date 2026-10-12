---
name: add-message
description: Add a new log/error message (ltfsmsg ID) to an Aurora LTFS message catalog under messages/ and wire it into the source, following the project's message-ID rules. Use when asked to "add a message", "add a new ltfsmsg", "new message ID", "new error message", or when a code change needs a new AXX####[EWID] ID.
---

# add-message

Adds one or more message IDs the way AGENTS.md / messages/README require, then
regenerates the bundle objects and validates.

## Inputs to establish first

- **Where the message is emitted** (source file). This decides the prefix:
  - `src/cmd/altfs` → AFS, `src/cmd/altfsck` → ACK, `src/cmd/altfsindextool` → AIX, `src/cmd/mkaltfs` → AMK
  - `src/iosched/fcfs.c` → AIF, `src/iosched/unified.c` → AIU (`cache_manager.c` uses the libltfs prefixes ALC/ALP; follow the `ltfsmsg()` calls already in the file)
  - `src/kmi/flatfile.c` → AKF, `src/kmi/simple.c` → AKS
  - `src/tape_drivers/`: common → ATM, freebsd/cam → ATC, generic/file → ATF, generic/itdtimg → ATI, osx/iokit → ATK, linux/sg → ATG, netbsd/scsipi-ibmtape → ATG
  - `src/libltfs/` is split into eight bundles (`messages/libaltfs/l?_root.txt`, prefixes ALB ALC ALF ALG ALI ALJ ALP ALX). Look at the header comment of each `l?_root.txt` and at the prefix already used by neighbouring `ltfsmsg()` calls in the same file, and follow that.
- **Severity**: E (error), W (warning), I (info), D (debug). The severity letter is part of the ID and cannot be changed later (see rules).
- **Text** with printf-style placeholders. The message-checker CI build type-checks the arguments against the catalog text, so `%s`/`%d`/`%lu`/`%llu` must match the C argument types exactly.

## Steps

1. **Pick the number** with the helper (counts commented-out/"unused" IDs too, so retired numbers are never reissued):
   ```bash
   python3 .agents/skills/add-message/next_id.py <PREFIX>
   ```
   Run `git branch --show-current`. On a release branch the number field must use the letter-bearing shape from messages/README ("Release-branch ID shapes", e.g. `AFSA001E` for 1.0.x); the helper only computes HEAD-pool (4-digit) numbers. Never invent an ID by hand-scanning the file.

2. **Add the catalog entry** to the bundle's `*root.txt` (the `en.txt`/`en_US.txt` files are intentionally blank, leave them). Append after the last entry of the table, keeping the existing tab indentation:
   ```
   		AMK0082E:string { "Cannot open device '%s' (%d)" }
   ```
   Escape single quotes as `\'` and double quotes as `\"` like the surrounding entries. Add several messages in one change with consecutive numbers; no gaps.

3. **Reference it from the source** with `ltfsmsg(AMK0082E, arg1, arg2);` (the ID is a bare token, not a string). Every defined ID must be referenced somewhere in `src/**/*.{c,h}` or `validate_error_messages.py` reports it as unused.

4. **Regenerate the bundle objects** (needs a configured tree; `./autogen.sh && ./configure` first if `messages/Makefile` does not exist):
   ```bash
   make -C messages
   ```
   This runs `make_message_src.sh` with the right libtool environment. Do not run the script by hand.

5. **Validate** from the repository root:
   ```bash
   python3 validate_error_messages.py
   ```
   Must print `All message IDs are consistent.` (The local hooks of Claude Code and Codex also run this after catalog edits, where they are set up.)

6. **Compile** the affected component (`make` or at least `make -C src/...`) so the new `ltfsmsg()` call is checked. Never leave the tree in a state that does not build.

## Rules baked in (from AGENTS.md / messages/README)

- Number is unique within a prefix across all severities: once `AFS0001I` exists, `AFS0001E/W/D` are forbidden forever.
- **Never change a message's severity letter.** If severity must change, retire the old ID and allocate a new number.
- Never reuse a number, including commented-out ones. Retire an ID by commenting it out with an `unused` prefix, do not delete it:
  ```
  		//unused AFS0024W:string { "..." }
  ```
- Before release, numbers stay consecutive; if you remove an ID you just added (unreleased), renumber the ones after it to close the gap.
- `AEI`/`AED` (messages/internal_error) are a registry of `src/libltfs/ltfs_error.h`: `AEI<n>` = value of the `LTFS_*` constant, `AED<n>` = `EDEV_*` value minus 20000. To add one, add the constant to `ltfs_error.h` first and derive the ID from it. New constants go on HEAD only; release branches backport them.
- Release-branch messages use the letter-bearing shapes (`AFSA001E`, `AFSAA01E`, ...) so pools never collide; do not use 4-digit IDs there.
- Message text: no trailing newline, no message ID inside the text, follow the phrasing style of neighbouring entries.
