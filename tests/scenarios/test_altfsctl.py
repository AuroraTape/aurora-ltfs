"""altfsctl: setting up altfs@<serial>.service instances (issue #105).

altfsctl normally runs as root against /etc. Here the test hooks point it
at a temporary configuration directory and fuse.conf, at a fake systemctl
that logs its calls, and at the current user / group in place of the
"altfs" user and the "tape" group. Nothing is mounted: starting an
instance is systemd's job and is checked on a real system.
"""

import grp
import os
import pwd
import shutil
import subprocess

import pytest

ALTFSCTL = shutil.which("altfsctl")
pytestmark = pytest.mark.skipif(ALTFSCTL is None, reason="altfsctl is installed on Linux only")


class Env:
    def __init__(self, tmp_path, active="inactive", enabled="disabled"):
        self.root = tmp_path
        self.confdir = tmp_path / "etc"
        self.fuse_conf = tmp_path / "fuse.conf"
        self.device = tmp_path / "drive"
        self.device.write_text("")
        self.log = tmp_path / "systemctl.log"
        systemctl = tmp_path / "systemctl"
        systemctl.write_text(
            "#!/bin/sh\n"
            f"echo \"$@\" >> {self.log}\n"
            "case \"$1\" in\n"
            f"  is-active) echo {active}; [ {active} = active ] ;;\n"
            f"  is-enabled) echo {enabled}; [ {enabled} = enabled ] ;;\n"
            "esac\n")
        systemctl.chmod(0o755)
        self.env = dict(os.environ,
                        ALTFSCTL_CONFDIR=str(self.confdir),
                        ALTFSCTL_FUSE_CONF=str(self.fuse_conf),
                        ALTFSCTL_SYSTEMCTL=str(systemctl),
                        ALTFSCTL_USER=pwd.getpwuid(os.getuid()).pw_name,
                        ALTFSCTL_TAPE_GROUP=grp.getgrgid(os.getgid()).gr_name,
                        ALTFSCTL_TEST="1")

    def run(self, *args):
        return subprocess.run([ALTFSCTL, *args], env=self.env, capture_output=True,
                              text=True, timeout=30)

    def add(self, serial="DRV001", mnt=None, *extra):
        mnt = mnt or str(self.root / "mnt")
        return self.run("add", serial, mnt, "--device", str(self.device), *extra)

    def conf(self, serial="DRV001"):
        return (self.confdir / f"{serial}.conf").read_text()

    def systemctl_calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []


@pytest.fixture
def env(tmp_path):
    e = Env(tmp_path)
    e.fuse_conf.write_text("user_allow_other\n")
    return e


def test_check_reports_missing_user_allow_other(tmp_path):
    e = Env(tmp_path)
    e.fuse_conf.write_text("# mount_max = 1000\n")
    r = e.run("check")
    assert r.returncode == 1
    assert "FAIL  user_allow_other is not set" in r.stdout
    assert "--fix-fuse-conf" in r.stdout
    assert e.fuse_conf.read_text() == "# mount_max = 1000\n"   # left alone


def test_fix_fuse_conf_uncomments_the_line(tmp_path):
    e = Env(tmp_path)
    e.fuse_conf.write_text("# mount_max = 1000\n#user_allow_other\n")
    r = e.run("check", "--fix-fuse-conf")
    assert r.returncode == 0, r.stdout + r.stderr
    assert e.fuse_conf.read_text() == "# mount_max = 1000\nuser_allow_other\n"


def test_fix_fuse_conf_appends_the_line(tmp_path):
    e = Env(tmp_path)
    r = e.run("check", "--fix-fuse-conf")       # no fuse.conf at all
    assert r.returncode == 0, r.stdout + r.stderr
    assert e.fuse_conf.read_text() == "user_allow_other\n"


