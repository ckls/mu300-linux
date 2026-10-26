"""U30-specific boot routing and the existing zero-based dashboard contract."""
import json
from pathlib import Path
from helpers import BIN, TOP, ShellTest

import test_data_sim as shared

class U30Adapter(ShellTest):
    def setUp(self):
        shared.DataSim.setUp(self)
        self.stub('mu300-device', 'echo u30air')
        self.extra['TEST_DSDS']='1'
        (self.tmp/'sim-radio-policy').write_text('1 1\n')
    reset = shared.DataSim.reset
    run_switch = shared.DataSim.run_switch

    def test_common_schema_and_ready_marker(self):
        self.reset()
        for shell in self.each_shell():
            r=self.script(shell,self.controller,'get',**self.extra)
            self.assertEqual(r.returncode,0,r.stderr)
            state=json.loads(r.stdout)
            self.assertTrue(state['ready']);self.assertNotIn('native',state)
            self.assertEqual(state['actual_sim'],0)
            (self.tmp/'ready').unlink()
            state=json.loads(self.script(shell,self.controller,'get',**self.extra).stdout)
            self.assertFalse(state['ready'])
            (self.tmp/'ready').touch()

    def test_no_data_does_not_undo_selection_or_change_rf(self):
        for shell in self.each_shell():
            self.reset(fail_target=True)
            result=self.run_switch(shell,'1')
            self.assertEqual(result.returncode,0,result.stderr)
            state=json.loads(self.db.read_text())
            self.assertEqual((state['actual'],state['saved']),(1,1))
            commands=(self.tmp/'commands').read_text()
            self.assertNotIn('SFUN=',commands);self.assertNotIn('enable-sim2',commands)
            self.assertEqual((self.tmp/'sim-radio-policy').read_text(),'1 1\n')

    def test_explicit_rf_off_requires_manual_enable_before_switch(self):
        for shell in self.each_shell():
            self.reset();(self.tmp/'sim-radio-policy').write_text('1 0\n')
            result=self.run_switch(shell,'1')
            self.assertNotEqual(result.returncode,0)
            self.assertIn('Enable the target SIM radio',result.stderr)
            self.assertNotIn('ifdown',(self.tmp/'commands').read_text())
            self.assertEqual((self.tmp/'sim-radio-policy').read_text(),'1 0\n')

    def test_single_standby_default_and_explicit_dual_standby_policies(self):
        policy=self.tmp/'sim-radio-policy'
        self.reset()
        for shell in self.each_shell():
            policy.unlink(missing_ok=True)
            self.assertEqual(self.script(shell,BIN/'mu300-radio-allowed','--flags').stdout.strip(),'1 0')
            for flags in ('0 0','0 1','1 0','1 1'):
                policy.write_text(flags+'\n')
                self.assertEqual(self.script(shell,BIN/'mu300-radio-allowed','--flags',TEST_DSDS='1').stdout.strip(),flags)
                self.assertEqual(self.script(shell,BIN/'mu300-radio-allowed','--flags',TEST_DSDS='0').stdout.strip(),'1 0' if flags=='1 1' else flags)

    def test_failed_route_or_storage_restores_old_selection(self):
        for shell in self.each_shell():
            for failure in ('fail_switch','fail_commit'):
                self.reset(**{failure:True})
                result=self.run_switch(shell,'1')
                self.assertNotEqual(result.returncode,0)
                state=json.loads(self.db.read_text())
                self.assertEqual((state['actual'],state['saved']),(0,0))

    def test_old_hot_boot_options_cannot_start_automatic_controller(self):
        for shell in self.each_shell():
            self.reset()
            for arg in ('u30-hot-1','u30-default-1','1;reboot'):
                result=self.run_switch(shell,arg)
                self.assertNotEqual(result.returncode,0)
                self.assertNotIn('ifdown',(self.tmp/'commands').read_text())

