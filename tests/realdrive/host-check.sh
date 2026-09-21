#!/bin/bash
#
# Aurora LTFS check on a real systemd host, optionally with a real tape
# drive. Debian / Ubuntu. Run as root. See README.md in this directory.
#
#   sudo ./host-check.sh --deb-dir DIR [options]      packages under test
#   sudo ./host-check.sh --skip-install [options]     packages already installed
#   sudo ./host-check.sh --prefix DIR [options]       a build tree ("make install
#                                                      --prefix"), no packages
#
#   --deb-dir DIR        directory with libaltfs0_*.deb and altfs_*.deb to install
#   --old-deb-dir DIR    install these (older) packages first and test the upgrade.
#                        Only when altfs is not installed yet.
#   --skip-install       the packages are already installed, do not touch them
#   --prefix DIR         test the build installed in DIR instead of the packages.
#                        Only the file-backend and real-drive phases run; the
#                        system integration (altfs.service, rsyslog, logrotate)
#                        belongs to the packages and is skipped.
#   --expect-version V   version `altfs -V` must report (default: not checked)
#   --device DEV         real tape drive (serial number or /dev/sgN): run the tape
#                        phase. Needs --erase-tape as well.
#   --erase-tape         confirm that the cartridge in DEV may be ERASED (mkaltfs)
#   --big-size SIZE      size of the large test file on tape      (default: 2G)
#   --blocksize BYTES    LTFS block size for mkaltfs on the real drive (default: the
#                        mkaltfs default, which since #149 follows the host limit;
#                        older builds need 262144 behind a 256 KiB limited HBA)
#   --mnt DIR            mount point                              (default: /mnt/altfs-rc)
#   --skip-logrotate     do not force a rotation of /var/log/altfs.log
#   --keep               keep the work directory (logs, file-backend tape)
#
# What it changes on the host: installs the packages, restarts rsyslog (done
# by the package), creates the mount point, rotates /var/log/altfs.log once,
# and STOPS and restarts altfs.service. Stopping altfs.service sends SIGTERM to
# EVERY altfs process on the machine, so the script refuses to run while a
# volume that it did not mount itself is mounted.
#
# Exit status: 0 if no check failed, 1 otherwise.

set -u

DEB_DIR="" ; OLD_DEB_DIR="" ; EXPECT="" ; PREFIX="" ; SYSTEM=1 ; DEVICE="" ; ERASE=0
BIG_SIZE="2G" ; BLOCKSIZE="" ; MNT="/mnt/altfs-rc" ; SKIP_INSTALL=0 ; SKIP_LOGROTATE=0 ; KEEP=0

while [ $# -gt 0 ]; do
	case "$1" in
		--deb-dir)        DEB_DIR="$2"; shift 2 ;;
		--old-deb-dir)    OLD_DEB_DIR="$2"; shift 2 ;;
		--expect-version) EXPECT="$2"; shift 2 ;;
		--device)         DEVICE="$2"; shift 2 ;;
		--erase-tape)     ERASE=1; shift ;;
		--big-size)       BIG_SIZE="$2"; shift 2 ;;
		--blocksize)      BLOCKSIZE="$2"; shift 2 ;;
		--mnt)            MNT="$2"; shift 2 ;;
		--skip-install)   SKIP_INSTALL=1; shift ;;
		--prefix)         PREFIX="$2"; shift 2 ;;
		--skip-logrotate) SKIP_LOGROTATE=1; shift ;;
		--keep)           KEEP=1; shift ;;
		-h|--help)        sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
		*) echo "unknown option: $1" >&2; exit 2 ;;
	esac
done

if [ -n "$PREFIX" ]; then
	[ -x "$PREFIX/bin/altfs" ] || { echo "$PREFIX/bin/altfs not found" >&2; exit 2; }
	export PATH="$PREFIX/bin:$PATH" LD_LIBRARY_PATH="$PREFIX/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
	SKIP_INSTALL=1; SYSTEM=0
fi

