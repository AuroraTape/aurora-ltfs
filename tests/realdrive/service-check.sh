#!/bin/bash
#
# Real-drive check of the mount service (#105): altfs@<serial>.service set up
# by altfsctl, running altfs as the "altfs" user. Run as root on a systemd
# host (Debian / Ubuntu) with the packages under test installed, or let the
# script install them. See README.md in this directory.
#
#   sudo ./service-check.sh --device <serial> [options]
#   sudo ./service-check.sh --device <serial> --after-reboot
#
#   --device SERIAL   drive serial (from "altfs -o device_list"), also the
#                     instance name
#   --deb-dir DIR     first install libaltfs0_*.deb and altfs_*.deb from DIR
#   --mnt DIR         mount point (default: /mnt/altfs-svc; must not exist,
#                     or be empty and belong to the altfs user)
#   --user USER       user who reads and writes the volume through the group
#                     (default: the user who ran sudo)
#   --gid GROUP       group of the files on the volume (default: the primary
#                     group of --user, who has to be a member); the volume is
#                     mounted with umask 007
#   --fix-fuse-conf   let altfsctl add user_allow_other to /etc/fuse.conf
#   --reboot          end with the instance enabled and the volume mounted,
#                     for a reboot; then run again with --after-reboot
#   --after-reboot    check the volume after that reboot, then clean up
#   --keep            leave the instance set up at the end
#
# The cartridge has to be LTFS formatted with a block size this host can
# transfer, and the drive loaded when the script starts. The script writes a
# directory service-check-<time> to it; nothing else on the volume is touched.
# Run it from a terminal: it asks you to eject and insert the cartridge.
#
#   S1  altfsctl check / add
#   S2  start with the cartridge in the drive: mounted, altfs runs as the
#       altfs user with CAP_SYS_RAWIO, the start does not wait for the mount
#   S3  access through the group by --user; a user outside it is refused
#   S4  log lines once in the journal, also in /var/log/altfs.log
#   S5  systemctl stop: index written, clean unmount; data there after a
#       restart, without a full consistency check
#   S6  empty drive: the instance waits; stop while waiting; start again and
#       insert the cartridge: mounted, data there
#   S7  (--reboot / --after-reboot) reboot with the volume mounted: index
#       written at shutdown, mounted again at boot, data there

set -u
export LANG=C.UTF-8
DEV="" ; DEB_DIR="" ; MNT="/mnt/altfs-svc" ; OTHER="${SUDO_USER:-}" ; GROUP=""
FIX_FUSE=0 ; REBOOT=0 ; AFTER_REBOOT=0 ; KEEP=0
# Kept across the reboot; root only (not /var/tmp, where anybody can plant a file)
STATE_DIR=/var/lib/altfs-service-check
STATE="$STATE_DIR/state"
need() { [ "$1" -ge 2 ] || { echo "$2 needs a value" >&2; exit 2; }; }
while [ $# -gt 0 ]; do
	case "$1" in
		--device)        need $# "$1"; DEV="$2"; shift 2 ;;
		--deb-dir)       need $# "$1"; DEB_DIR="$2"; shift 2 ;;
		--mnt)           need $# "$1"; MNT="$2"; shift 2 ;;
		--user)          need $# "$1"; OTHER="$2"; shift 2 ;;
		--gid)           need $# "$1"; GROUP="$2"; shift 2 ;;
		--fix-fuse-conf) FIX_FUSE=1; shift ;;
		--reboot)        REBOOT=1; shift ;;
		--after-reboot)  AFTER_REBOOT=1; shift ;;
		--keep)          KEEP=1; shift ;;
		-h|--help) sed -n '2,42p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
		*) echo "unknown option: $1" >&2; exit 2 ;;
	esac
done
[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 2; }
[ -n "$DEV" ] || { echo "--device <serial> is required" >&2; exit 2; }
[[ $DEV =~ ^[A-Za-z0-9_.-]+$ ]] || { echo "--device: not a serial number" >&2; exit 2; }
# The paths end up in eval'd checks and in the state file
[[ $MNT =~ ^/[A-Za-z0-9/._-]+$ ]] || { echo "--mnt: use an absolute path of letters, digits and / . _ -" >&2; exit 2; }
[ -d /run/systemd/system ] || { echo "systemd is not running" >&2; exit 2; }
UNIT="altfs@$DEV.service"

