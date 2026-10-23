"""OpenWrt starts one system service and reports missing requirements."""
from helpers import ShellTest, TOP
INIT=TOP/'openwrt/overlay/etc/init.d'
class SysdService(ShellTest):
    def setUp(self):
        super().setUp()
        self.stub('ucode','exit "${RUNTIME_FAIL:-0}"')
        self.procd='procd_open_instance() { echo "instance:$1"; }; procd_set_param() { echo "param:$*"; }; procd_close_instance() { :; };\n'

    def run_init(self,shell,fail=0):
        source=(INIT/'mu300-sysd').read_text().replace('/usr/bin/ucode','ucode')
        return self.sh(shell,self.procd+source+'\nstart_service\n',RUNTIME_FAIL=fail)

    def test_native_service_starts_directly(self):
        for shell in self.each_shell():
            p=self.run_init(shell)
            self.assertEqual(p.returncode,0,p.stderr)
            self.assertIn('instance:sysd',p.stdout)
            self.assertIn('param:command ucode /opt/mu300/bin/mu300-sysd',p.stdout)

    def test_missing_dependency_is_an_error_not_another_backend(self):
        for shell in self.each_shell():
            p=self.run_init(shell,fail=1)
            self.assertNotEqual(p.returncode,0)
            self.assertNotIn('instance:',p.stdout)

    def test_no_second_openwrt_key_or_thermal_implementation_is_enabled(self):
        self.assertFalse((INIT/'mu300-buttons').exists())
        post=(INIT/'mu300-post').read_text()
        self.assertNotIn('thermalguard',post)
        self.assertNotIn('thermal-guard',post)
        self.assertNotIn('sysd_on',post)
        self.assertNotIn('mu300-buttons mu300-sysd',(TOP/'openwrt/build-rootfs.sh').read_text())

    def test_release_builds_source_matched_arm64_keys(self):
        for name,root in [('tools/make-release.sh','$IN'),('install.sh','$WORK')]:
            self.assertIn(f'sh "$TOP/tools/keys/build.sh" "{root}/tools/keys"',(TOP/name).read_text())
        self.assertIn('S95mu300-sysd',(TOP/'tools/build-openwrt-tf-magisk.sh').read_text())
