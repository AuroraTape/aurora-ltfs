#!/bin/bash
#
# Real-drive check of altfs -o wait_medium (#104 / #146): start on an empty
# drive, time limit, SIGTERM while waiting, and a cartridge inserted while
# altfs waits. Run as root (the sg command filter needs CAP_SYS_RAWIO).
# See README.md in this directory.
#
#   sudo ./wait-medium-check.sh --device <serial> [--prefix DIR] [--mnt DIR] [--format]
#
#   --device SERIAL  drive serial (from "altfs -o device_list")
#   --prefix DIR     test the build installed in DIR (default: the installed
#                    commands found in PATH)
#   --mnt DIR        mount point (default: /mnt/altfs-wm, must be empty)
#   --format         first format the cartridge that is in the drive now
#                    (ERASES IT) without -b, so mkaltfs picks a block size the
#                    host can transfer (#148). Then asks to eject it
#
# Flow: the drive must be EMPTY for steps A-C; D1 and D2 ask you to insert
# the cartridge while altfs is waiting. The cartridge must be LTFS formatted
# with a block size this host can transfer; --format takes care of that.
#
#   A  no option, empty drive      -> fails fast (no endless loop), exit != 0;
#                                     the drive dump taken on the failed LOAD
#                                     can be read (#149)
#   B  wait_medium=20, empty drive -> gives up after ~20 s, AFS0145E, exit 1
#   C  wait_medium, then SIGTERM   -> AFS0144I, exit 0, drive released
#   D1 wait_medium, push the cartridge fully in (the drive loads it itself)
#   D2 wait_medium, insert the cartridge only to the lock position (altfs
#      has to issue LOAD)
#      -> AFS0143I, mount completes, write, unmount exit 0, data there after
#         a normal remount; that remount ejects the cartridge at unmount
#
# Insert the cartridge only when the script says so: before that, altfs is
# still in its initial load attempt and the wait is not exercised.

set -u
export LANG=C.UTF-8
DEV="" ; PREFIX="" ; MNT="/mnt/altfs-wm" ; FORMAT=0
while [ $# -gt 0 ]; do
	case "$1" in
		--device) DEV="$2"; shift 2 ;;
		--prefix) PREFIX="$2"; shift 2 ;;
		--mnt)    MNT="$2"; shift 2 ;;
		--format) FORMAT=1; shift ;;
		-h|--help) sed -n '2,36p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
		*) echo "unknown option: $1" >&2; exit 2 ;;
	esac
done
if [ -n "$PREFIX" ]; then
	export PATH="$PREFIX/bin:$PATH" LD_LIBRARY_PATH="$PREFIX/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi
ALTFS="$(command -v altfs)"; MKALTFS="$(command -v mkaltfs)"
# Dry-run hooks for testing this script with the file backend (the scenario
# tests use them; not needed on a real drive): WM_DRYRUN=1 skips the root
# check, WM_EXTRA_OPTS adds altfs options, WM_INSERT_CMD "inserts" the
# cartridge in steps D1/D2, WM_EJECT_CMD empties the drive after each of
# them, WM_LIMIT replaces the 20 s limit of step B.
[ "$(id -u)" -eq 0 ] || [ "${WM_DRYRUN:-0}" = 1 ] || { echo "run as root" >&2; exit 2; }
[ -n "$DEV" ] || { echo "--device <serial> is required" >&2; exit 2; }
[ -n "$ALTFS" ] && [ -x "$ALTFS" ] || { echo "altfs not found (use --prefix)" >&2; exit 2; }
mkdir -p "$MNT"
if mountpoint -q "$MNT" || [ -n "$(ls -A "$MNT")" ]; then
	echo "$MNT is mounted or not empty" >&2; exit 2
fi

WORK="$(mktemp -d /var/tmp/wait-medium-check.XXXXXX)"
PASS=0; FAIL=0; PID=""
say()  { echo "$*" | tee -a "$WORK/report.txt"; }
pass() { PASS=$((PASS+1)); say "  PASS  $*"; }
fail() { FAIL=$((FAIL+1)); say "  FAIL  $*"; }
info() { say "  ....  $*"; }
cleanup() {
	[ -n "$PID" ] && kill -0 "$PID" 2>/dev/null && { kill -TERM "$PID"; wait "$PID" 2>/dev/null; }
	mountpoint -q "$MNT" && unmount
	echo; echo "logs: $WORK"
}
trap cleanup EXIT

