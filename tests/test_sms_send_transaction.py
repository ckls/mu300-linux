"""PR #177 adaptation: real FIFO client, isolated pool, no modem or SMS sends."""
import json
import os
from pathlib import Path
import re
import select
import shlex
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import unittest

from helpers import TOP

SMS = TOP / 'rootfs/overlay/opt/mu300/bin/mu300-sms'
AT = TOP / 'rootfs/overlay/opt/mu300/bin/mu300-at'
RPC = TOP / 'openwrt/luci-app-mu300/root/usr/libexec/rpcd/mu300dash'


class SmsTransaction(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.channel = self.root / 'channel'
        self.channel.mkdir()
        os.mkfifo(self.channel / 'cmd')
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        (self.bin / 'mu300-at').symlink_to(AT)
        self.env = dict(os.environ, PATH=str(self.bin) + ':' + os.environ['PATH'],
                        MU300_AT_DIR=str(self.channel), MU300_AT_LOCK_WAIT='0',
                        MU300_SMS_POOL=str(self.root / 'pool'),
                        MU300_SMS_OP_LOCK=str(self.root / 'oplock'),
                        MU300_SMS_PDU_AWK=str(TOP / 'rootfs/overlay/opt/mu300/lib/sms-pdu.awk'))
        self.commands = []
        self.query = '+CSCA: "2B38363133383030313030353030",145\nOK\n'
        self.write = 'OK\n'
        self.submit = '+CMGS: 42\nOK\n'
        self.stop = threading.Event()
        self.fd = os.open(self.channel / 'cmd', os.O_RDWR | os.O_NONBLOCK)
        self.thread = threading.Thread(target=self.daemon, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.stop.set()
        self.thread.join(timeout=2)
        os.close(self.fd)
        self.temp.cleanup()

    def daemon(self):
        data = b''
        while not self.stop.is_set():
            if not select.select([self.fd], [], [], .05)[0]:
                continue
            data += os.read(self.fd, 8192)
            while b'\n' in data:
                line, data = data.split(b'\n', 1)
                _, answer, command = line.decode().split(' ', 2)
                holder = (self.channel / 'lock/pid').read_text().strip()
                self.commands.append((command, holder))
                if 'CSCA?' in command:
                    reply = self.query
                elif 'CSCA=' in command:
                    reply = self.write
                elif 'CMGS=' in command:
                    reply = self.submit
                else:
                    reply = 'OK\n'
                part = Path(answer + '.part')
                part.write_text(reply)
                part.rename(answer)

    def send(self, shell='bash', text='test', **extra):
        return subprocess.run([shell, str(SMS), 'send', '10010', text],
                              env=dict(self.env, **extra), capture_output=True,
                              text=True, timeout=8)

    def test_one_holder_whole_transaction_and_cleanup(self):
        for shell in ('bash', 'dash'):
            self.commands.clear()
            result = self.send(shell)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(self.commands), 5)
            self.assertEqual(len({p for _, p in self.commands}), 1)
            self.assertEqual(self.commands[1][0], 'AT+CSCA="2B38363133383030313030353030",145')
            self.assertFalse((self.channel / 'lock').exists())
            self.assertFalse((self.root / 'oplock').exists())

    def test_plain_smsc_same_value_and_slot_one(self):
        self.query = '+CSCA: "+8613800100500",145\nOK\n'
        result = self.send(MU300_SIM_SLOT='1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.commands[1][0], 'AT+SPACTCARD=1;+CSCA="+8613800100500",145')
        self.assertTrue(all(c.startswith('AT+SPACTCARD=1;') for c, _ in self.commands))

    def test_multiline_text_is_encoded_inside_pdu_not_fifo_protocol(self):
        for text in ('first\nsecond', '\nfirst\n\nlast\n', 'a\r\nb\r\n',
                     'literal\\ntext', '中文\nİstanbul 😀\n', '\n', 'a' * 68 + '\nZ'):
            with self.subTest(text=repr(text)):
                self.commands.clear()
                result = self.send(text=text, MU300_SIM_SLOT='1')
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                commands = [cmd for cmd, _ in self.commands if '+CMGS=' in cmd]
                self.assertEqual(len(commands), 1)
                command = commands[0]
                self.assertNotIn('\n', command)
                header, pdu = command.split('\r', 1)
                data = bytes.fromhex(pdu.removesuffix('\x1a'))
                address_bytes = (data[3] + 1) // 2
                udl_position = 7 + address_bytes
                payload = data[udl_position + 1:]
                self.assertEqual(payload, text.encode('utf-16-be'))
                self.assertEqual(data[udl_position], len(payload))
                self.assertEqual(int(re.search(r'CMGS=(\d+)', header)[1]), len(data) - 1)

    def test_trailing_newlines_count_towards_sms_limit_before_any_at(self):
        result = self.send(text='a' * 69 + '\n\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('71 UCS-2 units', result.stderr)
        self.assertEqual(self.commands, [])

    def test_malformed_or_failed_query_still_submits(self):
        for query in ['ERROR\n', '+CSCA: "evil;AT",145\nOK\n', 'OK\n']:
            self.query = query
            self.commands.clear()
            result = self.send()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(any('CSCA=' in c for c, _ in self.commands))
            self.assertTrue(any('CMGS=' in c for c, _ in self.commands))

    def test_refused_refresh_does_not_block_send(self):
        self.write = 'ERROR\n'
        result = self.send()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('refresh refused', result.stderr)

    def test_failed_submission_releases_both_locks(self):
        self.submit = '+CMS ERROR: 500\n'
        result = self.send()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.channel / 'lock').exists())
        self.assertFalse((self.root / 'oplock').exists())
        self.assertIn('+CMS ERROR: 500', result.stderr)

    @unittest.skipUnless(shutil.which('busybox'), 'BusyBox ash required')
    def test_background_signal_state_preserves_slot_and_transaction(self):
        # Run both sender and FIFO client in ash, as on OpenWrt; the host's
        # /bin/sh might be dash and otherwise re-exec the client in bash.
        client = self.bin / 'mu300-at'
        client.unlink()
        client.write_text('#!/bin/sh\nexec busybox ash '+shlex.quote(str(AT))+' "$@"\n')
        client.chmod(0o755)
        for ignored, blocked in (([signal.SIGCHLD, signal.SIGPIPE], []),
                                 ([], [signal.SIGCHLD, signal.SIGALRM]),
                                 ([signal.SIGINT, signal.SIGQUIT, signal.SIGHUP], [])):
            def setup():
                for sig in ignored:
                    signal.signal(sig, signal.SIG_IGN)
                signal.pthread_sigmask(signal.SIG_BLOCK, blocked)
            self.commands.clear()
            # Forwarding keeps descriptor 8/9 locks open in its parent. The
            # child may use fd9 for its FIFO, without closing the parent's lock.
            launch = 'exec 8>'+shlex.quote(str(self.root/'fd8'))+' 9>'+shlex.quote(str(self.root/'fd9'))+'; exec "$@"'
            result = subprocess.run(['busybox', 'ash', '-c', launch, 'fixture',
                                     'busybox', 'ash', str(SMS), 'send', '10010', 'fixture'],
                                    env=dict(self.env, MU300_SIM_SLOT='1'),
                                    stdin=subprocess.DEVNULL, capture_output=True,
                                    preexec_fn=setup, start_new_session=True, text=True, timeout=8)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(self.commands), 5)
            self.assertEqual(len({holder for _, holder in self.commands}), 1)
            self.assertTrue(all(c.startswith('AT+SPACTCARD=1;') for c, _ in self.commands))
            self.assertEqual(sum('CMGS=' in c for c, _ in self.commands), 1)

    def test_empty_at_submission_is_reported_without_resending(self):
        # Interpose a transport failure after the real client has carried all
        # setup requests; this must not create a sent entry or repeat Ctrl-Z.
        client = self.bin / 'mu300-at'
        client.unlink()
        client.write_text('#!/bin/sh\ncase "$*" in *CMGS=*) exit 7 ;; esac\n'
                          'exec bash '+shlex.quote(str(AT))+' "$@"\n')
        client.chmod(0o755)
        result = self.send()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('no submission acknowledgement (AT exit 7)', result.stderr)
        self.assertFalse(any('CMGS=' in c for c, _ in self.commands))
        self.assertFalse((self.channel / 'lock').exists())
        self.assertFalse((self.root / 'oplock').exists())

    def test_live_holder_busy_without_commands(self):
        lock = self.channel / 'lock'
        lock.mkdir()
        (lock / 'pid').write_text(str(os.getpid()))
        result = self.send()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('mu300-at: busy', result.stderr)
        self.assertFalse(self.commands)
        self.assertTrue(lock.exists())
        # sms_op_lock was acquired before waiting for AT; failure must release it.
        self.assertFalse((self.root / 'oplock').exists())

    def test_dead_holder_recovered(self):
        lock = self.channel / 'lock'
        lock.mkdir()
        (lock / 'pid').write_text('99999999')
        self.assertEqual(self.send().returncode, 0)

    def test_borrowed_client_leaves_parent_lock(self):
        lock = self.channel / 'lock'
        lock.mkdir()
        (lock / 'pid').write_text(str(os.getpid()))
        result = subprocess.run(['bash', str(AT), 'AT'], capture_output=True,
                                text=True, timeout=5,
                                env=dict(self.env, MU300_AT_LOCK_HELD=str(os.getpid())))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((lock / 'pid').read_text(), str(os.getpid()))

    def test_invalid_borrower_cannot_skip_live_lock(self):
        lock = self.channel / 'lock'
        lock.mkdir()
        (lock / 'pid').write_text(str(os.getpid()))
        for held in ('99999999', 'not-a-pid', ''):
            result = subprocess.run(['bash', str(AT), 'AT'], capture_output=True,
                                    text=True, timeout=5,
                                    env=dict(self.env, MU300_AT_LOCK_HELD=held))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('mu300-at: busy', result.stderr)
        self.assertFalse(self.commands)