def test_add_writes_the_instance_settings(env):
    group = grp.getgrgid(os.getgid())
    r = env.add("DRV001", None, "--gid", group.gr_name, "--umask", "007",
                "-o", "sync_type=unmount", "--enable")
    assert r.returncode == 0, r.stdout + r.stderr
    mnt = env.root / "mnt"
    assert mnt.is_dir() and mnt.stat().st_uid == os.getuid()
    conf = env.conf()
    assert f'MOUNTPOINT="{mnt}"' in conf
    assert (f'OPTIONS="-o wait_medium -o gid={group.gr_gid} -o umask=007 '
            '-o sync_type=unmount"') in conf
    assert f'DEVICE="{env.device}"' in conf
    assert env.systemctl_calls() == ["enable altfs@DRV001.service"]
    assert "systemctl start altfs@DRV001.service" in r.stdout


def test_add_without_wait_medium(env):
    r = env.add("DRV001", None, "--no-wait-medium")
    assert r.returncode == 0, r.stdout + r.stderr
    assert 'OPTIONS=""' in env.conf()
    assert env.systemctl_calls() == []          # not enabled unless asked


def test_add_changes_nothing_when_the_check_fails(tmp_path):
    e = Env(tmp_path)                           # no user_allow_other
    r = e.add()
    assert r.returncode == 1
    assert "nothing was changed" in r.stderr
    assert not e.confdir.exists()
    assert not (tmp_path / "mnt").exists()


@pytest.mark.parametrize("serial, mnt, extra, message", [
    ("bad/serial", "/tmp/x", [], "cannot be used as an instance name"),
    ("DRV001\n", "/tmp/x", [], "cannot be used as an instance name"),
    ("DRV001", "/tmp/a\nOPTIONS=x", [], "control characters"),
    ("DRV001", None, ["--umask", "007\n"], "octal mode"),
    ("DRV001", "relative/mnt", [], "absolute path"),
    ("DRV001", None, ["--umask", "8"], "octal mode"),
    ("DRV001", None, ["--gid", "no-such-group-105"], "does not exist"),
    ("DRV001", None, ["-o", "a b"], "white space"),
])
def test_add_rejects_bad_arguments(env, serial, mnt, extra, message):
    r = env.add(serial, mnt, *extra)
    assert r.returncode == 1
    assert message in r.stderr
    assert not env.confdir.exists()


def test_add_refuses_a_non_empty_mount_point(env):
    mnt = env.root / "mnt"
    mnt.mkdir()
    (mnt / "file").write_text("x")
    r = env.add()
    assert r.returncode == 1
    assert "is not empty" in r.stderr
    assert not env.confdir.exists()


def test_add_keeps_existing_settings_unless_forced(env):
    assert env.add().returncode == 0
    r = env.add("DRV001", None, "--no-wait-medium")
    assert r.returncode == 1
    assert "--force" in r.stderr
    assert "wait_medium" in env.conf()
    r = env.add("DRV001", None, "--no-wait-medium", "--force")
    assert r.returncode == 0, r.stdout + r.stderr
    assert 'OPTIONS=""' in env.conf()


def test_mount_point_with_quotes_and_spaces_round_trips(env):
    mnt = env.root / 'my "tape" dir'
    assert env.add("DRV001", str(mnt)).returncode == 0
    assert '\\"tape\\"' in env.conf()
    r = env.run("list")
    assert r.returncode == 0
    assert r.stdout.splitlines()[1].endswith(str(mnt))


def test_list(env):
    assert "No instances are set up" in env.run("list").stdout
    assert env.add("DRV001").returncode == 0
    assert env.add("DRV002", str(env.root / "mnt2")).returncode == 0
    lines = env.run("list").stdout.splitlines()
    assert lines[0].split() == ["SERIAL", "ENABLED", "ACTIVE", "MOUNTPOINT"]
    assert lines[1].split() == ["DRV001", "disabled", "inactive", str(env.root / "mnt")]
    assert lines[2].split() == ["DRV002", "disabled", "inactive", str(env.root / "mnt2")]


