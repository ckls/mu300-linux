"""Run the production ucode against private UMS9620/UMS9621 sysfs trees."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

TOP=Path(__file__).resolve().parents[1]
LIB=Path(os.environ.get('CPU_IDLE_TEST_LIB',str(TOP/'openwrt/luci-app-mu300/root/usr/libexec/unisoc-modem/cpu-idle.uc')))


class CpuIdle(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        p=self.root/'sys/firmware/devicetree/base';p.mkdir(parents=True)
        (p/'compatible').write_bytes(b'board,test\0sprd,ums9620\0')
        (self.root/'etc').mkdir()
        for cpu in (0,1):
            for index,name in enumerate(('WFI','core-sleep-lit','cluster-pd')):
                p=self.root/f'sys/devices/system/cpu/cpu{cpu}/cpuidle/state{index}';p.mkdir(parents=True)
                (p/'name').write_text(name);(p/'disable').write_text('1' if cpu==0 else '0')
        self.profile=self.root/'etc/unisoc-cpu-idle.json'
        self.env=dict(os.environ,UNISOC_IDLE_ROOT=str(self.root))

    def tearDown(self):self.tmp.cleanup()

    def call(self,action,request=None,**env):
        p=subprocess.run(['ucode',str(LIB),action],input=json.dumps(request or {}),
                         text=True,capture_output=True,env=dict(self.env,**env),timeout=5)
        self.assertTrue(p.stdout,p.stderr)
        return p.returncode,json.loads(p.stdout)

    def values(self):return [p.read_text().strip() for p in sorted(self.root.glob('sys/devices/system/cpu/cpu*/cpuidle/state*/disable'))]

    def test_get_and_absent_boot_never_change_state(self):
        before=self.values()
        self.assertTrue(self.call('get')[1]['supported'])
        self.assertFalse(self.call('get')[1]['enabled'])
        self.assertTrue(self.call('boot')[1]['skipped'])
        self.assertEqual(self.values(),before);self.assertFalse(self.profile.exists())

    def test_apply_persist_replay_and_only_cpu0_deep_states(self):
        code,result=self.call('apply',{'enabled':True,'ubus_rpc_session':'fixture'})
        self.assertEqual(code,0);self.assertTrue(result['enabled'])
        self.assertEqual(self.values(),['1','0','0','0','0','0'])
        self.assertEqual(json.loads(self.profile.read_text()),{'version':1,'enabled':True})
        self.assertEqual(self.profile.stat().st_mode&0o777,0o600)
        for p in self.root.glob('sys/devices/system/cpu/cpu0/cpuidle/state[12]/disable'):p.write_text('1')
        self.assertEqual(self.call('boot')[0],0)
        self.assertEqual(self.values(),['1','0','0','0','0','0'])
        self.assertFalse(self.call('apply',{'enabled':False})[1]['enabled'])
        self.assertEqual(self.values(),['1','1','1','0','0','0'])

    def test_ums9621_hidden_and_direct_write_rejected(self):
        (self.root/'sys/firmware/devicetree/base/compatible').write_bytes(b'sprd,ums9621\0')
        before=self.values()
        self.assertFalse(self.call('get')[1]['supported'])
        self.assertNotEqual(self.call('apply',{'enabled':True})[0],0)
        self.assertEqual(self.values(),before);self.assertFalse(self.profile.exists())

    def test_invalid_requests_and_profile_are_rejected_before_writes(self):
        before=self.values()
        for request in ({'enabled':1},{'enabled':'true'},{'enabled':True,'path':'arbitrary'},{}):
            self.assertNotEqual(self.call('apply',request)[0],0)
            self.assertEqual(self.values(),before)
        self.profile.write_text('{broken')
        self.assertNotEqual(self.call('apply',{'enabled':True})[0],0)
        self.assertEqual(self.values(),before)

    def test_save_failure_restores_exact_mixed_state(self):
        path=self.root/'sys/devices/system/cpu/cpu0/cpuidle/state1/disable';path.write_text('0')
        self.assertTrue(self.call('get')[1]['mixed'])
        before=self.values()
        code,result=self.call('apply',{'enabled':True},UNISOC_IDLE_CONFIG=str(self.root/'missing/profile.json'))
        self.assertNotEqual(code,0);self.assertTrue(result['rollback'])
        self.assertEqual(self.values(),before)


if __name__=='__main__':unittest.main()