WORK="$(mktemp -d /var/tmp/service-check.XXXXXX)"
PASS=0; FAIL=0; INV=""
say()  { echo "$*" | tee -a "$WORK/report.txt"; }
pass() { PASS=$((PASS+1)); say "  PASS  $*"; }
fail() { FAIL=$((FAIL+1)); say "  FAIL  $*"; }
info() { say "  ....  $*"; }
check() { if eval "$1"; then pass "$2"; else fail "$2"; fi; }   # check CONDITION TEXT
show() { systemctl show -p "$1" --value "$UNIT"; }
# Messages of the current run of the instance. Selected by the invocation ID,
# not by time: "--since" has a resolution of one second and would also catch
# the previous run's messages.
log_inv() { [ -n "$INV" ] && journalctl -o cat --no-pager _SYSTEMD_INVOCATION_ID="$INV" 2>/dev/null; }
start_unit() { systemctl start "$UNIT"; INV="$(show InvocationID)"; }
summary() {
	say ""
	say "=== Summary: $PASS passed, $FAIL failed"
	if [ "$FAIL" -eq 0 ]; then
		rm -f "$WORK/data.bin"
		echo "report: $WORK/report.txt"
	else
		echo "logs: $WORK"
	fi
	[ "$FAIL" -eq 0 ]
}
cleanup() {  # stop and remove the instance, unless it is kept for a reboot
	if [ "$KEEP" -eq 0 ]; then
		systemctl stop "$UNIT" 2>/dev/null
		altfsctl remove "$DEV" >/dev/null 2>&1 && info "instance removed (mount point $MNT left in place)"
		rm -rf "$STATE_DIR"
	fi
}
wait_mounted() {  # wait_mounted SECONDS -> 0 when the volume is mounted
	local i=0
	until mountpoint -q "$MNT"; do
		[ "$i" -ge "$1" ] && return 1
		case "$(show ActiveState)" in
			failed) return 1 ;;
			# right after boot the instance may not have been started yet
			inactive) [ "$i" -ge 30 ] && return 1 ;;
		esac
		sleep 1; i=$((i+1))
	done
}
wait_log() {  # wait_log PATTERN SECONDS -> 0 when the current run logs PATTERN
	local i=0
	until log_inv | grep -q "$1"; do
		[ "$i" -ge "$2" ] && return 1
		[ "$(show ActiveState)" = failed ] && return 1
		sleep 1; i=$((i+1))
	done
}
stop_unit() {  # stop_unit TEXT -> stops the instance and checks the outcome
	local t0 took
	t0=$(date +%s)
	systemctl stop "$UNIT"
	took=$(( $(date +%s) - t0 ))
	info "$1: systemctl stop took $took s"
	check "! mountpoint -q '$MNT'" "$1: unmounted"
	check "[ \"\$(show Result)\" = success ]" "$1: Result=$(show Result)"
}
prompt() { say ""; say "  >>> $*"; read -r _ </dev/tty; }

# --- after a reboot --------------------------------------------------------
if [ "$AFTER_REBOOT" -eq 1 ]; then
	if [ ! -f "$STATE" ] || [ -L "$STATE" ] || [ ! -O "$STATE" ]; then
		echo "$STATE not found (or not root's): run with --reboot first" >&2; exit 2
	fi
	# shellcheck disable=SC1090
	. "$STATE"
	[ "$S_DEV" = "$DEV" ] || { echo "the reboot was prepared for $S_DEV, not $DEV" >&2; exit 2; }
	if [ "$(cat /proc/sys/kernel/random/boot_id)" = "$S_BOOT_ID" ]; then
		echo "the host has not been rebooted yet: reboot, then run this again" >&2; exit 2
	fi
	MNT="$S_MNT"
	trap cleanup EXIT
	say "=== S7: after the reboot ($UNIT)"
	if journalctl --list-boots --no-pager 2>/dev/null | grep -q "${S_BOOT_ID//-/}"; then
		journalctl -b "${S_BOOT_ID//-/}" -u "$UNIT" -o cat --no-pager > "$WORK/previous-boot.log" 2>&1
		check "grep -q ALB0035I '$WORK/previous-boot.log'" "previous boot: index written and unmounted at shutdown (ALB0035I)"
	else
		info "the journal of the previous boot is not kept (no persistent journal): ALB0035I not checked"
	fi
	if wait_mounted 600; then
		pass "mounted again at boot"
		INV="$(show InvocationID)"
		check "! log_inv | grep -q ALB0028I" "mounted without a full consistency check"
		check "cmp -s '$STATE_DIR/data.bin' '$MNT/$S_DIR/data.bin'" "data written before the reboot is there"
		check "[ \"\$(cat '$MNT/$S_DIR/marker')\" = \"\$S_MARKER\" ]" "file written just before the reboot is there"
	else
		fail "not mounted within 10 minutes after boot ($(show ActiveState))"
	fi
	altfsctl disable "$DEV" >/dev/null
	stop_unit "stop after the reboot"
	summary; exit