def test_remove_refuses_a_running_instance(tmp_path):
    e = Env(tmp_path, active="active", enabled="enabled")
    e.fuse_conf.write_text("user_allow_other\n")
    assert e.add().returncode == 0
    r = e.run("remove", "DRV001")
    assert r.returncode == 1
    assert "systemctl stop altfs@DRV001.service" in r.stderr
    assert (e.confdir / "DRV001.conf").exists()
    assert "disable altfs@DRV001.service" not in e.systemctl_calls()


def test_remove_disables_and_keeps_the_mount_point(tmp_path):
    e = Env(tmp_path, enabled="enabled")
    e.fuse_conf.write_text("user_allow_other\n")
    assert e.add().returncode == 0
    r = e.run("remove", "DRV001")
    assert r.returncode == 0, r.stdout + r.stderr
    assert not (e.confdir / "DRV001.conf").exists()
    assert "disable altfs@DRV001.service" in e.systemctl_calls()
    assert (tmp_path / "mnt").is_dir()
    assert "left in place" in r.stdout


def test_enable_needs_settings(env):
    r = env.run("enable", "DRV009")
    assert r.returncode == 1
    assert "is not set up" in r.stderr
    assert env.systemctl_calls() == []
    assert env.add("DRV009").returncode == 0
    assert env.run("enable", "DRV009").returncode == 0
    assert env.run("disable", "DRV009").returncode == 0
    assert env.systemctl_calls() == ["enable altfs@DRV009.service",
                                     "disable altfs@DRV009.service"]


def test_unit_template_matches_altfsctl():
    """The installed template reads the settings altfsctl writes."""
    unit = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(ALTFSCTL))),
                        "lib", "systemd", "system", "altfs@.service")
    if not os.path.exists(unit):
        pytest.skip("altfs@.service is installed elsewhere")
    text = open(unit).read()
    confdir = subprocess.run(["sed", "-n", 's/^SYSCONFDIR = "\\(.*\\)"$/\\1/p', ALTFSCTL],
                             capture_output=True, text=True).stdout.strip()
    assert f"EnvironmentFile={confdir}/altfs/%i.conf" in text
    for needle in ("Environment=DEVICE=%i", "-o devname=${DEVICE}", "$OPTIONS ${MOUNTPOINT}",
                   "User=altfs", "AmbientCapabilities=CAP_SYS_RAWIO", "After=",
                   "altfs.service", "Type=exec", "KillMode=mixed"):
        assert needle in text
    assert "NoNewPrivileges" not in text.replace("No NoNewPrivileges=", "")


def test_hooks_need_altfsctl_test(env):
    env.env.pop("ALTFSCTL_TEST")
    if os.geteuid() == 0:
        pytest.skip("runs as root")
    r = env.add()
    assert r.returncode == 1
    assert "has to be run as root" in r.stderr
    assert not env.confdir.exists()


def test_add_refuses_an_existing_directory_of_another_user(env):
    env.env["ALTFSCTL_USER"] = "root"
    if os.getuid() == 0:
        pytest.skip("runs as root")
    mnt = env.root / "mnt"
    mnt.mkdir()
    r = env.add()
    assert r.returncode == 1
    assert "does not belong to root" in r.stderr
    assert not env.confdir.exists()


def test_add_refuses_a_symbolic_link(env):
    (env.root / "real").mkdir()
    (env.root / "link").symlink_to(env.root / "real")
    r = env.add("DRV001", str(env.root / "link"))
    assert r.returncode == 1
    assert "symbolic link" in r.stderr


def test_fix_fuse_conf_waits_for_the_other_checks(tmp_path):
    e = Env(tmp_path)
    e.fuse_conf.write_text("#user_allow_other\n")
    e.device.unlink()                           # the device check fails
    r = e.add("DRV001", None, "--fix-fuse-conf")
    assert r.returncode == 1
    assert "added when the other checks pass" in r.stdout
    assert e.fuse_conf.read_text() == "#user_allow_other\n"
    assert not e.confdir.exists()