WORK="$(mktemp -d /var/tmp/altfs-host-check.XXXXXX)"
REPORT="$WORK/report.txt"
ALTFS_LOG=/var/log/altfs.log
SYSLOG=/var/log/syslog
[ -f "$SYSLOG" ] || SYSLOG=/var/log/messages
PASS=0 ; FAIL=0 ; WARN=0

say()  { echo "$*" | tee -a "$REPORT"; }
hdr()  { say ""; say "=== $*"; }
pass() { PASS=$((PASS+1)); say "  PASS  $*"; }
fail() { FAIL=$((FAIL+1)); say "  FAIL  $*"; }
warn() { WARN=$((WARN+1)); say "  WARN  $*"; }
info() { say "  ....  $*"; }
# check "description" command...   (PASS when the command succeeds)
check() { local d="$1"; shift; if "$@" >>"$WORK/cmd.log" 2>&1; then pass "$d"; else fail "$d"; fi; }

ltfs_mounts()  { LC_ALL=C awk '$1 ~ /^ltfs:/ && $3 ~ /^fuse/ { print $2 }' /proc/mounts; }
altfs_procs()  { pgrep -x altfs | tr '\n' ' '; }
wait_unmounted() {  # wait_unmounted DIR SECONDS
	local i=0
	while mountpoint -q "$1" || pgrep -x altfs >/dev/null; do
		i=$((i+1)); [ "$i" -gt "$2" ] && return 1; sleep 1
	done
}
wait_mounted() { local i=0; until mountpoint -q "$1"; do i=$((i+1)); [ "$i" -gt "$2" ] && return 1; sleep 1; done; }
elapsed() { echo $(( $(date +%s) - $1 )); }
# Read an extended attribute without getfattr (the attr package is not
# installed by default); os.getxattr() is in the Python standard library.
xattr_get() { python3 -c 'import os,sys; print(os.getxattr(sys.argv[1], sys.argv[2]).decode())' "$1" "user.$2" 2>/dev/null; }

cleanup() {
	mountpoint -q "$MNT" && { umount "$MNT"; wait_unmounted "$MNT" 900; }
	systemctl is-active -q altfs.service 2>/dev/null || systemctl start altfs.service 2>/dev/null
	if [ "$KEEP" -eq 1 ] || [ "$FAIL" -gt 0 ]; then
		echo; echo "Work directory kept: $WORK (report: $REPORT)"
	else
		cp "$REPORT" "/var/tmp/altfs-host-check-report-$(date +%Y%m%d-%H%M%S).txt"
		rm -rf "$WORK"
	fi
}
trap cleanup EXIT

# ---------------------------------------------------------------- preflight
hdr "Preflight"
# HC_DRYRUN=1 lets the --prefix mode without --device run as a normal user
# (the scenario tests use it to keep this script working)
if [ "$(id -u)" -ne 0 ] && ! { [ "${HC_DRYRUN:-0}" = 1 ] && [ "$SYSTEM" -eq 0 ] && [ -z "$DEVICE" ]; }; then
	echo "run as root (real drives need CAP_SYS_RAWIO, packages need root)" >&2; exit 2
fi
if [ "$SYSTEM" -eq 1 ]; then
	[ -d /run/systemd/system ] || { echo "systemd is not running here" >&2; exit 2; }
	command -v apt-get >/dev/null || { echo "this script is for Debian / Ubuntu" >&2; exit 2; }
fi
if [ -n "$(ltfs_mounts)" ]; then
	echo "LTFS volumes are mounted: $(ltfs_mounts | tr '\n' ' ')" >&2
	echo "this script stops altfs.service, which unmounts ALL of them. Unmount first." >&2
	exit 2
fi
if [ -d "$MNT" ] && ! mountpoint -q "$MNT" && [ -n "$(ls -A "$MNT" 2>/dev/null)" ]; then
	echo "mount point $MNT is not empty (left over from an earlier run?). Empty it first." >&2
	exit 2
fi
if [ -n "$DEVICE" ] && [ "$ERASE" -ne 1 ]; then
	echo "--device needs --erase-tape: the tape phase formats the cartridge" >&2; exit 2
