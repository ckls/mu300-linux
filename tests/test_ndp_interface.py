"""NDP uses the existing SIM mapper, including custom devices and switch gates."""
from helpers import TOP, BIN, ShellTest
from test_ipv6_prefix_routes import ROWS, B

LIB=TOP/'rootfs/overlay/opt/mu300/lib/ndp-interface.sh'
SCRIPT=TOP/'openwrt/overlay/opt/mu300/bin/ndp-learn'

class NdpInterface(ShellTest):
    def setUp(self):
        super().setUp();(self.tmp/'run/mu300').mkdir(parents=True)
        self.config=self.tmp/'config';self.config.write_text('initial\n')
        (self.tmp/'selected').write_text('0\n');(self.tmp/'custom').write_text('')
        self.stub('mu300-device','echo f50')
        self.stub('uci','''echo "$*" >> "$STUBLOG/lookups"
case "$*" in
    *main.data_sim) cat "$STUBLOG/selected" ;;
    *main.sim_slots) echo 2 ;;
    *main.sim0_device|*main.sim1_device) cat "$STUBLOG/custom" ;;
esac''')
        self.options=dict(MU300_NDP_RUN=self.tmp/'run',MU300_NDP_CONFIG=self.config,MU300_NDP_SIM_ENV=BIN/'mu300-sim-env',MU300_DEVICE_CMD=self.stubs/'mu300-device',MU300_NDP_INTERFACE_LIB=LIB)

    def test_cache_avoids_repeated_configuration_processes_and_applies_changes(self):
        for shell in self.each_shell():
            self.config.write_text('initial\n');(self.tmp/'selected').write_text('0\n')
            code='. '+str(LIB)+'''
ndp_iface_refresh || exit 5
echo "$IFACE"
cp "$STUBLOG/lookups" "$STUBLOG/before"
ndp_iface_refresh || exit 6
cmp "$STUBLOG/lookups" "$STUBLOG/before" || exit 7
echo 1 > "$STUBLOG/selected"; echo edited >> "$MU300_NDP_CONFIG"
ndp_iface_refresh || exit 8
echo "$IFACE"
'''
            r=self.sh(shell,code,**self.options)
            self.assertEqual((r.returncode,r.stdout,r.stderr),(0,'sipa_eth0\nsipa_eth8\n',''))

    def test_custom_device_and_switching_unknown_gates(self):
        for shell in self.each_shell():
            (self.tmp/'custom').write_text('wwan.test0\n')
            code='. '+str(LIB)+'''
ndp_iface_refresh || exit 5
echo "$IFACE"
touch "$MU300_NDP_RUN/mu300/sim-switching"
ndp_iface_refresh; echo "blocked:$?"
rm "$MU300_NDP_RUN/mu300/sim-switching"
touch "$MU300_NDP_RUN/mu300/sim-active-unknown"
ndp_iface_refresh; echo "unknown:$?"
rm "$MU300_NDP_RUN/mu300/sim-active-unknown"
'''
            r=self.sh(shell,code,**self.options)
            self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(r.stdout,'wwan.test0\nblocked:75\nunknown:75\n')

    def test_invalid_device_never_becomes_a_sysctl_path(self):
        (self.tmp/'custom').write_text('../bad\n')
        for shell in self.each_shell():
            r=self.sh(shell,'. '+str(LIB)+'\nndp_iface_refresh; printf "%s|%s" "$?" "$IFACE"',**self.options)
            self.assertEqual(r.stdout,'1|sipa_eth0',r.stderr)

    def test_prefix_entry_uses_only_the_selected_bearer(self):
        (self.tmp/'selected').write_text('1\n')
        inet=self.tmp/'inet6';inet.write_text(ROWS['a']+ROWS['b'].replace('sipa_eth0','sipa_eth8'))
        for shell in self.each_shell():
            r=self.script(shell,SCRIPT,'--prefix',MU300_IF_INET6=inet,**self.options)
            self.assertEqual((r.returncode,r.stdout,r.stderr),(0,B+'\n',''))