class SmsJob(unittest.TestCase):
    def test_background_send_duplicate_guard_and_slot_pool(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bindir = root / 'bin'
            bindir.mkdir()
            def stub(name, text):
                p = bindir / name
                p.write_text(text)
                p.chmod(0o755)
                return p
            stub('uci', '#!/bin/sh\nexit 1\n')
            stub('jsonfilter', '''#!/usr/bin/python3
import json,sys
data=json.load(sys.stdin)
key=sys.argv[sys.argv.index('-e')+1][2:]
value=data.get(key, '')
print(value if not isinstance(value,dict) else json.dumps(value))
''')
            sms = stub('sms-test', '''#!/bin/sh
printf '%s|%s|%s\n' "$MU300_SMS_POOL" "$MU300_SIM_SLOT" "$*" >> "$TEST_SENDS"
sleep 1
printf 'sent (42)\n'
''')
            for slot in ('0', '1'):
                directory = root / ('dash' + slot)
                pool = root / ('pool' + slot)
                env = dict(os.environ, PATH=str(bindir) + ':' + os.environ['PATH'],
                           MU300_DASH_DIR=str(directory), MU300_SMS_BIN=str(sms),
                           MU300_SMS_POOL=str(pool), MU300_SIM_SLOT=slot,
                           MU300_DASH_BIN=str(bindir), MU300_SMS_POOL_LIB=str(SMS.parent.parent/'lib/sms-pool.sh'), TEST_SENDS=str(root / 'sends'))
                def call(method, data=None):
                    result = subprocess.run([str(RPC), 'call', method],
                                            input=json.dumps(data or {}), env=env,
                                            capture_output=True, text=True, timeout=3)
                    return json.loads(result.stdout)
                start = time.monotonic()
                processes = [subprocess.Popen([str(RPC), 'call', 'sms_send'],
                                              stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                              stderr=subprocess.PIPE, text=True, env=env)
                             for _ in range(2)]
                for process in processes:
                    process.stdin.write(json.dumps({'num':'10010', 'text':'test'}))
                    process.stdin.close()
                    process.stdin = None
                responses = [json.loads(p.communicate(timeout=3)[0]) for p in processes]
                self.assertEqual(sum(bool(r.get('started')) for r in responses), 1)
                self.assertEqual(sum(bool(r.get('busy')) for r in responses), 1)
                self.assertLess(time.monotonic() - start, .8)
                self.assertTrue(call('sms_send', {'num':'10010','text':'second'})['busy'])
                for _ in range(30):
                    result = call('sms_job')
                    if result.get('done'):
                        break
                    time.sleep(.1)
                self.assertTrue(result['ok'], result)
                self.assertEqual((directory / 'sms-job').stat().st_mode & 0o077, 0)
                self.assertFalse((directory / 'sms-job/text').exists())
                expected = str(pool) + ('/sim1' if slot == '1' else '')
                self.assertIn(expected + '|' + slot + '|send 10010 test', (root / 'sends').read_text())
                # A worker that died without publishing a result is not replayed.
                (directory / 'sms-job/end').unlink()
                (directory / 'sms-job/result').unlink()
                (directory / 'sms-job/pid').write_text('99999999')
                unknown = call('sms_job')
                self.assertTrue(unknown['done'])
                self.assertFalse(unknown['ok'])
            self.assertEqual(len((root / 'sends').read_text().splitlines()), 2)


if __name__ == '__main__':
    unittest.main()