fi
if [ "$SKIP_INSTALL" -eq 0 ]; then
	[ -n "$DEB_DIR" ] && ls "$DEB_DIR"/altfs_*.deb "$DEB_DIR"/libaltfs0_*.deb >/dev/null 2>&1 \
		|| { echo "--deb-dir must contain altfs_*.deb and libaltfs0_*.deb" >&2; exit 2; }
fi
info "host: $(. /etc/os-release; echo "$PRETTY_NAME"), kernel $(uname -r), $(systemctl --version | head -1)"
info "rsyslog: $(systemctl is-active rsyslog.service 2>/dev/null)   work dir: $WORK"
RSYSLOG_BEFORE="$(systemctl show rsyslog.service -p ActiveEnterTimestampMonotonic --value 2>/dev/null)"

# ------------------------------------------------------------------ install
hdr "Package installation"
if [ "$SYSTEM" -eq 0 ]; then
	info "skipped (--prefix $PREFIX: testing that build, not the installed packages)"
elif [ "$SKIP_INSTALL" -eq 1 ]; then
	info "skipped (--skip-install)"
else
	export DEBIAN_FRONTEND=noninteractive
	if [ -n "$OLD_DEB_DIR" ]; then
		if dpkg -s altfs >/dev/null 2>&1; then
			warn "altfs is already installed ($(dpkg-query -W -f='${Version}' altfs)); --old-deb-dir ignored"
		else
			check "install the old packages from $OLD_DEB_DIR" \
				apt-get install -y "$OLD_DEB_DIR"/libaltfs0_*.deb "$OLD_DEB_DIR"/altfs_*.deb
			info "old version: $(dpkg-query -W -f='${Version}' altfs)   altfs.service: $(systemctl is-enabled altfs.service 2>&1 | head -1)"
		fi
	fi
	info "before: $(dpkg-query -W -f='${Version}' altfs 2>/dev/null || echo 'not installed')"
	check "install / upgrade to the packages" \
		apt-get install -y "$DEB_DIR"/libaltfs0_*.deb "$DEB_DIR"/altfs_*.deb
fi

VER="$(altfs -V 2>&1 | head -3 | tr '\n' ' ')"
info "altfs -V: $VER"
if [ -n "$EXPECT" ]; then
	case "$VER" in *"$EXPECT"*) pass "version is $EXPECT" ;; *) fail "version is not $EXPECT" ;; esac
fi
if [ "$SYSTEM" -eq 1 ]; then
check "altfs.service is enabled"            systemctl is-enabled -q altfs.service
check "altfs.service is active"             systemctl is-active -q altfs.service
check "unit file installed"                 test -f /usr/lib/systemd/system/altfs.service
check "helper script installed"             test -x /usr/share/altfs/altfs
check "rsyslog rule installed"              test -f /etc/rsyslog.d/30-altfs.conf
check "logrotate config installed"          test -f /etc/logrotate.d/altfs
check "systemd accepts the unit"            systemd-analyze verify --man=no /usr/lib/systemd/system/altfs.service
if systemctl is-active -q rsyslog.service; then
	check "rsyslog accepts its configuration" rsyslogd -N1
	RSYSLOG_AFTER="$(systemctl show rsyslog.service -p ActiveEnterTimestampMonotonic --value)"
	if [ "$RSYSLOG_BEFORE" != "$RSYSLOG_AFTER" ]; then
		pass "rsyslog was restarted by the package installation"
	else
		info "rsyslog was not restarted (expected unless this was a first install or an upgrade from 1.0.0)"
	fi
else
	warn "rsyslog is not active: the log routing checks below will fail or be meaningless"
fi
fi  # SYSTEM

