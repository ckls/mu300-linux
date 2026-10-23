"""Single owner and clean takeover with the real ARM64 key event helper."""
import os
import shutil
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from helpers import BIN, ucode, ucode_paths
from test_modemd import wait_for
KEYS=os.environ.get('MU300_TEST_KEYS','')
@unittest.skipUnless(KEYS and Path('/tmp/event-test-ready').exists() and ucode(),'explicit isolated container and verified helper required')
class SystemRuntime(unittest.TestCase):
    def setUp(self):
        self.tmp=Path(tempfile.mkdtemp(prefix='sysd-runtime-'));self.procs=[]
        root=self.tmp/'root';(root/'run/mu300').mkdir(parents=True)
        (root/'run/mu300/device').write_text('f50\n')
        (root/'proc').mkdir();(root/'proc/uptime').symlink_to('/proc/uptime')
        commands=self.tmp/'bin';commands.mkdir()
        for name,body in [('mu300-device','echo f50'),('mu300-led','exit 0')]:
            p=commands/name;p.write_text('#!/bin/sh\n'+body+'\n');p.chmod(0o755)
        self.root=root
        self.env=dict(os.environ,MU300_SYSROOT=str(root),MU300_RUN=str(self.tmp/'run'),MU300_BIN=str(commands),MU300_KEYS_BIN=KEYS,PATH=str(commands)+':'+os.environ['PATH'])
        self.owner=self.tmp/'run/mu300/sysd.lock/pid'

    def tearDown(self):
        for p in reversed(self.procs):
            if p.poll() is None:p.terminate();p.wait(5)
            if os.environ.get('MU300_TEST_VERBOSE') and p.stderr: print(p.stderr.read())
            if p.stdout:p.stdout.close()
            if p.stderr:p.stderr.close()
        shutil.rmtree(self.tmp)

    def start(self,*args):
        p=subprocess.Popen(ucode()+ucode_paths()[2:]+[str(BIN/'mu300-sysd')]+list(args),env=self.env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        self.procs.append(p);return p

    def helper_pid(self,pid):
        children=Path(f'/proc/{pid}/task/{pid}/children').read_text().split()
        for child in children:
            try: text=Path(f'/proc/{child}/cmdline').read_bytes()
            except FileNotFoundError:continue
            if KEYS.encode() in text:return int(child)
        return None

    def test_preflight_single_owner_exit_and_stale_record_takeover(self):
        check=self.start('--check');self.assertEqual(check.wait(5),0,check.stderr.read())
        first=self.start();self.assertTrue(wait_for(self.owner.exists))
        self.assertEqual(int(self.owner.read_text()),first.pid)
        child=wait_for(lambda:self.helper_pid(first.pid));self.assertTrue(child)
        second=self.start();self.assertEqual(second.wait(5),0,second.stderr.read())
        self.assertEqual(int(self.owner.read_text()),first.pid)
        self.assertEqual(self.helper_pid(first.pid),child)
        first.send_signal(signal.SIGTERM);self.assertEqual(first.wait(5),0)
        self.assertFalse(self.owner.exists())
        def stopped():
            try:return Path(f'/proc/{child}/stat').read_text().split(') ',1)[1][0]=='Z'
            except FileNotFoundError:return True
        self.assertTrue(wait_for(stopped))
        # A killed earlier daemon cannot leave permanent ownership behind.
        self.owner.parent.mkdir(parents=True,exist_ok=True);self.owner.write_text('999999999\n')
        third=self.start();self.assertTrue(wait_for(lambda:self.owner.exists() and self.owner.read_text().strip()==str(third.pid)))
        self.assertTrue(wait_for(lambda:self.helper_pid(third.pid)))

    def test_thermal_timer_repeats_without_restarting_key_owner(self):
        zone=self.root/'sys/class/thermal/thermal_zone0';zone.mkdir(parents=True)
        (zone/'temp').write_text('70000\n')
        daemon=self.start();self.assertTrue(wait_for(self.owner.exists))
        child=wait_for(lambda:self.helper_pid(daemon.pid));self.assertTrue(child)
        time.sleep(.3)
        (zone/'temp').write_text('90000\n')
        alarm=self.root/'run/mu300/thermal-alarm'
        self.assertTrue(wait_for(alarm.exists,timeout=8))
        self.assertIsNone(daemon.poll())
        self.assertEqual(self.helper_pid(daemon.pid),child)
        (zone/'temp').write_text('70000\n')
        self.assertTrue(wait_for(lambda:not alarm.exists(),timeout=8))
        self.assertEqual(self.helper_pid(daemon.pid),child)