# start altfs in the foreground, in the background of this script
start_altfs() {  # start_altfs LOG [options...]
	local log="$1"; shift
	# shellcheck disable=SC2086
	"$ALTFS" -f -o devname="$DEV" ${WM_EXTRA_OPTS:-} "$@" "$MNT" > "$log" 2>&1 &
	PID=$!
}
wait_for() {  # wait_for LOG PATTERN SECONDS -> 0 when PATTERN shows up while altfs runs
	local i=0
	while [ "$i" -lt "$3" ]; do
		grep -q "$2" "$1" && return 0
		kill -0 "$PID" 2>/dev/null || return 1
		sleep 1; i=$((i+1))
	done
	return 1
}
finish() {  # finish SECONDS -> exit status of altfs (124 if it had to be stopped)
	# Wait SECONDS, then ask altfs to stop (SIGTERM, or an unmount if it is
	# mounted) and give it 15 minutes to write the index and release the
	# drive. SIGKILL only as the very last resort: a killed altfs leaves the
	# medium locked (PREVENT MEDIUM REMOVAL) and a dead mount behind.
	local i=0 stopped=0
	while kill -0 "$PID" 2>/dev/null; do
		if [ "$i" -eq "$1" ]; then
			stopped=1
			if mountpoint -q "$MNT"; then unmount; else kill -TERM "$PID"; fi
		fi
		if [ "$i" -ge $(( $1 + 900 )) ]; then
			kill -KILL "$PID"; wait "$PID" 2>/dev/null; PID=""
			say "  !!!!  altfs had to be killed: remount and unmount once to release the medium lock"
			return 124
		fi
		sleep 1; i=$((i+1))
	done
	wait "$PID"; local rc=$?; PID=""
	[ "$stopped" -eq 1 ] && return 124
	return $rc
}
unmount() { umount "$MNT" 2>/dev/null || fusermount -u "$MNT"; }
errors() { grep -E '[0-9A-Z]{4}[EW] ' "$1" | grep -v ATF0062E | head -4 | sed 's/^/        /' | tee -a "$WORK/report.txt"; }

say "=== wait_medium on $DEV ($($ALTFS -V 2>&1 | grep -o 'version [^ ]*' | head -1))"

if [ "$FORMAT" -eq 1 ]; then
	say "=== Formatting the cartridge in the drive without -b (ERASED)"
	"$MKALTFS" -d "$DEV" -f > "$WORK/mkaltfs.log" 2>&1 && pass "mkaltfs" || { fail "mkaltfs"; errors "$WORK/mkaltfs.log"; exit 1; }
	grep -E 'ATG0107I|ATG0108W|AMK0084I' "$WORK/mkaltfs.log" | sed 's/^/        /' | tee -a "$WORK/report.txt"
	grep -q ATG0107I "$WORK/mkaltfs.log" && pass "host transfer limit reported (ATG0107I)" || fail "no ATG0107I"
	if grep -q ATG0108W "$WORK/mkaltfs.log"; then
		grep -q AMK0084I "$WORK/mkaltfs.log" && pass "block size lowered to what the host can transfer (AMK0084I)" || fail "limited host but no AMK0084I"
	else
		info "host limit is not below 512 KiB: the default block size is kept"
	fi
	read -r -p "  >>> Eject the cartridge now (drive must be EMPTY), then press Enter " _
fi

# --- A -------------------------------------------------------------------
say "=== A: no option, empty drive"
T0=$(date +%s); start_altfs "$WORK/A.log"
# If a cartridge is in the drive, altfs mounts and keeps running: stop at
# whichever comes first, the mount or the end of altfs.
i=0; while kill -0 "$PID" 2>/dev/null && ! mountpoint -q "$MNT" && [ "$i" -lt 120 ]; do sleep 1; i=$((i+1)); done
if mountpoint -q "$MNT"; then
	unmount; finish 300
	fail "a cartridge is in the drive: eject it and run again (steps A-C need an empty drive)"; exit 1
fi
finish 5; rc=$?
info "exit $rc after $(( $(date +%s) - T0 )) s"
[ "$rc" -ne 0 ] && [ "$rc" -ne 124 ] && pass "fails fast without the option (no endless loop)" || fail "exit $rc (124 = did not end within 120 s)"
errors "$WORK/A.log"
# #149: the drive dump taken on the failed LOAD is read in chunks the host
# path can transfer
if grep -q ATG0054I "$WORK/A.log"; then
	if grep -q ATG0059W "$WORK/A.log"; then
		fail "drive dump could not be read (ATG0059W)"
	else
		dump=$(grep -o 'ATG0054I Saving drive dump to [^ ]*' "$WORK/A.log" | tail -1 | awk '{print $NF}')
		pass "drive dump taken: $dump ($(stat -c %s "$dump" 2>/dev/null || echo '?') bytes)"
	fi
else
	info "no drive dump was taken"
fi

