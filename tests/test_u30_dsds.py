"""U30/F50 standby policy through the real RF controller and fake AT owner."""
import json
from helpers import ShellTest, TOP
import test_sim_radio as fixture


class U30Dsds(ShellTest):
    model = 'u30air'
    call = fixture.SimRadio.call

    def setUp(self):
        fixture.SimRadio.setUp(self)
        self.stub('mu300-device', 'echo "${TEST_MODEL:-'+self.model+'}"')
        self.stub('uci', '''
case "$2:$3" in
 get:*.dual_standby) cat "$STUBLOG/dsds" 2>/dev/null || :;;
 get:*.data_sim) echo "${DATA_SIM:-0}";;
 get:*.sim_slots) echo 2;;
 get:*.data_interface) echo wan;;
 set:*.dual_standby=*) [ "${FAIL_SAVE:-0}" != 1 ] || exit 1; echo "${3##*=}" > "$STUBLOG/dsds";;
 commit:*) :;;
 revert:*) :;;
esac''')
        self.stub('mobile-data', '''
case $1 in
 radio-policy) exec sh "$CONTROLLER" --locked "$2" "$3";;
 radio-dsds) exec sh "$CONTROLLER" --dsds-locked "$2";;
 radio-on) printf '[1,2]' > "$STUBLOG/state";;
 *) exit 2;;
esac''')
        # Every test starts at an ordinary single-SIM policy/runtime state.
        (self.tmp/'state').write_text('[1,2]')
        (self.tmp/'sim-radio-policy').write_text('1 0\n')

    def flags(self):
        return (self.tmp/'sim-radio-policy').read_text().strip()

    def test_default_and_legacy_both_on_keep_the_selected_card(self):
        for shell in self.each_shell():
            for saved, expected in [('0',[1,0]),('1',[0,1])]:
                for legacy in (False, True):
                    p=self.tmp/'sim-radio-policy';p.unlink(missing_ok=True)
                    if legacy:p.write_text('1 1\n')
                    r=self.call(shell,'get',DATA_SIM=saved)
                    self.assertEqual(r.returncode,0,r.stderr)
                    view=json.loads(r.stdout)
                    self.assertEqual(view['enabled'],expected)
                    self.assertTrue(view['dsds_supported'])
                    self.assertFalse(view['dsds_enabled'])
            self.assertFalse((self.tmp/'at').exists())

    def test_single_standby_turns_peer_off_before_target_on_in_both_directions(self):
        for shell in self.each_shell():
            for target in ('1','0'):
                (self.tmp/'at').unlink(missing_ok=True)
                r=self.call(shell,'apply',target,'1',SIM_POWERED='1')
                self.assertEqual(r.returncode,0,r.stderr)
                peer=1-int(target)
                writes=[s for s in (self.tmp/'at').read_text().splitlines() if 'SFUN=' in s]
                self.assertEqual(writes,[f'AT+SPACTCARD={peer};+SFUN=5',f'AT+SPACTCARD={target};+SFUN=4'])
                state=json.loads((self.tmp/'state').read_text())
                self.assertEqual(state[int(target)],1)
                self.assertIn(state[peer],[0,2])
                self.assertEqual(self.flags(),'0 1' if target=='1' else '1 0')

    def test_peer_close_failure_does_not_open_target(self):
        for shell in self.each_shell():
            (self.tmp/'at').unlink(missing_ok=True)
            r=self.call(shell,'apply','1','1',FAIL_RF='1')
            self.assertNotEqual(r.returncode,0)
            self.assertNotIn('SFUN=4',(self.tmp/'at').read_text())
            self.assertEqual(json.loads((self.tmp/'state').read_text()),[1,2])

    def test_enabling_mode_never_reactivates_a_legacy_both_on_policy(self):
        for shell in self.each_shell():
            (self.tmp/'dsds').unlink(missing_ok=True)
            (self.tmp/'sim-radio-policy').write_text('1 1\n')
            r=self.call(shell,'dsds','1',DATA_SIM='1')
            self.assertEqual(r.returncode,0,r.stderr)
            self.assertEqual(self.flags(),'0 1')
            self.assertFalse((self.tmp/'at').exists())

    def test_both_off_survive_mode_changes_and_enable_does_not_turn_radios_on(self):
        for shell in self.each_shell():
            (self.tmp/'state').write_text('[2,2]')
            (self.tmp/'sim-radio-policy').write_text('0 0\n')
            for enabled in ('1','0','1','0'):
                r=self.call(shell,'dsds',enabled)
                self.assertEqual(r.returncode,0,r.stderr)
                self.assertEqual(self.flags(),'0 0')
                self.assertEqual(json.loads((self.tmp/'state').read_text()),[2,2])
                self.assertEqual((self.tmp/'dsds').read_text().strip(),enabled)
                self.assertFalse((self.tmp/'gate').exists())

    def test_enabled_dsds_allows_both_and_disable_keeps_data_card(self):
        for shell in self.each_shell():
            (self.tmp/'dsds').write_text('1\n')
            (self.tmp/'state').write_text('[1,2]')
            (self.tmp/'sim-radio-policy').write_text('1 0\n')
            self.assertEqual(self.call(shell,'apply','1','1').returncode,0)
            self.assertEqual(self.flags(),'1 1')
            self.assertEqual(json.loads((self.tmp/'state').read_text()),[1,1])
            r=self.call(shell,'dsds','0',DATA_SIM='1')
            self.assertEqual(r.returncode,0,r.stderr)
            self.assertEqual(self.flags(),'0 1')
            self.assertEqual(json.loads((self.tmp/'state').read_text()),[2,1])

    def test_failed_disable_keeps_dsds_enabled(self):
        for shell in self.each_shell():
            (self.tmp/'dsds').write_text('1\n')
            (self.tmp/'sim-radio-policy').write_text('1 1\n')
            r=self.call(shell,'dsds','0',FAIL_RF='1')
            self.assertNotEqual(r.returncode,0)
            self.assertEqual((self.tmp/'dsds').read_text().strip(),'1')
            self.assertFalse((self.tmp/'gate').exists())

    def test_unsupported_model_rejects_without_at_or_policy_change(self):
        for shell in self.each_shell():
            for model in ('v50','unknown'):
                r=self.call(shell,'dsds','1',TEST_MODEL=model)
                self.assertNotEqual(r.returncode,0)
                self.assertIn('dsds_unsupported',r.stderr)
                self.assertFalse((self.tmp/'at').exists())
                self.assertFalse((self.tmp/'dsds').exists())
                self.assertFalse(json.loads(self.call(shell,'get',TEST_MODEL=model).stdout)['dsds_supported'])

    def test_busy_and_corrupt_saved_modes_send_no_at(self):
        for shell in self.each_shell():
            gate=self.tmp/'gate';gate.mkdir()
            self.assertNotEqual(self.call(shell,'dsds','1').returncode,0)
            gate.rmdir()
            (self.tmp/'dsds').write_text('invalid')
            self.assertNotEqual(self.call(shell,'apply','1','1').returncode,0)
            (self.tmp/'dsds').unlink()
            self.assertFalse((self.tmp/'at').exists())


class F50Dsds(U30Dsds):
    model = 'f50'
