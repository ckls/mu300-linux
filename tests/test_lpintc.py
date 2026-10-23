"""Run the actual LP_AP_INTC C implementation with emulated MMIO only."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from helpers import TOP, BIN, ShellTest


class LpIntc(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc = shutil.which('cc')
        if not cc:
            raise unittest.SkipTest('host C compiler required')
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        root = Path(cls.tmp.name)
        include = root / 'linux'
        include.mkdir()
        for name in ('bits', 'io', 'module', 'of', 'of_address', 'spinlock', 'syscore_ops', 'workqueue'):
            (include / (name + '.h')).touch()
        cls.binary = root / 'lpintc-test'
        subprocess.run([cc, '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                        '-Wno-unused-parameter', '-Wno-unused-function',
                        '-I', str(root), str(TOP / 'tests/fixtures/lpintc-harness.c'),
                        '-o', str(cls.binary)], check=True, capture_output=True, text=True)

    def run_case(self, case):
        result = subprocess.run([str(self.binary), case], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'OK')

    def test_enabled_interrupts_late_drivers_suspend_resume_and_unload(self):
        self.run_case('lifecycle')

    def test_clock_off_is_never_accessed_and_zero_period_is_bounded(self):
        self.run_case('clock-off')

    def test_wrong_soc_and_missing_hardware_never_write(self):
        for case in ('wrong-soc', 'no-gic', 'all-clocks-off'):
            with self.subTest(case=case):
                self.run_case(case)

    def test_mapping_failure_releases_every_mapping_before_writes(self):
        for case in ('bad-gic', 'bad-gate', 'partial-map'):
            with self.subTest(case=case):
                self.run_case(case)


class Loader(ShellTest):
    def setUp(self):
        super().setUp()
        self.modules = self.tmp / 'modules'
        self.modules.mkdir()
        self.loaded = self.tmp / 'loaded'
        self.stub('insmod', 'echo "$1" >> "$STUBLOG/loads"; exit "${LOAD_FAIL:-0}"')
        source = (BIN / 'extra-modules').read_text()
        start = source.index('# UMS9620 mainline:')
        end = source.index('if [ -f "$M/sipc-core.ko" ]', start)
        self.code = source[start:end].replace('/sys/module/ums9620_lpintc', str(self.loaded))
        self.code = self.code.replace('insmod ', str(self.stubs / 'insmod') + ' ')

    def run_loader(self, shell, **env):
        return self.sh(shell, self.code, M=self.modules, **env)

    def test_flat_and_extra_layouts_load_once_and_already_loaded_is_untouched(self):
        for shell in self.each_shell():
            for layout in ('', 'extra'):
                with self.subTest(layout=layout):
                    module = self.modules / layout / 'ums9620_lpintc.ko'
                    module.parent.mkdir(exist_ok=True)
                    module.touch()
                    log = self.tmp / 'loads'
                    log.unlink(missing_ok=True)
                    result = self.run_loader(shell)
                    self.assertEqual(log.read_text().splitlines(), [str(module)])
                    self.assertIn('loaded ums9620_lpintc', result.stdout)
                    self.loaded.mkdir()
                    self.run_loader(shell)
                    self.assertEqual(len(log.read_text().splitlines()), 1)
                    self.loaded.rmdir()
                    module.unlink()

    def test_missing_vendor_54_module_is_skipped_and_load_failure_is_reported(self):
        for shell in self.each_shell():
            log = self.tmp / 'loads'
            log.unlink(missing_ok=True)
            self.assertEqual(self.run_loader(shell).stdout, '')
            self.assertFalse(log.exists())
            module = self.modules / 'ums9620_lpintc.ko'
            module.touch()
            result = self.run_loader(shell, LOAD_FAIL=1)
            self.assertIn('FAILED ums9620_lpintc', result.stdout)
            self.assertNotIn('loaded ums9620_lpintc', result.stdout)
            module.unlink()
