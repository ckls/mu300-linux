"""Real rpcd plugin and a single native frontend route."""
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

class RatesRouting(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'),'Node required')
    def test_native_route_and_explicit_failure(self):
        p=subprocess.run(['node',str(TOP/'tests/dashboard_resident_rates.js')],capture_output=True,text=True,timeout=10)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def test_only_fixed_read_method_is_exposed(self):
        acl=json.loads((ROOT/'usr/share/rpcd/acl.d/luci-app-mu300.json').read_text())['luci-app-mu300']
        self.assertEqual(acl['read']['ubus']['mu300rates'],['rates'])
        self.assertNotIn('mu300rates',acl['write']['ubus'])
        plugin=(ROOT/'usr/share/rpcd/ucode/mu300rates.uc').read_text()
        self.assertNotIn('args:',plugin)
        self.assertIn('+rpcd-mod-ucode',(TOP/'openwrt/luci-app-mu300/Makefile').read_text())
        for name in ['openwrt/luci-app-mu300/Makefile','openwrt/build-rootfs.sh']:
            self.assertIn('chmod 0644',(TOP/name).read_text())
            self.assertIn('/usr/share/rpcd/ucode/*.uc',(TOP/name).read_text())

@unittest.skipUnless(Path('/tmp/event-test-ready').exists() and Path('/sbin/rpcd').exists(),'explicit disposable OpenWrt container required')
class RealRpcd(unittest.TestCase):
    def test_real_uci_wan_selection_and_counter_fixtures(self):
        config=Path('/etc/config/unisoc_modem');saved=config.read_bytes() if config.exists() else None
        try:
            for script in ['dashboard_rates.uc','dashboard_backport.uc']:
                p=subprocess.run(['ucode',str(TOP/'tests'/script),str(TOP)],env=dict(os.environ,MU300_TEST_CONTAINER='1'),capture_output=True,text=True,timeout=20)
                self.assertEqual(p.returncode,0,p.stdout+p.stderr)
                self.assertIn('checks passed',p.stdout)
        finally:
            if saved is None:config.unlink(missing_ok=True)
            else:config.write_bytes(saved)

    def test_resident_plugin_and_compatibility_entry_agree(self):
        with tempfile.TemporaryDirectory(prefix='rates-rpcd-') as td:
            self.socket=str(Path(td)/'bus');procs=[];links=[]
            config=Path('/etc/config/unisoc_modem');saved=config.read_bytes() if config.exists() else None
            try:
                for name in ['usr/share/ucode/mu300/rates.uc','usr/share/rpcd/ucode/mu300rates.uc']:
                    target=Path('/')/name
                    self.assertFalse(target.exists(),f'refuse to overwrite {target}')
                    target.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copyfile(ROOT/name,target);target.chmod(0o644);links.append(target)
                config.parent.mkdir(parents=True,exist_ok=True)
                config.write_text("config core 'main'\n option data_device 'lo'\n")
                bus=subprocess.Popen(['/sbin/ubusd','-s',self.socket],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);procs.append(bus)
                self.assertTrue(wait_for(lambda:Path(self.socket).exists()))
                log=open(Path(td)/'rpcd.log','w+')
                rpcd=subprocess.Popen(['/sbin/rpcd','-s',self.socket],stdout=log,stderr=log);procs.append(rpcd)
                loaded=wait_for(lambda:self.request('list','mu300rates').returncode==0)
                log.seek(0);diagnostics=log.read();log.close()
                self.assertTrue(loaded,diagnostics)
                for _ in range(3):
                    p=self.request('call','mu300rates','rates','{}');self.assertEqual(p.returncode,0,p.stderr)
                    native=json.loads(p.stdout)
                    self.assertTrue(native['available']);self.assertEqual(native['device'],'lo')
                    self.assertIsInstance(native['rx'],int);self.assertGreater(native['ts'],0)
                old=subprocess.run(['ucode',str(ROOT/'usr/libexec/unisoc-modem/dashboard-rates')],capture_output=True,text=True,timeout=5)
                self.assertEqual(old.returncode,0,old.stderr)
                legacy=json.loads(old.stdout)
                for field in ['available','device','ifindex','boot_id']:
                    self.assertEqual(native[field],legacy[field])
                config.write_text("config core 'main'\n option data_device '../etc/passwd'\n")
                bad=json.loads(self.request('call','mu300rates','rates','{}').stdout)
                self.assertFalse(bad['available'])
                self.assertIsNone(rpcd.poll())
            finally:
                for proc in reversed(procs):
                    proc.terminate();proc.wait(5)
                for link in links:link.unlink()
                if saved is None:config.unlink(missing_ok=True)
                else:config.write_bytes(saved)

    def request(self,*args):
        return subprocess.run(['/bin/ubus','-s',self.socket,*args],capture_output=True,text=True,timeout=5)