# ------------------------------------------------------- file backend volume
hdr "File backend volume: logging, xattrs, altfs_ordered_copy"
FTAPE="$WORK/filetape"; mkdir -p "$FTAPE" "$MNT" "$WORK/src"
MARK="host-check-$$-$(date +%s)"
mkaltfs -e file -d "$FTAPE" -s RCCHK0 -n "$MARK" -f > "$WORK/mkaltfs.log" 2>&1 \
	&& pass "mkaltfs (file backend)" || fail "mkaltfs (file backend), see $WORK/mkaltfs.log"
# Not necessarily the first line: without a usable LANG the commands print a
# hardcoded locale warning ("LTFS9015W ...") before the catalogs are loaded.
if grep -q '^AMK0001I ' "$WORK/mkaltfs.log" && ! grep -Eq '^LTFSA[A-Z]{2}[0-9]' "$WORK/mkaltfs.log"; then
	pass "log lines start with the bare message ID (AMK0001I ...)"
else
	fail "log lines do not start with the bare message ID, see $WORK/mkaltfs.log"
fi

mount_file() { altfs -o tape_backend=file -o devname="$FTAPE" "$MNT" >>"$WORK/cmd.log" 2>&1 && wait_mounted "$MNT" 30; }
check "mount"  mount_file
echo "payload $MARK" > "$MNT/check.txt"
sleep 2

if systemctl is-active -q rsyslog.service && [ -f /etc/rsyslog.d/30-altfs.conf ]; then
	grep -q "$FTAPE" "$ALTFS_LOG" 2>/dev/null \
		&& pass "messages of this mount are in $ALTFS_LOG" || fail "messages of this mount are NOT in $ALTFS_LOG"
	grep "$FTAPE" "$ALTFS_LOG" 2>/dev/null | tail -1 | grep -Eq '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.]+[+-][0-9]{2}:[0-9]{2} ' \
		&& pass "RFC 3339 timestamps in $ALTFS_LOG" || fail "timestamp format in $ALTFS_LOG"
	grep "$FTAPE" "$ALTFS_LOG" 2>/dev/null | tail -1 | grep -Eq ' altfs(\[[0-9]+\])?: [0-9a-f]+ A[A-Z]{2}[0-9A-Z]{4}[EWID] ' \
		&& pass "log line format: '<tid> <ID> text', no LTFS prefix" || fail "log line format in $ALTFS_LOG"
	grep -q "$FTAPE" "$SYSLOG" 2>/dev/null \
		&& fail "messages of this mount ALSO appear in $SYSLOG (stop rule not effective)" \
		|| pass "messages of this mount are not in $SYSLOG"
	info "sample: $(grep "$FTAPE" "$ALTFS_LOG" | tail -1 | cut -c1-150)"
fi
journalctl -t altfs --since "-5min" --no-pager 2>/dev/null | grep -q "$FTAPE" \
	&& pass "messages are still in the journal" || warn "messages of this mount not found in the journal"

PROD="$(xattr_get "$MNT" ltfs.softwareProduct)"
[ "$PROD" = "Aurora LTFS" ] && pass "ltfs.softwareProduct = 'Aurora LTFS'" || fail "ltfs.softwareProduct = '$PROD'"
info "ltfs.softwareVersion = $(xattr_get "$MNT" ltfs.softwareVersion)"

echo a > "$WORK/src/a"; echo b > "$WORK/src/b"
if python3 -c 'import xattr' 2>/dev/null; then
	# No "| grep -q": it exits at the first match and the copy dies of SIGPIPE.
	altfs_ordered_copy "$WORK/src/a" "$WORK/src/b" "$MNT/" > "$WORK/ordered_copy.log" 2>&1
	grep -q 'is LTFS' "$WORK/ordered_copy.log" \
		&& pass "altfs_ordered_copy recognizes the mount as LTFS" || fail "altfs_ordered_copy did not report 'is LTFS'"
else
	warn "python3 module 'xattr' is missing: altfs_ordered_copy cannot run (install python3-pyxattr or python3-xattr)"
fi

# ----------------------------------------------- package upgrade while mounted
hdr "Package reinstall while a volume is mounted"
if [ "$SYSTEM" -eq 0 ] || [ "$SKIP_INSTALL" -eq 1 ]; then
	info "skipped (no packages to reinstall)"