# --- B -------------------------------------------------------------------
LIMIT="${WM_LIMIT:-20}"
say "=== B: -o wait_medium=$LIMIT, empty drive"
T0=$(date +%s); start_altfs "$WORK/B.log" -o wait_medium="$LIMIT"
wait_for "$WORK/B.log" AFS0142I 60 && pass "AFS0142I (waiting up to $LIMIT s)" || fail "no AFS0142I"
finish 120; rc=$?; took=$(( $(date +%s) - T0 ))
info "exit $rc after $took s"
{ [ "$rc" -eq 1 ] && grep -q AFS0145E "$WORK/B.log"; } && pass "gives up with AFS0145E and exit 1" || { fail "exit $rc"; errors "$WORK/B.log"; }
[ "$took" -ge "$LIMIT" ] && [ "$took" -le $(( LIMIT + 40 )) ] && pass "gave up after the limit ($took s)" || fail "gave up after $took s"

# --- C -------------------------------------------------------------------
say "=== C: -o wait_medium, SIGTERM while waiting"
start_altfs "$WORK/C.log" -o wait_medium
if wait_for "$WORK/C.log" AFS0141I 60; then
	pass "AFS0141I (waiting without a limit)"
	sleep 7; kill -TERM "$PID"
	finish 60; rc=$?
	{ [ "$rc" -eq 0 ] && grep -q AFS0144I "$WORK/C.log"; } && pass "SIGTERM: AFS0144I and exit 0" || { fail "SIGTERM: exit $rc"; errors "$WORK/C.log"; }
else
	fail "no AFS0141I"; errors "$WORK/C.log"; finish 10
fi

# --- D1 / D2 -------------------------------------------------------------
d_case() {  # d_case TAG "what to do with the cartridge"
	local tag="$1" how="$2" log="$WORK/$1.log" i
	say "=== $tag: -o wait_medium, $how"
	start_altfs "$log" -o wait_medium
	# altfs first tries the regular load (LOAD, drive dumps on a real drive),
	# then announces the wait with AFS0141I
	i=0
	while [ "$i" -lt 180 ] && kill -0 "$PID" 2>/dev/null && ! grep -q AFS0141I "$log" && ! mountpoint -q "$MNT"; do
		sleep 1; i=$((i+1))
	done
	if mountpoint -q "$MNT"; then
		fail "mounted before altfs started to wait: the cartridge was inserted too early, the wait was not exercised"
		finish 0; return
	elif ! grep -q AFS0141I "$log"; then
		fail "no AFS0141I"; errors "$log"; finish 0; return
	fi
	pass "waiting ($(( i )) s after start)"
	say ""
	say "  >>> NOW: $how   (waiting up to 15 minutes)"
	say ""
	[ -n "${WM_INSERT_CMD:-}" ] && { sleep 8; eval "$WM_INSERT_CMD"; }
	local t0; t0=$(date +%s); i=0
	until mountpoint -q "$MNT" || ! kill -0 "$PID" 2>/dev/null || [ "$i" -ge 900 ]; do sleep 1; i=$((i+1)); done
	if ! mountpoint -q "$MNT"; then
		kill -0 "$PID" 2>/dev/null && fail "not mounted within 15 minutes" || fail "altfs ended without mounting"
		errors "$log"; finish 0; return
	fi
	pass "mounted $(( $(date +%s) - t0 )) s after the prompt"
	grep -q AFS0143I "$log" && pass "AFS0143I (medium detected)" || fail "no AFS0143I"
	head -c 3000000 /dev/urandom > "$WORK/$tag.bin"
	cp "$WORK/$tag.bin" "$MNT/" && pass "wrote a file" || fail "write"
	unmount; finish 900
	local rc=$?
	[ "$rc" -eq 0 ] && pass "unmount, altfs exit 0" || fail "altfs exit $rc after unmount"

	# normal remount, which also ejects the cartridge at unmount for the next case
	start_altfs "$WORK/$tag-remount.log" -o eject
	i=0; until mountpoint -q "$MNT" || ! kill -0 "$PID" 2>/dev/null || [ "$i" -ge 300 ]; do sleep 1; i=$((i+1)); done
	if mountpoint -q "$MNT"; then
		cmp -s "$WORK/$tag.bin" "$MNT/$tag.bin" && pass "data is there after a normal remount" || fail "data after remount"
		grep -q ALB0028I "$WORK/$tag-remount.log" && fail "remount ran a full consistency check" || pass "remount without consistency check"
		unmount; finish 900
	else
		fail "remount"; errors "$WORK/$tag-remount.log"; finish 0
	fi
	[ -n "${WM_EJECT_CMD:-}" ] && eval "$WM_EJECT_CMD"
}

d_case D1 "push the cartridge fully in (the drive loads it by itself)"
say ""
say "  >>> Take the ejected cartridge out of the drive (do not reinsert yet)"
[ -z "${WM_INSERT_CMD:-}" ] && read -r -p "      then press Enter " _
d_case D2 "insert the cartridge only to the lock position (do not push it in)"

say ""
say "=== Summary: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
