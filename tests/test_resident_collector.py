"""Compatibility RPC delegates to native collectors, with no worker fallback."""
import json
from helpers import ShellTest, TOP
RPC=TOP/'openwrt/luci-app-mu300/root/usr/libexec/rpcd/mu300dash'

class ResidentCollector(ShellTest):
    def setUp(self):
        super().setUp()
        source=RPC.read_text();self.helper=source[source.index('m_status() {'):source.index('m_act() {')]
        self.stub('ubus', 'printf "%s\\n" "$*" > "$STUBLOG/request"; [ "$FAIL" != 1 ] || exit 1; printf "%s\\n" "$REPLY"')
        self.stub('setsid','touch "$STUBLOG/worker"')

    def test_status_cells_and_signal_keep_selected_sim(self):
        for shell in self.each_shell():
            for slot in ['0','1']:
                for operation,target in [('m_status','mu300status status'),('m_status cells','mu300status cells'),('m_signal','mu300.modem signal')]:
                    p=self.sh(shell,self.helper+'\n'+operation,MU300_SIM_SLOT=slot,REPLY='{"fixture":true}')
                    self.assertEqual(p.returncode,0,p.stderr);self.assertEqual(json.loads(p.stdout),{'fixture':True})
                    request=(self.tmp/'request').read_text();self.assertIn(target,request);self.assertIn('"slot":"'+slot+'"',request)
                    self.assertFalse((self.tmp/'worker').exists())

    def test_native_failure_is_reported_without_starting_an_old_worker(self):
        for shell in self.each_shell():
            for operation in ['m_status','m_signal']:
                p=self.sh(shell,self.helper+'\n'+operation,FAIL=1)
                self.assertNotEqual(p.returncode,0);self.assertIn('error',json.loads(p.stdout));self.assertFalse((self.tmp/'worker').exists())