class U30Init(ShellTest):
    def setUp(self):
        super().setUp()
        self.run=self.tmp/'run'; (self.run/'mu300').mkdir(parents=True)
        self.etc=self.tmp/'etc';self.etc.mkdir()
        self.stub('uci', """case "$*" in
 '-q get unisoc_modem.main.data_sim') echo "${TEST_SLOT:-1}" ;;
 '-q get unisoc_modem.main.u30_sim_hot') echo "${TEST_HOT:-0}" ;;
 '-q get unisoc_modem.main.sim_slots') echo 2 ;;
 *) exit 1 ;;
esac""")
        self.stub('mu300-device', 'echo "${TEST_DEVICE:-u30air}"')
        self.init=self.tmp/'init'
        source=(TOP/'openwrt/overlay/etc/init.d/mu300-atd').read_text()
        source=source.replace('/run/',str(self.run)+'/').replace('/etc/',str(self.etc)+'/')
        source=source.replace('/opt/mu300/bin/mu300-device','mu300-device').replace('/opt/mu300/bin/mu300-platform-config','mu300-platform-config')
        self.stub('mu300-platform-config', ':')
        helper=(BIN.parent/'lib/modemd-service.sh').read_text()
        helper='modemd_require() { :; }\n'+helper[helper.index('MODEMD_BROKERS='):]
        helper=helper.replace('/opt/mu300/bin/mu300-device','mu300-device').replace('/run/',str(self.run)+'/')
        layout=self.tmp/'native-layout.sh';layout.write_text(helper)
        harness="""
procd_open_instance() { echo "instance $*"; }
procd_set_param() { echo "param $*"; }
procd_append_param() { echo "append $*"; }
procd_close_instance() { :; }
"""
        self.init.write_text(harness+source+'\nstart_service\n')
        self.extra=dict(MU300_MODEMD_SERVICE_LIB=layout)

    def test_all_old_hot_and_saved_choices_start_shared_dual_owners(self):
        for shell in self.each_shell():
            for slot in ('0','1'):
                for hot in ('0','1'):
                    r=self.script(shell,self.init,TEST_SLOT=slot,TEST_HOT=hot,**self.extra)
                    self.assertEqual(r.returncode,0,r.stderr)
                    self.assertNotIn('sim2-cold-start',r.stdout)
                    specs=[v for v in r.stdout.splitlines() if v.startswith('append command name=')]
                    self.assertEqual(len(specs),6,r.stdout)
                    for line,n in zip(specs,[1,2,4,5,6,7]):
                        self.assertIn(f'dev=/dev/stty_nr{n},',line)
                        self.assertIn('reopen=0,ready=sbuf:sbuf_5_006',line)
                    self.assertFalse((self.run/'mu300/sim-slot').exists())
                    self.assertFalse((self.run/'mu300-radio-freeze').exists())
                    self.assertFalse((self.etc/'mu300-sim-pending').exists())

    def test_f50_and_v50_keep_existing_native_layout(self):
        for shell in self.each_shell():
            for board in ('f50','v50'):
                r=self.script(shell,self.init,TEST_DEVICE=board,**self.extra)
                self.assertEqual(r.returncode,0,r.stderr)
                self.assertIn('instance atd-io',r.stdout)
                self.assertIn('instance modemd',r.stdout)
                self.assertIn('param respawn',r.stdout)

    def test_old_running_controller_requires_reboot_instead_of_reopening_tty(self):
        (self.run/'mu300/sim-slot').write_text('0\n')
        for shell in self.each_shell():
            r=self.script(shell,self.init,**self.extra)
            self.assertNotEqual(r.returncode,0)
            self.assertIn('reboot',r.stderr)
            self.assertNotIn('instance atd-io',r.stdout)

class U30RuntimePin(ShellTest):
    def test_both_boards_use_current_data_selection_not_obsolete_boot_pin(self):
        self.stub('mu300-device','echo "${TEST_DEVICE:-u30air}"')
        self.stub('uci','case "$3" in *.data_sim) echo 1;; *.sim_slots) echo 2;; esac')
        pin=self.tmp/'sim-slot';pin.write_text('0\n')
        envlib=self.tmp/'sim-env'
        envlib.write_text((BIN/'mu300-sim-env').read_text().replace('/run/mu300/sim-slot',str(pin)))
        for shell in self.each_shell():
            for board,expected in [('u30air','1'),('v50','1')]:
                r=self.sh(shell,f'. "{envlib}"; mu300_sim_env; echo "$MU300_SIM_SLOT"',MU300_DEVICE_CMD=self.stubs/'mu300-device',TEST_DEVICE=board)
                self.assertEqual(r.returncode,0,r.stderr)
                self.assertEqual(r.stdout.strip(),expected)

class U30ATGate(ShellTest):
    def test_native_sequence_and_unknown_radio_block_foreign_commands(self):
        run=self.tmp/'run'; (run/'mu300').mkdir(parents=True)
        client=self.tmp/'mu300-at'
        client.write_text((BIN/'mu300-at').read_text().replace('/run/',str(run)+'/'))
        for marker in ('sim-sequence','sim-active-unknown'):
            p=run/'mu300'/marker;p.touch()
            r=self.script(['bash'],client,'AT+CFUN?',MU300_AT_DIR=self.tmp/'no-broker')
            self.assertNotEqual(r.returncode,0);self.assertIn('busy',r.stderr)
            p.unlink()
        (run/'mu300/u30-native').touch()
        r=self.script(['bash'],client,'AT+CFUN?',MU300_AT_DIR=self.tmp/'no-broker')
        self.assertNotEqual(r.returncode,0);self.assertIn('direct tty fallback disabled',r.stderr)
