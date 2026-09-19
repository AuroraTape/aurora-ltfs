# Files in this directory

- 30-altfs.conf: rsyslog rule, installed as `SYSCONFDIR/rsyslog.d/30-altfs.conf`. Routes the
  messages of `altfs`, `mkaltfs`, `altfsck` and `altfsindextool` (matched by syslog program
  name) to `/var/log/altfs.log` with RFC 3339 timestamps and keeps them out of the system
  log (`stop`). The `30-` prefix matters: the file has to be read before the rules that
  write the system log (`50-default.conf` on Debian / Ubuntu).
- altfs.logrotate: logrotate config for `/var/log/altfs.log`, installed as
  `SYSCONFDIR/logrotate.d/altfs`.

  Both take effect when `SYSCONFDIR` is `/etc`, as in the deb / rpm packages, which also
  restart a running rsyslog when the rule is first installed. rsyslog is not a package
  dependency; without it the messages stay in the journal / system log as before.
- altfs.service.in: Template of the systemd unit for clean unmount at shutdown/reboot.
  `make` substitutes the location of the helper script (`$(datadir)/altfs/altfs`,
  installed from `init.d/`), and on Linux `make install` installs the unit into
  `--with-systemdsystemunitdir` (default `PREFIX/lib/systemd/system`). The deb and
  rpm packages enable it by default. With a prefix other than `/usr`, register it
  with `systemctl enable --now PREFIX/lib/systemd/system/altfs.service`

# syslog-ng

The packages support rsyslog only. With syslog-ng, an equivalent setup looks like the
following (untested example; `s_src` is the name of the system source in your
distribution's `syslog-ng.conf`, and `flags(final)` is the counterpart of rsyslog's
`stop`). Put it in `/etc/syslog-ng/conf.d/altfs.conf` and point the `postrotate` script of
`/etc/logrotate.d/altfs` at syslog-ng (`systemctl reload syslog-ng.service`).

```
filter f_altfs { program("^(altfs|mkaltfs|altfsck|altfsindextool)$"); };
destination d_altfs { file("/var/log/altfs.log" template("$ISODATE $HOST $MSGHDR$MSG\n")); };
log { source(s_src); filter(f_altfs); destination(d_altfs); flags(final); };
```
