"""Reproduce read timeout before coarse uptime reaches the existing deadline."""
import shlex
from helpers import BIN, ShellTest


class EventDeadlines(ShellTest):
    def run_wait(self, shell, kind, status):
        clock, now, wait = {
            'data': ('watch_clock', 'WATCH_NOW', 'watch_next'),
            'sms': ('sms_clock', 'SMS_NOW', 'sms_events_wait 1'),
            'ndp': ('ndp_clock', 'NDP_NOW', 'ndp_events_wait'),
        }[kind]
        source = BIN.parent/'lib'/f'{kind}-events.sh'
        # The first post-read uptime sample still rounds below due. Advance
        # on the next sample; no wall-clock sleeps or random scheduling needed.
        code = f'''set -eu
. {shlex.quote(str(source))}
samples=0; reads=0
{clock}() {{
    samples=$((samples + 1))
    if [ "$samples" -lt 3 ]; then {now}=0; else {now}=1; fi
}}
read() {{ reads=$((reads + 1)); return {status}; }}
watch_events=1; MU300_WATCH_INTERVAL=1
NDP_TICK_AT=1; NDP_FULL_AT=5; NDP_INTERVAL=1
exec 8</dev/null
result=0
{wait} || result=$?
printf '%s|%s|%s|%s' "$result" "$reads" "$samples" "${now}"
'''
        return self.sh(shell, code)

    def test_timeout_before_coarse_deadline_keeps_original_deadline(self):
        for shell in self.each_shell():
            for kind in ('data', 'sms', 'ndp'):
                with self.subTest(kind=kind):
                    result = self.run_wait(shell, kind, 142)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    status, reads, samples, now = map(int, result.stdout.split('|'))
                    self.assertEqual((status, samples, now), (0, 3, 1))
                    self.assertIn(reads, (1, 2))
                    self.assertEqual(result.stderr, '')

    def test_eof_before_deadline_remains_an_explicit_failure(self):
        for shell in self.each_shell():
            for kind in ('data', 'sms', 'ndp'):
                with self.subTest(kind=kind):
                    result = self.run_wait(shell, kind, 1)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout, '1|1|2|0')
                    self.assertIn('disconnected', result.stderr)
