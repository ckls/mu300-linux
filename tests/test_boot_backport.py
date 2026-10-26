"""Boot ordering and readiness checks with private command/file fixtures only."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from helpers import TOP, BIN, ShellTest, ucode

class HardwareOrdering(ShellTest):
    def setUp(self):
        super().setUp()
        for name in ['led-status','extra-modules','zram-start','wifi-start','regdb-load','openwrt-wifi-config','mu300-nfc']:
            self.stub(name,'echo "'+name+'" >> "$STUBLOG/order"\nexit 0')
        self.stub('openwrt-board-check','echo board-check >> "$STUBLOG/order"; exit "${BOARD_FAIL:-0}"')
        self.stub('wifi-ready','exit "${READY_FAIL:-0}"')
        self.stub('uci','echo CN')
        self.stub('iw','echo "iw:$*" >> "$STUBLOG/order"; echo "country CN:"')
        self.stub('wifi','echo "wifi:$*" >> "$STUBLOG/order"')
        self.stub('sha256sum','echo "${CONFIG_HASH:-same}"')
        source=(TOP/'openwrt/overlay/etc/init.d/mu300-hw').read_text()
        source=source.replace('/tmp/mu300-',str(self.tmp)+'/mu300-').replace('/opt/mu300/bin/',str(self.stubs)+'/')
        source=source.replace('sha256sum ',str(self.stubs/'sha256sum')+' ')
        self.code=source+'\nhw_bringup\n'

    def test_rules_precede_phy_and_ready_ap_is_not_restarted(self):
        for shell in self.each_shell():
            (self.tmp/'order').unlink(missing_ok=True)
            r=self.sh(shell,self.code);self.assertEqual(r.returncode,0,r.stderr)
            events=(self.tmp/'order').read_text().splitlines()
            self.assertLess(events.index('board-check'),events.index('wifi-start'))
            self.assertLess(events.index('regdb-load'),events.index('wifi-start'))
            self.assertLess(events.index('wifi-start'),events.index('extra-modules'))
            self.assertNotIn('wifi:down',events);self.assertNotIn('wifi:up',events)

    def test_unready_ap_reconciles_once_and_invalid_board_stops_bringup(self):
        for shell in self.each_shell():
            for fail in [0,1]:
                (self.tmp/'order').unlink(missing_ok=True)
                r=self.sh(shell,self.code,READY_FAIL=1,BOARD_FAIL=fail)
                events=(self.tmp/'order').read_text().splitlines()
                if fail:self.assertNotEqual(r.returncode,0);self.assertNotIn('wifi-start',events)
                else:self.assertEqual(events.count('wifi:down'),1);self.assertEqual(events.count('wifi:up'),1)

class WirelessReadiness(unittest.TestCase):
    def test_all_enabled_interfaces_and_user_disabled_radio(self):
        from native_dashboard_fixture import Snapshot
        cmd=ucode()
        if not cmd:self.skipTest('ucode required')
        with tempfile.TemporaryDirectory() as td:
            s=Snapshot(td)
            source=(BIN/'wifi-ready').read_text().replace("from 'ubus'","from './bus.uc'")
            source=source.replace('cursor()','cursor(getenv("MU300_DASH_CONFIG"))')
            script=s.module/'wifi-ready';script.write_text(source)
            def run():
                (s.root/'rpc.json').write_text(json.dumps(s.responses))
                return subprocess.run(cmd+[str(script)],env=dict(os.environ,MU300_DASH_CONFIG=str(s.config),DASH_FIXTURE=td),capture_output=True,text=True,timeout=5)
            self.assertEqual(run().returncode,0)
            s.responses['hostapd.wlan0.get_status']={'status':'DISABLED'};self.assertEqual(run().returncode,1)
            s.responses['network.wireless.status']['radio0']['pending']=True;self.assertEqual(run().returncode,1)
            (s.config/'wireless').write_text("config wifi-device 'radio0'\n option disabled '1'\n")
            self.assertEqual(run().returncode,0,'a disabled radio must stay disabled without a global restart')

class BootContracts(unittest.TestCase):
    def test_device_entrypoints_have_unix_line_endings(self):
        for name in ['boot/init','openwrt/build-rootfs.sh',
                     'openwrt/overlay/lib/preinit/04_mu300_early_leds',
                     'openwrt/overlay/etc/init.d/mu300-hw',
                     'openwrt/overlay/etc/init.d/mu300-service-cpus',
                     'rootfs/overlay/opt/mu300/bin/mu300-led',
                     'rootfs/overlay/opt/mu300/bin/mu300-modemd',
                     'rootfs/overlay/opt/mu300/bin/mu300-service-cpus',
                     'rootfs/overlay/opt/mu300/bin/wifi-ready',
                     'rootfs/overlay/opt/mu300/bin/sipa-dele-start']:
            self.assertNotIn(b'\r\n',(TOP/name).read_bytes(),name)

    def test_recovery_and_full_resume_wait_are_retained(self):
        init=(TOP/'boot/init').read_text()
        self.assertNotIn('.kmodloader-once',init)
        self.assertIn('head -c 1 /dev/random',init)
        self.assertIn('echo 4 > /proc/sys/kernel/printk',init)
        driver=(TOP/'upstream/port/drivers/pci/controller/dwc/pcie-sprd.c').read_text()
        probe=driver[driver.index('static int sprd_pcie_probe('):]
        self.assertIn('sprd_pcie_link_up_soon(pci)',probe)
        self.assertIn('dw_pcie_wait_for_link(pci)',driver[:driver.index('static int sprd_pcie_probe(')])
        self.assertIn('sprd_pcie_clear_unhandled_msi',driver)
        self.assertFalse((TOP/'openwrt/overlay/lib/preinit/31_mu300_failsafe_wait').exists())

class EarlyLeds(ShellTest):
    def test_preinit_lights_before_usb_or_recorder_without_a_usb_interface(self):
        hooks=TOP/'openwrt/overlay/lib/preinit'
        self.assertLess('04_mu300_early_leds','05_mu300_early_recorder')
        for name in ('led-status','bootmark'):
            self.stub(name,'echo "'+name+' $*" >> "$STUBLOG/calls"')
        source=(hooks/'04_mu300_early_leds').read_text().replace('/opt/mu300/bin/',str(self.stubs)+'/')
        code='''boot_hook_add() { printf '%s %s' "$1" "$2"; }
'''+source+'\nmu300_early_leds\n'
        for shell in self.each_shell():
            (self.tmp/'calls').write_text('')
            result=self.sh(shell,code)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(result.stdout,'preinit_essential mu300_early_leds')
            self.assertEqual((self.tmp/'calls').read_text().splitlines(),
                             ['led-status boot','bootmark early-leds'])
        self.assertNotIn('led-status boot',(hooks/'06_mu300_early_usb').read_text())

class DelegateReadiness(ShellTest):
    def setUp(self):
        super().setUp()
        (self.tmp/'modules').mkdir();(self.tmp/'modules/sipa-dele.ko').write_text('test file only')
        (self.tmp/'loaded-modules').write_text('');(self.tmp/'tty').touch()
        node=self.tmp/'sysfs'/'cp';node.mkdir(parents=True)
        (node/'sipa_dele_wait').write_text('1\n')
        (node/'sipa_dele_ready').write_text('1\n')
        self.stub('dmesg','echo unexpected >> "$STUBLOG/dmesg-calls"; exit 99')
        self.stub('uci',"case \"$*\" in *sim_slots) echo 2;; *data_sim) echo 0;; *) exit 1;; esac")
        self.stub('mu300-at',"""[ "$MU300_AT_DAEMON_ONLY" = 1 ] || exit 99