else
	apt-get install -y --reinstall "$DEB_DIR"/altfs_*.deb >>"$WORK/cmd.log" 2>&1
	if mountpoint -q "$MNT" && [ -f "$MNT/check.txt" ]; then
		pass "the volume is still mounted after reinstalling the package"
	else
		fail "the volume was unmounted by the package reinstall"
		mount_file
	fi
fi

# ------------------------------------------------ altfs.service stop (file)
if [ "$SYSTEM" -eq 1 ]; then
	hdr "systemctl stop altfs.service with the file backend volume mounted"
	T0=$(date +%s)
	check "systemctl stop altfs.service" systemctl stop altfs.service
	info "stop took $(elapsed "$T0") s"
	mountpoint -q "$MNT" && fail "volume is still mounted after the stop" || pass "volume is unmounted"
	[ -z "$(altfs_procs)" ] && pass "no altfs process left" || fail "altfs processes left: $(altfs_procs)"
	check "systemctl start altfs.service" systemctl start altfs.service
else
	hdr "Unmount with the file backend volume mounted (altfs.service belongs to the packages)"
	echo "payload $MARK" > "$MNT/check.txt"
fi
mountpoint -q "$MNT" && { umount "$MNT"; wait_unmounted "$MNT" 60; }
check "remount" mount_file
grep -q "$MARK" "$MNT/check.txt" 2>/dev/null \
	&& pass "file written before the stop is there after remount (index was written)" \
	|| fail "file written before the stop is missing after remount"
umount "$MNT"; wait_unmounted "$MNT" 60 || fail "unmount of the file backend volume timed out"

# ---------------------------------------------------------------- logrotate
hdr "logrotate"
if [ "$SYSTEM" -eq 0 ] || [ "$SKIP_LOGROTATE" -eq 1 ] || ! systemctl is-active -q rsyslog.service; then
	info "skipped"
else
	# Only rotate our file, but with the global options (su, create ...) of the
	# system configuration, and without touching the system's state file.
	{ grep -Ev '^\s*include\b' /etc/logrotate.conf; echo "include /etc/logrotate.d/altfs"; } > "$WORK/logrotate.conf"
	check "logrotate -f (altfs.log only)" logrotate -f -s "$WORK/logrotate.state" "$WORK/logrotate.conf"
	compgen -G '/var/log/altfs.log?*' >/dev/null \
		&& pass "rotated file exists: $(ls /var/log/altfs.log?* | tr '\n' ' ')" || fail "no rotated altfs.log found"
	logger -t altfs "AFS0000I host-check after rotation $MARK"; sleep 2
	grep -q "after rotation $MARK" "$ALTFS_LOG" 2>/dev/null \
		&& pass "rsyslog writes to the new $ALTFS_LOG after the rotation" \
		|| fail "message logged after the rotation is not in $ALTFS_LOG"
fi

# --------------------------------------------------------------- real tape
if [ -n "$DEVICE" ]; then
	hdr "Real drive: $DEVICE   (THE CARTRIDGE WILL BE ERASED)"
	altfs -o device_list 2>&1 | grep -i 'Device Name' | tee -a "$REPORT"
	TLOG="$WORK/tape.log"
	mount_tape() { altfs -o devname="$DEVICE" "$MNT" >>"$TLOG" 2>&1 && wait_mounted "$MNT" 600; }
	umount_tape() { T0=$(date +%s); umount "$MNT" && wait_unmounted "$MNT" 900; }

	T0=$(date +%s); check "mkaltfs${BLOCKSIZE:+ -b $BLOCKSIZE}" mkaltfs -d "$DEVICE" -s RCCHK1 -n "host-check" ${BLOCKSIZE:+-b "$BLOCKSIZE"} -f; info "mkaltfs took $(elapsed "$T0") s"
	T0=$(date +%s)
	if mount_tape; then
		pass "mount"; info "mount took $(elapsed "$T0") s"
	else
		fail "mount (took $(elapsed "$T0") s); tape phase aborted, see $TLOG"
		grep -E '[0-9]E |ATG0001I|ATG0086I' "$TLOG" | head -8 | sed 's/^/        /' | tee -a "$REPORT"
		DEVICE="" ; TAPE_ABORTED=1
	fi
