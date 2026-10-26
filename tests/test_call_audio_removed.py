"""Retired call helpers must not return through cached images or boot services."""
import shlex
import unittest

from helpers import TOP, BIN, ShellTest


class SourcePolicy(unittest.TestCase):
    def test_helpers_are_not_shipped(self):
        for name in ('mu300-voice', 'mu300-audio-dsp'):
            self.assertFalse((BIN / name).exists(), name)

    def test_no_extra_dsp_memory_is_reserved(self):
        fragment = (TOP / 'kernel/mu300-linux.fragment').read_text()
        self.assertNotIn('CONFIG_OF_RESERVED_MEM_ADD=', fragment)
        self.assertNotIn('reserved_mem_add=', fragment)
        self.assertNotIn('of-reserved-mem-add', (TOP / 'kernel/build-all.sh').read_text())
        self.assertFalse((TOP / 'kernel/patches/of-reserved-mem-add.patch').exists())
        mainline = (TOP / 'upstream/mu300-mainline.config').read_text()
        self.assertNotIn('CONFIG_OF_RESERVED_MEM_ADD=', mainline)
        self.assertNotIn('reserved_mem_add=', mainline)

    def test_audio_services_remain_without_a_dsp_start(self):
        unit = (TOP / 'rootfs/overlay/etc/systemd/system/mu300-audio.service').read_text()
        self.assertIn('ExecStart=/bin/true', unit)
        self.assertNotIn('ExecStart=/opt/mu300/bin/mu300-audio-dsp', unit)
        self.assertTrue((TOP / 'openwrt/overlay/etc/init.d/mu300-audio').is_file())
        blocked = (TOP / 'rootfs/overlay/etc/modprobe.d/mu300-audio.conf').read_text()
        self.assertIn('install audio_mem /bin/false', blocked)
        self.assertIn('install sprd_audcp_boot /bin/false', blocked)


class AssemblyAndBoot(ShellTest):
    def test_builders_remove_retired_helpers_from_an_old_base(self):
        for shell in self.each_shell():
            for builder in ('rootfs/assemble.sh', 'openwrt/build-rootfs.sh'):
                root = self.tmp / ('root-' + builder.split('/')[0])
                directory = root / 'opt/mu300/bin'
                directory.mkdir(parents=True, exist_ok=True)
                for name in ('mu300-voice', 'mu300-audio-dsp', 'mu300-sms'):
                    (directory / name).write_text('old base input')
                lines = [l for l in (TOP / builder).read_text().splitlines()
                         if l.startswith('rm -f ') and 'mu300-voice' in l]
                self.assertEqual(len(lines), 1)
                r = self.sh(shell, lines[0], R=root)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertFalse((directory / 'mu300-voice').exists())
                self.assertFalse((directory / 'mu300-audio-dsp').exists())
                self.assertEqual((directory / 'mu300-sms').read_text(), 'old base input')

    def test_openwrt_boot_with_old_modules_does_not_start_the_dsp(self):
        source = (TOP / 'openwrt/overlay/etc/init.d/mu300-audio').read_text()
        body = source[source.index('boot() {'):source.index('\nstart_service()')]
        modules = self.tmp / 'modules/audio'
        modules.mkdir(parents=True)
        log = self.tmp / 'audio.log'
        body = body.replace('/opt/mu300/bin/mu300-audio-dsp',
                            shlex.quote(str(self.tmp / 'missing-loader')))
        body = body.replace('"/lib/modules/$(uname -r)/audio"', shlex.quote(str(modules)))
        body = body.replace('/tmp/mu300-audio.log', shlex.quote(str(log)))
        for shell in self.each_shell():
            r = self.sh(shell, body + '\nboot')
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stderr, '')
            self.assertFalse(log.exists())


if __name__ == '__main__':
    unittest.main()
