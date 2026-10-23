"""Exercise both firmware-helper layouts without hardware or real delays."""
from helpers import BIN, ShellTest


class RegulatoryBoot(ShellTest):
    def setUp(self):
        super().setUp()
        self.root = self.tmp / 'root'
        self.root.mkdir()
        self.stub('sleep', 'echo "$1" >> "$STUBLOG/sleeps"; exit 0')
        self.stub('iw', 'echo "$*" >> "$STUBLOG/requests"; '
                         'if [ "${REQUIRE_FED:-0}" = 1 ]; then '
                         'for f in regulatory.db regulatory.db.p7s; do '
                         '[ "$(cat "$MU300_SYSROOT/sys/class/firmware/$f/loading")" = 0 ] || exit 1; '
                         'cmp "$MU300_SYSROOT/sys/class/firmware/$f/data" "$MU300_SYSROOT/lib/firmware/$f" || exit 1; '
                         'done; fi; [ "${RELOAD_FAIL:-0}" = 0 ]')
        # BusyBox standalone applets must not bypass fixture commands.
        code = (BIN / 'regdb-load').read_text()
        code = code.replace('sleep ', str(self.stubs / 'sleep') + ' ')
        code = code.replace('iw reg reload ', str(self.stubs / 'iw') + ' reg reload ')
        self.entry = self.tmp / 'regdb-load'
        self.entry.write_text(code)

    def test_no_firmware_helper_does_not_wait_for_impossible_requests(self):
        for shell in self.each_shell():
            (self.tmp / 'requests').unlink(missing_ok=True)
            result = self.script(shell, self.entry, MU300_SYSROOT=self.root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((self.tmp / 'sleeps').exists())
            self.assertEqual((self.tmp / 'requests').read_text().splitlines(), ['reg reload'])

    def test_pending_database_and_signature_are_fed_before_reload(self):
        for shell in self.each_shell():
            for name, data in [('regulatory.db', 'database-bytes'), ('regulatory.db.p7s', 'signature-bytes')]:
                source = self.root / 'lib/firmware' / name
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_text(data)
                request = self.root / 'sys/class/firmware' / name
                request.mkdir(parents=True, exist_ok=True)
                (request / 'loading').touch()
                (request / 'data').touch()
            result = self.script(shell, self.entry, MU300_SYSROOT=self.root, REQUIRE_FED=1)
            self.assertEqual(result.returncode, 0, result.stderr)
            for name in ['regulatory.db', 'regulatory.db.p7s']:
                request = self.root / 'sys/class/firmware' / name
                self.assertEqual((request / 'loading').read_text(), '0\n')
                self.assertEqual((request / 'data').read_bytes(), (self.root / 'lib/firmware' / name).read_bytes())
            self.assertFalse((self.tmp / 'sleeps').exists())

    def test_reload_failure_keeps_existing_bounded_retry_and_reports_failure(self):
        for shell in self.each_shell():
            for name in ['requests', 'sleeps']:
                (self.tmp / name).unlink(missing_ok=True)
            result = self.script(shell, self.entry, MU300_SYSROOT=self.root, RELOAD_FAIL=1)
            self.assertEqual(result.returncode, 1)
            self.assertIn('iw reg reload failed', result.stderr)
            self.assertEqual(len((self.tmp / 'requests').read_text().splitlines()), 10)
            self.assertEqual(len((self.tmp / 'sleeps').read_text().splitlines()), 10)