fi

# --- set up ----------------------------------------------------------------
if [ -n "$DEB_DIR" ]; then
	say "=== Installing the packages from $DEB_DIR"
	if apt-get install -y "$DEB_DIR"/libaltfs0_*.deb "$DEB_DIR"/altfs_*.deb > "$WORK/install.log" 2>&1; then
		pass "packages installed"
	else
		fail "package installation"; tail -5 "$WORK/install.log"; summary; exit
	fi
fi
command -v altfsctl >/dev/null || { echo "altfsctl is not installed" >&2; exit 2; }
[ -n "$OTHER" ] || { echo "--user is required when not run through sudo" >&2; exit 2; }
id "$OTHER" >/dev/null 2>&1 || { echo "user $OTHER does not exist" >&2; exit 2; }
[ -n "$GROUP" ] || GROUP="$(id -gn "$OTHER")"
id -nG "$OTHER" | tr ' ' '\n' | grep -qx "$GROUP" \
	|| { echo "$OTHER is not a member of $GROUP" >&2; exit 2; }
if [ -e "/etc/altfs/$DEV.conf" ]; then
	echo "$DEV is already set up (/etc/altfs/$DEV.conf): altfsctl remove $DEV first" >&2; exit 2
fi
trap cleanup EXIT

say "=== service check of $DEV ($(altfs -V 2>&1 | grep -o 'version [^ ]*' | head -1))"
info "altfs user: $(getent passwd altfs || echo none)"

say "=== S1: altfsctl check / add"
altfsctl check "$DEV" > "$WORK/check.log" 2>&1
sed 's/^/        /' "$WORK/check.log" | tee -a "$WORK/report.txt"
opts=(--gid "$GROUP" --umask 007)
[ "$FIX_FUSE" -eq 1 ] && opts+=(--fix-fuse-conf)
if altfsctl add "${opts[@]}" "$DEV" "$MNT" > "$WORK/add.log" 2>&1; then
	pass "altfsctl add (group $GROUP, umask 007)"
else
	fail "altfsctl add"; sed 's/^/        /' "$WORK/add.log" | tail -8 | tee -a "$WORK/report.txt"
	trap - EXIT; summary; exit
fi

# --- S2 ----------------------------------------------------------------------
say "=== S2: start with the cartridge in the drive"
LOGFILE_BEFORE=$(grep -c AFS0025I /var/log/altfs.log 2>/dev/null || true)
LOGFILE_BEFORE=${LOGFILE_BEFORE:-0}
t0=$(date +%s)
start_unit
took=$(( $(date +%s) - t0 ))
check "[ '$took' -le 5 ]" "systemctl start returned after $took s (Type=exec does not wait for the mount)"
if wait_mounted 600; then
	pass "mounted $(( $(date +%s) - t0 )) s after the start"
else
	fail "not mounted within 10 minutes ($(show ActiveState))"
	log_inv | grep -E '[0-9A-Z]{4}[EW] ' | head -5 | sed 's/^/        /' | tee -a "$WORK/report.txt"
	summary; exit
fi
PID="$(show MainPID)"
check "[ \"\$(ps -o user= -p '$PID' | tr -d ' ')\" = altfs ]" "altfs runs as the altfs user (pid $PID)"
CAPAMB="$(awk '/^CapAmb:/ {print $2}' "/proc/$PID/status" 2>/dev/null)"
check "[ -n '$CAPAMB' ] && (( 0x$CAPAMB & 0x20000 ))" "CAP_SYS_RAWIO is in the ambient set (CapAmb ${CAPAMB:-?})"
check "grep ' $MNT fuse' /proc/mounts | grep -q allow_other" "mounted with allow_other"