printf '%s %s\n' "$MU300_AT_DIR" "$*" >> "$STUBLOG/at-calls"
case "$MU300_AT_DIR:$*" in
 /run/mu300-at:*'AT+SPACTCARD=0;+CGATT?'|/run/mu300-at4:*'AT+SPACTCARD=1;+CGATT?') ;;
 *) exit 98;;
esac
printf '+CGATT: %s\\n' "${ATTACHED:-1}"
""")
        self.stub('cat',"""case "$1" in
 */sipa_dele_wait)
  echo wait >> "$STUBLOG/gate-calls"
  [ "${GATE_FAIL:-0}" = 0 ] || exit 1
  ;;
esac
exec /bin/cat "$@"
""")
        self.stub('insmod','echo load >> "$STUBLOG/loads"; exit "${LOAD_FAIL:-0}"')
        self.stub('sleep','echo "$1" >> "$STUBLOG/sleeps"; echo "1.0 0" > "$STUBLOG/uptime"')
        source=(BIN/'sipa-dele-start').read_text()
        source=source.replace('/lib/modules/$(uname -r)',str(self.tmp/'modules'))
        source=source.replace('/proc/modules',str(self.tmp/'loaded-modules')).replace('/proc/uptime',str(self.tmp/'uptime'))
        source=source.replace('/dev/stty_nr1',str(self.tmp/'tty')).replace('[ -c ','[ -f ')
        for command in ['mu300-at','insmod','dmesg','sleep','cat']:
            source=source.replace(command+' ',str(self.stubs/command)+' ')
        source=source.replace('${MU300_SIM_ENV_LIB:-/opt/mu300/bin/mu300-sim-env}',str(BIN/'mu300-sim-env'))
        source=source.replace('${MU300_DELE_SYSFS:-/sys/bus/platform/drivers/sipa_delegate}',str(self.tmp/'sysfs'))
        self.code=source

    def run_delegate(self,shell,**env):
        for name in ['loads','sleeps','at-calls','gate-calls','dmesg-calls']:(self.tmp/name).unlink(missing_ok=True)
        (self.tmp/'uptime').write_text('0.0 0')
        return self.sh(shell,self.code,MU300_DELE_WAIT=1,**env)

    def test_packet_attach_and_handshake_finish_without_fixed_delay(self):
        for shell in self.each_shell():
            p=self.run_delegate(shell)
            self.assertEqual(p.returncode,0,p.stderr)
            self.assertEqual((self.tmp/'loads').read_text().splitlines(),['load'])
            self.assertFalse((self.tmp/'sleeps').exists())
            self.assertFalse((self.tmp/'dmesg-calls').exists())
            self.assertEqual((self.tmp/'gate-calls').read_text().splitlines(),['wait'])

    def test_no_packet_attach_never_loads_and_load_failure_is_not_success(self):
        for shell in self.each_shell():
            p=self.run_delegate(shell,ATTACHED=0)
            self.assertNotEqual(p.returncode,0);self.assertFalse((self.tmp/'loads').exists())
            p=self.run_delegate(shell,LOAD_FAIL=1)
            self.assertNotEqual(p.returncode,0);self.assertNotIn('channel and resource callbacks ready',p.stdout)

    def test_sim2_attach_uses_sim2_owner_and_explicit_scope(self):
        for shell in self.each_shell():
            p=self.run_delegate(shell,MU300_SIM_SLOT=1)
            self.assertEqual(p.returncode,0,p.stderr)
            self.assertIn('/run/mu300-at4', (self.tmp/'at-calls').read_text())
            self.assertIn('AT+SPACTCARD=1;+CGATT?',(self.tmp/'at-calls').read_text())
            self.assertNotIn('SPACTCARD=0',(self.tmp/'at-calls').read_text())

    def test_failed_or_missing_handshake_is_not_success(self):
        for shell in self.each_shell():
            p=self.run_delegate(shell,GATE_FAIL=1)
            self.assertNotEqual(p.returncode,0)
            self.assertIn('handshake not ready',p.stdout)
            node=self.tmp/'sysfs/cp/sipa_dele_wait'
            node.rename(node.with_suffix('.saved'))
            p=self.run_delegate(shell)
            self.assertNotEqual(p.returncode,0)
            self.assertIn('matching delegate module required',p.stdout)
            node.with_suffix('.saved').rename(node)

    def test_loaded_module_still_requires_handshake_but_no_more_at(self):
        for shell in self.each_shell():
            (self.tmp/'loaded-modules').write_text('sipa_dele 123 0\n')
            for fail in (0,1):
                p=self.run_delegate(shell,GATE_FAIL=fail)
                self.assertEqual(p.returncode==0,fail==0,p.stderr)
                self.assertFalse((self.tmp/'loads').exists())
                self.assertFalse((self.tmp/'at-calls').exists())
            (self.tmp/'loaded-modules').write_text('')

    def test_invalid_handshake_value_is_not_success(self):
        for shell in self.each_shell():
            node=self.tmp/'sysfs/cp/sipa_dele_wait'
            for value in ('0\n','2\n','-19\n',''):
                node.write_text(value)
                self.assertNotEqual(self.run_delegate(shell).returncode,0)
            node.write_text('1\n')
