"""Load the actual native plugin in rpcd, not just an imported module."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from helpers import TOP
from test_modemd import wait_for

ROOT=TOP/'openwrt/luci-app-mu300/root'

@unittest.skipUnless(Path('/tmp/event-test-ready').exists(),'disposable OpenWrt container required')
class NativeRpcd(unittest.TestCase):
    def test_real_plugin_repeated_reads_and_scoped_sms(self):
        with tempfile.TemporaryDirectory(prefix='native-rpcd-') as td:
            procs=[];owned=[];saved={}
            try:
                for name in ['usr/share/ucode/mu300/dash.uc','usr/share/rpcd/ucode/mu300status.uc',
                             'usr/libexec/unisoc-modem/hotspot.uc','usr/libexec/unisoc-modem/apn.uc']:
                    target=Path('/')/name
                    # A previous test may already own a symlink into this same
                    # disposable fixture. Never replace installed unrelated code.
                    if target.exists():
                        self.assertEqual(target.resolve(),(ROOT/name).resolve());continue
                    target.parent.mkdir(parents=True,exist_ok=True)
                    if name.endswith('mu300status.uc'):
                        shutil.copyfile(ROOT/name,target);target.chmod(0o644)
                    else:target.symlink_to(ROOT/name)
                    owned.append(target)
                for name in ['unisoc_modem','network']:
                    target=Path('/etc/config')/name;saved[target]=target.read_bytes() if target.exists() else None
                Path('/etc/config/unisoc_modem').write_text("config core 'main'\n option sim_slots '2'\n")
                socket=str(Path(td)/'ubus.sock')
                procs.append(subprocess.Popen(['/sbin/ubusd','-s',socket]))
                self.assertTrue(wait_for(lambda:Path(socket).exists()))
                with open(Path(td)/'rpcd.log','w+') as log:
                    procs.append(subprocess.Popen(['/sbin/rpcd','-s',socket],stdout=log,stderr=log))
                    def request(*args):return subprocess.run(['/bin/ubus','-s',socket,*args],capture_output=True,text=True,timeout=8)
                    loaded=wait_for(lambda:request('list','mu300status').returncode==0)
                    log.seek(0);self.assertTrue(loaded,log.read())
                    for _ in range(3):
                        result=request('call','mu300status','sysinfo','{}');self.assertEqual(result.returncode,0,result.stderr)
                        snapshot=json.loads(result.stdout)
                        for key in ['cpu','mem','power','wifi','lan','boot','wan','net','traffic','vpn','conns']:
                            self.assertIn(key,snapshot)
                        self.assertGreater(snapshot['cpu']['total'],0)
                    for slot in ['0','1']:
                        result=request('call','mu300status','sms_head',json.dumps({'slot':slot}))
                        self.assertEqual(result.returncode,0,result.stderr)
                        self.assertIn('count',json.loads(result.stdout))
                    self.assertIn('error',json.loads(request('call','mu300status','sms_head','{"slot":"bad"}').stdout))
                    failed=json.loads(request('call','mu300status','cells','{"slot":"0"}').stdout)
                    self.assertIn('error',failed['cell'])
                    self.assertIsNone(procs[-1].poll())
            finally:
                for p in reversed(procs):p.terminate();p.wait(5)
                for p in owned:p.unlink(missing_ok=True)
                for path,value in saved.items():
                    if value is None:path.unlink(missing_ok=True)
                    else:path.write_bytes(value)
