"""Production SMS -> FIFO -> ucode broker -> simulated modem; never sends SMS."""
import os
import re
import select
import shlex
import subprocess
import threading
import unittest

from helpers import TOP, ucode
from test_modemd import Base, MODEMD, has_modules


@unittest.skipUnless(ucode(), 'ucode required')
class PduBoundary(unittest.TestCase):
    def accepted(self, commands):
        # Execute the actual validator in ucode, not a Python translation.
        import json
        source = MODEMD.read_text()
        source = source[source.index("const LF ="):source.index('\nfunction answer_file')]
        code = source + '\nfor (let c in ' + json.dumps(commands) + ') print(one_request(c) ? "1\\n" : "0\\n");'
        result = subprocess.run(ucode() + ['-e', code], capture_output=True, text=True, timeout=8)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.splitlines()

    def test_bare_and_sim_scoped_atomic_pdu_requests(self):
        requests = [f'AT{scope}+CMG{op}=12\r001122Aa\x1a'
                    for scope in ('', '+SPACTCARD=0;', '+SPACTCARD=1;') for op in ('S', 'W')]
        self.assertEqual(self.accepted(requests), ['1'] * len(requests))

    def test_pdu_does_not_allow_other_commands_or_malformed_scopes(self):
        heads = ['AT+SPACTCARD=2;+CMGS=12', 'AT+SPACTCARD=-1;+CMGS=12',
                 'AT+SPACTCARD=01;+CMGS=12', 'AT+SPACTCARD=1;+CFUN=0;+CMGS=12',
                 'AT+CFUN=0;+CMGS=12', 'AT+SPACTCARD=0;+SPACTCARD=1;+CMGS=12',
                 'AT+SPACTCARD=1;AT+CMGS=12', 'AT+SPACTCARD=1;+CMGS=1000']
        requests = [h + '\r001122\x1a' for h in heads] + [
            'AT+SPACTCARD=1;+CMGS=12\r001122',
            'AT+SPACTCARD=1;+CMGS=12\r00112Z\x1a',
            'AT+SPACTCARD=1;+CMGS=12\r\x1a',
            'AT+SPACTCARD=1;+CMGS=12\r001122\x1a\rAT+CFUN=0',
            'AT+SPACTCARD=1;+CMGS=12\r001122\x1a\nAT+CFUN=0']
        self.assertEqual(self.accepted(requests), ['0'] * len(requests))


@unittest.skipUnless(ucode() and has_modules(ucode()), 'ucode socket/uloop/ubus required')
class SmsBroker(Base):
    def setUp(self):
        super().setUp()
        # Never publish on the device's live bus, even when tested on hardware.
        self.env['MU300_UBUS_SOCKET'] = str(self.tmp / 'isolated-unavailable.sock')

    def start_dual(self):
        self.start(f'name=sim0,dev=/dev/stty_nr1,dir={self.run_root}/mu300-at,urc=0',
                   f'name=sim1,dev=/dev/stty_nr4,dir={self.run_root}/mu300-at4,urc=3')
        self.ready('stty_nr1')
        self.ready('stty_nr4')

    def test_both_scoped_submits_reach_only_their_channel_in_one_write(self):
        self.start_dual()
        for slot, name, directory in ((0, 'stty_nr1', 'mu300-at'), (1, 'stty_nr4', 'mu300-at4')):
            cmd = f'AT+SPACTCARD={slot};+CMGS=12\r0011000B811234\x1a'
            self.table[cmd] = ['+CMGS: 42', 'OK']
            answer = self.run_root / directory / f'answer.{10 + slot}'
            self.ask(f'2 {answer} {cmd}', name)
            self.assertEqual(self.answer(answer), '+CMGS: 42\nOK\n')
            self.assertEqual([tx for tx in self.bridge.tx if cmd in tx[1]], [(name, cmd + '\r')])

    def test_real_sender_and_client_through_broker_on_both_sims(self):
        self.table['AT+CSCA?'] = ['+CSCA: "+8613800100500",145', 'OK']
        original_modem = self.bridge.modem
        self.bridge.modem = lambda name, cmd: (
            ['+CMGS: 42', 'OK'] if re.fullmatch(r'AT\+SPACTCARD=[01];\+CMGS=\d+\r[0-9A-F]+\x1a', cmd)
            else original_modem(name, cmd))
        self.start_dual()
        bindir = self.tmp / 'bin'
        bindir.mkdir()
        client = bindir / 'mu300-at'
        client.write_text('#!/bin/sh\nexec /bin/sh ' + shlex.quote(str(TOP / 'rootfs/overlay/opt/mu300/bin/mu300-at')) + ' "$@"\n')
        client.chmod(0o755)
        for slot, name, directory in ((0, 'stty_nr1', 'mu300-at'), (1, 'stty_nr4', 'mu300-at4')):
            with self.subTest(slot=slot):
                atdir = self.run_root / directory
                fifo = atdir / 'cmd'
                os.mkfifo(fifo, 0o600)
                fd = os.open(fifo, os.O_RDWR | os.O_NONBLOCK)
                stop = threading.Event()
                errors = []
                def forward_requests():
                    pending = b''
                    try:
                        while not stop.is_set():
                            if not select.select([fd], [], [], .02)[0]:
                                continue
                            pending += os.read(fd, 8192)
                            while b'\n' in pending:
                                line, pending = pending.split(b'\n', 1)
                                self.bridge.req(name, line.decode('ascii'))
                    except Exception as error:
                        errors.append(error)
                thread = threading.Thread(target=forward_requests, daemon=True)
                thread.start()
                before = len(self.bridge.tx)
                try:
                    env = dict(self.env, PATH=str(bindir) + ':' + os.environ['PATH'],
                               MU300_AT_DIR=str(atdir), MU300_SIM_SLOT=str(slot),
                               MU300_SMS_POOL=str(self.tmp / f'pool{slot}'),
                               MU300_SMS_OP_LOCK=str(self.tmp / f'operation{slot}.lock'),
                               MU300_SMS_PDU_AWK=str(TOP / 'rootfs/overlay/opt/mu300/lib/sms-pdu.awk'))
                    body = 'first\n第二行\r\n\nlast\n'
                    result = subprocess.run(['/bin/sh', str(TOP / 'rootfs/overlay/opt/mu300/bin/mu300-sms'),
                                             'send', '10010', body], env=env, capture_output=True,
                                            text=True, stdin=subprocess.DEVNULL, start_new_session=True, timeout=12)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn('sent (42)', result.stdout)
                    tx = self.bridge.tx[before:]
                    self.assertEqual(len(tx), 5, tx)
                    self.assertTrue(all(channel == name and cmd.startswith(f'AT+SPACTCARD={slot};') for channel, cmd in tx), tx)
                    self.assertEqual(sum('+CMGS=' in cmd for _, cmd in tx), 1)
                    submit = next(cmd for _, cmd in tx if '+CMGS=' in cmd)
                    pdu = bytes.fromhex(submit.split('\r', 1)[1].removesuffix('\x1a\r'))
                    payload = pdu[8 + (pdu[3] + 1) // 2:]
                    self.assertEqual(payload, body.encode('utf-16-be'))
                    self.assertFalse((atdir / 'lock').exists())
                    self.assertFalse((self.tmp / f'operation{slot}.lock').exists())
                    self.assertEqual(errors, [])
                finally:
                    stop.set()
                    thread.join(2)
                    os.close(fd)


if __name__ == '__main__':
    unittest.main()