fi
if [ -n "$DEVICE" ]; then
	mkdir -p "$MNT/small"
	for i in $(seq 1 200); do head -c 4096 /dev/urandom > "$MNT/small/f$i"; done
	head -c "$BIG_SIZE" /dev/urandom > "$WORK/big.bin"
	T0=$(date +%s); check "copy a $BIG_SIZE file to the tape" cp "$WORK/big.bin" "$MNT/"; info "copy took $(elapsed "$T0") s"
	( cd "$MNT" && find . -type f -exec sha256sum {} + | sort -k2 ) > "$WORK/tape.sha256"
	info "files on tape: $(wc -l < "$WORK/tape.sha256")   indexGeneration: $(xattr_get "$MNT" ltfs.indexGeneration)"

	check "unmount" umount_tape; info "unmount (index write) took $(elapsed "$T0") s"

	: > "$TLOG"
	T0=$(date +%s); check "remount" mount_tape; info "remount took $(elapsed "$T0") s"
	grep -q 'ALB0028I' "$TLOG" \
		&& fail "remount ran a full medium consistency check (ALB0028I): VCR / VCI inconsistent" \
		|| pass "remount without a full medium consistency check"
	( cd "$MNT" && sha256sum -c --quiet "$WORK/tape.sha256" ) >>"$WORK/cmd.log" 2>&1 \
		&& pass "all checksums match after remount" || fail "checksum mismatch after remount"

	echo "written before systemctl stop $MARK" > "$MNT/before-stop.txt"
	T0=$(date +%s)
	if [ "$SYSTEM" -eq 1 ]; then
		check "systemctl stop altfs.service with the tape mounted" systemctl stop altfs.service
		info "stop took $(elapsed "$T0") s (TimeoutStopSec is 660 s)"
		mountpoint -q "$MNT" && fail "tape is still mounted after the stop" || pass "tape is unmounted"
		[ -z "$(altfs_procs)" ] && pass "no altfs process left" || fail "altfs processes left: $(altfs_procs)"
		systemctl start altfs.service
	else
		check "unmount" umount_tape; info "unmount took $(elapsed "$T0") s"
	fi

	: > "$TLOG"
	check "mount after the stop" mount_tape
	grep -q 'ALB0028I' "$TLOG" \
		&& fail "consistency check after the stop: the unmount was not clean" \
		|| pass "clean volume after the stop"
	grep -q "$MARK" "$MNT/before-stop.txt" 2>/dev/null \
		&& pass "file written before the stop is on the tape" || fail "file written before the stop is missing"
	check "unmount" umount_tape

	altfsck "$DEVICE" > "$WORK/altfsck.log" 2>&1
	RC=$?; info "altfsck exit status: $RC   last line: $(tail -1 "$WORK/altfsck.log" | cut -c1-120)"
	# altfsck always runs a full consistency check and updates the MAM
	# coherency data, so a consistent volume ends with ACK0019I and exit
	# status 1 (LTFSCK_CORRECTED), not 0.
	if [ "$RC" -le 1 ] && grep -q 'ACK0019I' "$WORK/altfsck.log"; then
		pass "altfsck reports a consistent volume (ACK0019I, exit $RC)"
	else
		fail "altfsck exit status $RC (log: $WORK/altfsck.log)"
	fi
elif [ -z "${TAPE_ABORTED:-}" ]; then
	hdr "Real drive"
	info "skipped (no --device). Example: --device <serial from 'altfs -o device_list'> --erase-tape"
fi

# ------------------------------------------------------------------ summary
hdr "Summary"
say "  $PASS passed, $FAIL failed, $WARN warnings"
say "  Not covered here: a reboot with a volume mounted (do it by hand from a root console / ssh session)."
[ "$FAIL" -eq 0 ]