# --- S3 ----------------------------------------------------------------------
say "=== S3: access through the group"
DIR="service-check-$(date +%Y%m%d-%H%M%S)"
head -c 20000000 /dev/urandom > "$WORK/data.bin"
chmod 644 "$WORK/data.bin"; chmod 755 "$WORK"
check "runuser -u '$OTHER' -- mkdir '$MNT/$DIR'" "$OTHER creates a directory"
check "runuser -u '$OTHER' -- cp '$WORK/data.bin' '$MNT/$DIR/data.bin'" "$OTHER writes 20 MB"
check "runuser -u '$OTHER' -- cmp -s '$WORK/data.bin' '$MNT/$DIR/data.bin'" "$OTHER reads it back"
check "! runuser -u nobody -- ls '$MNT' >/dev/null 2>&1" "nobody (not in $GROUP) cannot list the volume"
check "[ \"\$(stat -c %G '$MNT/$DIR')\" = '$GROUP' ]" "files belong to the group $GROUP"

# --- S4 ----------------------------------------------------------------------
say "=== S4: logging"
n=$(log_inv | grep -c AFS0025I)
check "[ '$n' -eq 1 ]" "AFS0025I once in the journal of the run (found $n)"
if [ -f /var/log/altfs.log ]; then
	sleep 2
	after=$(grep -c AFS0025I /var/log/altfs.log || true)
	check "[ '${after:-0}' -gt '$LOGFILE_BEFORE' ]" "AFS0025I also in /var/log/altfs.log"
else
	info "no /var/log/altfs.log (rsyslog rule not active)"
fi

# --- S5 ----------------------------------------------------------------------
say "=== S5: systemctl stop with the volume mounted"
stop_unit "stop"
check "log_inv | grep -q ALB0035I" "index written, volume unmounted (ALB0035I)"
start_unit
if wait_mounted 600; then
	check "cmp -s '$WORK/data.bin' '$MNT/$DIR/data.bin'" "data there after a restart"
	check "! log_inv | grep -q ALB0028I" "restart without a full consistency check"
else
	fail "restart: not mounted"
fi
stop_unit "stop before the empty-drive case"

# --- S6 ----------------------------------------------------------------------
say "=== S6: empty drive"
prompt "Eject the cartridge and take it out of the drive, then press Enter"
start_unit
if wait_log AFS0141I 120; then
	pass "waits for a cartridge (AFS0141I)"
	check "[ \"\$(show ActiveState)\" = active ] && ! mountpoint -q '$MNT'" "active and not mounted while waiting"
	stop_unit "stop while waiting"
	check "log_inv | grep -q AFS0144I" "AFS0144I on the stop"
else
	fail "no AFS0141I within 2 minutes ($(show ActiveState))"
	systemctl stop "$UNIT"
fi
start_unit
if wait_log AFS0141I 120; then
	say ""
	say "  >>> NOW: push the cartridge fully in (waiting up to 15 minutes)"
	say ""
	if wait_mounted 900; then
		pass "mounted after the cartridge was inserted"
		check "cmp -s '$WORK/data.bin' '$MNT/$DIR/data.bin'" "data there"
	else
		fail "not mounted within 15 minutes"
	fi
else
	fail "second start: no AFS0141I"
fi

# --- S7, first half ----------------------------------------------------------
if [ "$REBOOT" -eq 1 ]; then
	say "=== S7: prepare the reboot"
	if ! mountpoint -q "$MNT"; then
		fail "S7: not mounted, the reboot is not prepared"
	else
		altfsctl enable "$DEV" >/dev/null && pass "instance enabled" || fail "altfsctl enable"
		MARKER="written $(date '+%F %T') before the reboot"
		check "runuser -u '$OTHER' -- sh -c 'echo \"$MARKER\" > \"$MNT/$DIR/marker\"'" "marker file written"
		[ -d /var/log/journal ] || info "no persistent journal: the shutdown cannot be checked after the reboot"
		rm -rf "$STATE_DIR"
		if (umask 077 && mkdir "$STATE_DIR" && cp "$WORK/data.bin" "$STATE_DIR/data.bin" \
			&& printf 'S_%s=%q\n' DEV "$DEV" MNT "$MNT" DIR "$DIR" MARKER "$MARKER" \
				BOOT_ID "$(cat /proc/sys/kernel/random/boot_id)" > "$STATE"); then
			KEEP=1
			say ""
			say "  >>> Leave the cartridge in the drive and reboot (sudo systemctl reboot)."
			say "      Afterwards run: sudo $0 --device $DEV --after-reboot"
		else
			fail "cannot write $STATE"
		fi
	fi
fi

summary
