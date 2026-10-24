"""Production sysd with private sensors/helpers; no real device access."""
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time
import unittest

TOP=Path(__file__).resolve().parents[1]
SYSD=TOP/'rootfs/overlay/opt/mu300/bin/mu300-sysd'


class Scheduling(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name)
        self.root=self.base/'root';self.bin=self.base/'bin';self.bin.mkdir()
        (self.root/'proc').mkdir(parents=True);(self.root/'proc/uptime').symlink_to('/proc/uptime')
        (self.root/'run/mu300').mkdir(parents=True)
        (self.root/'run/mu300/device').write_text('f50')
        self.stub('mu300-device','''#!/bin/sh
echo f50
''')
        self.stub('mu300-led','''#!/bin/sh
exit 0
''')
        self.env=dict(os.environ,MU300_SYSROOT=str(self.root),MU300_RUN=str(self.root/'run'),MU300_BIN=str(self.bin),PATH=str(self.bin)+':'+os.environ['PATH'])

    def tearDown(self):self.tmp.cleanup()

    def stub(self,name,source):
        p=self.bin/name;p.write_text(source);p.chmod(0o755);return p

    def zone(self,temp):
        p=self.root/'sys/class/thermal/thermal_zone0';p.mkdir(parents=True,exist_ok=True)
        (p/'temp').write_text(str(temp));(p/'trip_point_0_temp').write_text('85000')

    def round(self,temp,expected):
        self.zone(temp)
        p=subprocess.run(['ucode',str(SYSD),'--round'],env=self.env,capture_output=True,text=True,timeout=5)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn(f'next look in {expected} s',p.stderr)

    def test_adaptive_thermal_limits_alarm_and_read_error(self):
        self.round(45000,25);self.round(10000,30);self.round(84000,5)
        self.round(86000,5)
        (self.root/'run/mu300/thermal-alarm').unlink()
        (self.root/'sys/module/mu300_thermal').mkdir(parents=True)
        self.round(45000,10)  # No native binding: guard remains the policy owner.
        p=self.root/'sys/class/thermal/thermal_zone0/temp';p.write_text('unavailable')
        bad=subprocess.run(['ucode',str(SYSD),'--round'],env=self.env,capture_output=True,text=True,timeout=5)
        self.assertNotEqual(bad.returncode,0)

    def test_led_deadline_does_not_fork_every_five_seconds(self):
        helper=self.stub('keys','''#!/usr/bin/python3
import ctypes,time
ctypes.CDLL(None).prctl(1,15)  # Match the real helper's parent-death signal.
time.sleep(60)
''')
        self.stub('mu300-led','''#!/usr/bin/python3
import os,time
from pathlib import Path
root=Path(os.environ['MU300_SYSROOT'])
p=root/'run/mu300/led';p.mkdir(exist_ok=True)
with (root/'calls').open('a') as f:f.write('tick\\n')
now=int(float(Path('/proc/uptime').read_text().split()[0]))
(p/'.tick-hint').write_text('due '+str(now+600)+'\\nbattery -\\n')
''')
        env=dict(self.env,MU300_KEYS_BIN=str(helper),MU300_SYSD_PARTS='led')
        daemon=subprocess.Popen(['ucode',str(SYSD)],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        try:
            deadline=time.monotonic()+9
            while not (self.root/'calls').exists() and time.monotonic()<deadline:time.sleep(.05)
            self.assertTrue((self.root/'calls').exists())
            time.sleep(6)
            self.assertEqual((self.root/'calls').read_text().splitlines(),['tick'])
            self.assertIsNone(daemon.poll())
        finally:
            daemon.send_signal(signal.SIGTERM);daemon.communicate(timeout=5)

    def test_child_actions_do_not_inherit_relaxed_timer_slack(self):
        helper=self.stub('keys','''#!/usr/bin/python3
import time
print("116 short",flush=True)
time.sleep(.2)
''')
        self.stub('mu300-led','''#!/usr/bin/python3
import os
from pathlib import Path
Path(os.environ['SLACK_RESULT']).write_text(Path('/proc/self/timerslack_ns').read_text())
''')
        env=dict(self.env,MU300_SYSROOT='',MU300_KEYS_BIN=str(helper),MU300_SYSD_PARTS='keys',MU300_SYSD_ONCE='1',SLACK_RESULT=str(self.base/'slack'))
        p=subprocess.run(['ucode',str(SYSD)],env=env,capture_output=True,text=True,timeout=5)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertNotEqual(int((self.base/'slack').read_text()),500000000)


if __name__=='__main__':unittest.main()
