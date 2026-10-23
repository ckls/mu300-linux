#!/usr/bin/env python3
"""Run both repositories' TTL engine against isolated firewall/config commands."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

TOP = Path(__file__).resolve().parents[2]
APP = TOP / 'openwrt' / ('luci-app-t551m' if (TOP/'devices/e5').exists() else 'luci-app-mu300')
ENGINE = APP/'root/usr/libexec/unisoc-modem/ttl-engine'


class Ttl(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bin = self.root/'bin'; self.bin.mkdir()
        self.store = self.root/'firewall.json'
        self.store.write_text(json.dumps({'flow_offloading':'1','flow_offloading_hw':'1'}))
        self.conf = self.root/'etc/ttl.conf'
        self.env = dict(os.environ, PATH=str(self.bin)+':'+os.environ['PATH'],
                        MU300_TTL_CONF=str(self.conf), MU300_TTL_LOCK=str(self.root/'lock'),
                        TEST_TTL_ROOT=str(self.root))
        self.stub('uci', '''import sys,json,os
from pathlib import Path
r=Path(os.environ['TEST_TTL_ROOT']); p=r/'firewall.json'; d=json.loads(p.read_text())
a=sys.argv[1:]
if a[0]=='-q': a=a[1:]
if a[0]=='get': print(d.get(a[1].split('.')[-1],''))
elif a[0]=='set':
 if (r/'uci.fail').exists(): sys.exit(1)
 k,v=a[1].split('=');d[k.split('.')[-1]]=v;p.write_text(json.dumps(d))
''')
        self.stub('fw4', '''import os,sys
from pathlib import Path
r=Path(os.environ['TEST_TTL_ROOT'])
with (r/'reloads').open('a') as f:f.write('reload\\n')
sys.exit(1 if (r/'reload.fail').exists() else 0)
''')
        self.stub('nft', '''import os,sys,time
from pathlib import Path
r=Path(os.environ['TEST_TTL_ROOT']);a=sys.argv[1:];p=r/'rules'
if a[0]=='list': sys.exit(0 if p.exists() else 1)
if a[0]=='delete':p.unlink(missing_ok=True)
if a[0]=='-f':
 data=sys.stdin.read()
 if (r/'nft.fail').exists():sys.exit(1)
 if (r/'delay').exists():time.sleep(.2)
 p.write_text(data)
''')

    def stub(self, name, code):
        p=self.bin/name;p.write_text('#!/usr/bin/env python3\n'+code);p.chmod(0o755)

    def call(self, *args, ok=True):
        r=subprocess.run(['sh',str(ENGINE),*args],env=self.env,text=True,capture_output=True,timeout=10)
        if ok:self.assertEqual(r.returncode,0,r.stderr)
        else:self.assertNotEqual(r.returncode,0)
        return r

    def test_ipv4_ipv6_only_cellular_and_restore_both_offload_flags(self):
        self.call('set','65')
        rules=(self.root/'rules').read_text()
        self.assertIn('ip ttl set 65',rules);self.assertIn('ip6 hoplimit set 65',rules)
        self.assertEqual(rules.count('oifname "sipa_eth*"'),2)
        self.assertNotIn('flush ruleset',rules)
        self.assertEqual(json.loads(self.store.read_text()),{'flow_offloading':'0','flow_offloading_hw':'0'})
        self.call('off')
        self.assertEqual(json.loads(self.store.read_text()),{'flow_offloading':'1','flow_offloading_hw':'1'})
        self.assertFalse(self.conf.exists());self.assertFalse((self.root/'rules').exists())

    def test_invalid_values_do_not_change_settings(self):
        for v in ('','0','01','256','-1','1; reboot','1\n2','1.5','999999999999'):
            self.call('set',v,ok=False)
        self.assertFalse(self.conf.exists());self.assertFalse((self.root/'reloads').exists())

    def test_preserves_user_disabled_offload(self):
        self.store.write_text(json.dumps({'flow_offloading':'0','flow_offloading_hw':'0'}))
        self.call('set','64');self.call('apply');self.call('off')
        self.assertEqual(json.loads(self.store.read_text()),{'flow_offloading':'0','flow_offloading_hw':'0'})
        self.assertFalse((self.root/'reloads').exists())

    def test_failed_atomic_rule_keeps_previous_value_and_can_retry(self):
        self.call('set','64');before=(self.root/'rules').read_text()
        (self.root/'nft.fail').touch();self.call('set','128',ok=False)
        self.assertEqual(self.conf.read_text(),'TTL=64\n');self.assertEqual((self.root/'rules').read_text(),before)
        (self.root/'nft.fail').unlink();self.call('set','128')
        self.assertEqual(self.conf.read_text(),'TTL=128\n')

    def test_reload_failure_is_reported_and_retried_even_after_uci_changed(self):
        (self.root/'reload.fail').touch();self.call('set','64',ok=False)
        self.assertFalse(self.conf.exists());self.assertFalse((self.root/'rules').exists())
        (self.root/'reload.fail').unlink();self.call('set','64')
        self.assertEqual((self.root/'reloads').read_text().count('reload'),2)
        self.call('off')
        self.assertEqual(json.loads(self.store.read_text())['flow_offloading'],'1')

    def test_uci_failure_never_claims_success(self):
        (self.root/'uci.fail').touch();self.call('set','64',ok=False)
        self.assertFalse(self.conf.exists());self.assertFalse((self.root/'rules').exists())

    def test_process_restart_reapplies_saved_rule(self):
        self.call('set','128');(self.root/'rules').unlink()
        self.call('apply');self.assertIn('ttl set 128',(self.root/'rules').read_text())
        self.assertIn('TTL=128\nBACKEND=nft',self.call('state').stdout)

    def test_default_off_does_not_touch_firewall(self):
        self.call('apply');self.call('state')
        self.assertFalse((self.root/'rules').exists());self.assertFalse((self.root/'reloads').exists())

    def test_parallel_requests_are_serialized(self):
        (self.root/'delay').touch()
        procs=[subprocess.Popen(['sh',str(ENGINE),'set',v],env=self.env,stdout=subprocess.PIPE,stderr=subprocess.PIPE) for v in ('64','128')]
        codes=[]
        for p in procs:
            out,err=p.communicate(timeout=10);codes.append(p.returncode)
        self.assertEqual(sorted(codes),[0,75])
        v=self.conf.read_text().strip().split('=')[1]
        self.assertIn('ttl set '+v,(self.root/'rules').read_text())
        self.call('off');self.assertEqual(json.loads(self.store.read_text())['flow_offloading'],'1')


if __name__=='__main__':unittest.main()
