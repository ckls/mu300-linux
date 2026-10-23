"""Shared helpers for the tests: the shells the scripts run under, stub commands, a scratch directory.

The device scripts run under dash (Ubuntu's /bin/sh), bash and busybox ash (OpenWrt); every shell test runs under
each of them that this machine has (MU300_TEST_SHELLS="dash,busybox sh" picks others). Commands a script calls that
touch the device (nft, ip, id, ...) are replaced by stubs in a directory put first on PATH.
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

TOP = Path(__file__).resolve().parents[1]
BIN = TOP / 'rootfs' / 'overlay' / 'opt' / 'mu300' / 'bin'
GIT_CHECKOUT = bool(shutil.which('git')) and subprocess.run(
    ['git', '-C', str(TOP), 'rev-parse', '--git-dir'], capture_output=True).returncode == 0
UCODE_STUBS = TOP / 'tests/ucode-stubs'
UCODE_MODULES = TOP / 'openwrt/luci-app-mu300/root/usr/share/ucode'
UCODE_BASE_MODULES = TOP / 'rootfs/overlay/usr/share/ucode'


def ucode_paths():
    return ['-L', f'{UCODE_STUBS}/*.uc', '-L', f'{UCODE_MODULES}/*.uc',
            '-L', f'{UCODE_BASE_MODULES}/*.uc']


def ucode():
    """Use an explicitly selected interpreter, or the installed native one."""
    import shlex
    cmd = shlex.split(os.environ.get('MU300_TEST_UCODE', '')) or ([shutil.which('ucode')] if shutil.which('ucode') else [])
    if not cmd:
        return None
    try:
        if subprocess.run(cmd + ['-e', 'print(1)'], capture_output=True, timeout=10).returncode == 0:
            return cmd
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def is_ucode(path):
    try:
        with open(path, 'rb') as f:
            return f.readline().startswith(b'#!/usr/bin/ucode')
    except OSError:
        return False


def ucode_argv(path):
    cmd = ucode()
    return cmd + ucode_paths() + [str(path)] if cmd else None


def _works(argv):
    try:
        return subprocess.run(argv + ['-c', 'true'], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def shells():
    """[argv, ...] of the POSIX shells available here, e.g. [['dash'], ['bash'], ['busybox', 'sh']]."""
    names = os.environ.get('MU300_TEST_SHELLS', 'dash,bash,busybox sh,sh').split(',')
    found, seen = [], set()
    for n in names:
        argv = n.split()
        path = shutil.which(argv[0])
        if not path or not _works(argv):
            continue
        key = (os.path.realpath(path),) + tuple(argv[1:])
        if key not in seen:
            seen.add(key)
            found.append(argv)
    return found


class ShellTest(unittest.TestCase):
    """A scratch directory (self.tmp) with a stub directory first on PATH (self.stub)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='mu300-test-'))
        self.stubs = self.tmp / 'stubs'
        self.stubs.mkdir()
        self.shells = shells()
        if not self.shells:
            self.skipTest('no POSIX shell')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def stub(self, name, body):
        """A command NAME that runs BODY (sh); $STUBLOG is the scratch directory, for recording calls."""
        p = self.stubs / name
        p.write_text('#!/bin/sh\n' + body + '\n')
        p.chmod(0o755)

    def env(self, **extra):
        e = dict(os.environ)
        e['PATH'] = f'{self.stubs}{os.pathsep}{e.get("PATH", "")}'
        e['STUBLOG'] = str(self.tmp)
        e['MU300_RADIO_ALLOWED'] = str(BIN / 'mu300-radio-allowed')
        e['MU300_SMS_POOL_LIB'] = str(BIN.parent / 'lib/sms-pool.sh')
        e['UNISOC_RADIO_POLICY'] = str(self.tmp / 'sim-radio-policy')
        e['LC_ALL'] = 'C.UTF-8' if os.name != 'nt' else e.get('LC_ALL', '')
        e.update({k: str(v) for k, v in extra.items()})
        return e

    def sh(self, shell, code, stdin=None, **env):
        """Run CODE with SHELL; returns the CompletedProcess (text)."""
        return subprocess.run(shell + ['-c', code], input=stdin, capture_output=True, text=True,
                              env=self.env(**env), timeout=60)

    def script(self, shell, path, *args, stdin=None, **env):
        """Run the script at PATH with SHELL (not its #! line: the point is to try every shell)."""
        return subprocess.run(shell + [str(path)] + [str(a) for a in args], input=stdin, capture_output=True,
                              text=True, env=self.env(**env), timeout=60)

    def each_shell(self):
        for s in self.shells:
            with self.subTest(shell=' '.join(s)):
                try:
                    yield s
                except GeneratorExit:
                    # The caller's skip/failure remains the test outcome; closing
                    # the iterator must not produce a second subtest error.
                    return
