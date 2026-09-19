# Files in this directory

- altfs-log.conf: Configuration for rsyslog
- altfslog: Configuration for syslog-ng
- altfs.service.in: Template of the systemd unit for clean unmount at shutdown/reboot.
  `make` substitutes the location of the helper script (`$(datadir)/altfs/altfs`,
  installed from `init.d/`), and on Linux `make install` installs the unit into
  `--with-systemdsystemunitdir` (default `PREFIX/lib/systemd/system`). The deb and
  rpm packages enable it by default. With a prefix other than `/usr`, register it
  with `systemctl enable --now PREFIX/lib/systemd/system/altfs.service`
