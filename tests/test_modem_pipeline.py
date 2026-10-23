"""Real ARM64 bridge + ucode + original FIFO CLI, using PTYs in our test container.

This deliberately requires an explicit verified binary and the disposable test
container marker. Never creates aliases in a workstation/device's normal /dev.
"""
import os
import pty
import select
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from helpers import TOP, BIN, ucode, ucode_paths
from test_modemd import wait_for

BRIDGE=os.environ.get('MU300_TEST_ATD_IO','')

@unittest.skipUnless(BRIDGE and Path('/tmp/event-test-ready').exists() and ucode(),'explicit isolated container and verified ARM64 bridge required')
class ModemPipeline(unittest.TestCase):
    def setUp(self):
        self.tmp=Path(tempfile.mkdtemp(prefix='modem-pipeline-'))
        self.procs=[];self.fds=[];self.aliases=[];self.done=False
        self.directory=self.tmp/'at';self.socket=self.tmp/'io.sock'
        for n in [0,1]:
            master,slave=pty.openpty()
            self.fds.extend([master,slave])
            alias=Path('/dev')/f'mu300t{os.getpid()}{n}'
            if os.path.lexists(alias): self.fail('test alias already exists; refusing to replace it')
            os.symlink(os.ttyname(slave),alias)
            self.aliases.append(alias)
            if n==0:self.urc=master
            else:self.command=master
        self.requests=[]
        self.thread=threading.Thread(target=self.modem,daemon=True);self.thread.start()
        self.spool=self.tmp/'spool'
        spooler=self.tmp/'spooler'
        spooler.write_text('#!/bin/sh\ncat >> "'+str(self.spool)+'"\n');spooler.chmod(0o755)
        self.env=dict(os.environ,MU300_CMT_SPOOL_BIN=str(spooler),MU300_MODEMD_RUN=str(self.tmp),MU300_REGISTRATION_DIR=str(self.tmp/'registration'),MU300_AT_DIR=str(self.directory),MU300_AT_DEV=str(self.aliases[1]),MU300_AT_LOCK_WAIT='0',MU300_AT_DAEMON_ONLY='1')
        self.bridge=subprocess.Popen([BRIDGE,'-s',str(self.socket)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        self.procs.append(self.bridge)
        self.assertTrue(wait_for(self.socket.exists))
        self.start_daemon()

    def tearDown(self):
        for p in reversed(self.procs):
            if p.poll() is None:
                p.terminate()
                try:p.wait(5)
                except subprocess.TimeoutExpired:p.kill();p.wait(5)
            if p.stdout:p.stdout.close()
            if p.stderr:p.stderr.close()
        self.done=True;self.thread.join(2)
        for alias in self.aliases: alias.unlink(missing_ok=True)
        for fd in self.fds:os.close(fd)
        shutil.rmtree(self.tmp)

    def modem(self):
        buf=b''
        while not self.done:
            ready,_,_=select.select([self.command],[],[],.1)
            if not ready:continue
            try:data=os.read(self.command,4096)
            except OSError:time.sleep(.01);continue
            buf+=data
            while b'\r' in buf:
                cmd,buf=buf.split(b'\r',1)
                self.requests.append(cmd.decode())
                answer=b'\r\n+CSQ: 20,99\r\nOK\r\n' if cmd==b'AT+CSQ' else b'\r\nERROR\r\n'
                os.write(self.command,answer)

    def start_daemon(self):
        spec=f'name=atd,dev={self.aliases[1]},dir={self.directory},urc=0,reopen=0'
        p=subprocess.Popen(ucode()+ucode_paths()[2:]+[str(BIN/'mu300-modemd'),'-s',str(self.socket),spec],env=self.env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        self.procs.append(p);self.daemon=p
        self.assertTrue(wait_for(lambda:(self.directory/'cmd').exists() and (self.directory/'owner'/'pid').exists()))
        time.sleep(1.3)

    def ask(self):
        p=subprocess.run(['/bin/sh',str(BIN/'mu300-at'),'-t','5','AT+CSQ'],env=self.env,capture_output=True,text=True,timeout=9)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(p.stdout,'+CSQ: 20,99\nOK\n')

    def held_ttys(self):
        return sorted((p.name,os.readlink(p)) for p in Path(f'/proc/{self.bridge.pid}/fd').iterdir() if '/dev/pts/' in os.readlink(p))

    def test_bridge_fifo_client_and_daemon_restart_preserve_descriptors(self):
        self.ask()
        before=self.held_ttys()
        self.assertEqual(len(before),2)
        self.assertEqual((self.directory/'owner'/'pid').read_text().strip(),str(self.bridge.pid))
        self.daemon.terminate();self.daemon.wait(5)
        # Submit while no ucode client is connected. The C bridge queues the
        # FIFO request and keeps both descriptors, then delivers it on takeover.
        pending=subprocess.Popen(['/bin/sh',str(BIN/'mu300-at'),'-t','5','AT+CSQ'],env=self.env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        self.procs.append(pending)
        time.sleep(.15)
        self.start_daemon()
        out,err=pending.communicate(timeout=8)
        self.assertEqual(pending.returncode,0,err)
        self.assertEqual(out,'+CSQ: 20,99\nOK\n')
        self.assertEqual(self.held_ttys(),before)
        self.assertIsNone(self.bridge.poll())
        self.ask()
        os.write(self.urc,b'+CMT: ,23\r\n0791448720003023\r\n')
        self.assertTrue(wait_for(lambda: self.spool.exists() and self.spool.read_text()=='+CMT: ,23\n0791448720003023\n'))
        log=self.directory/'urc'/(self.aliases[0].name+'.log')
        self.assertTrue(wait_for(lambda: 'PDU spooled' in log.read_text()))
        self.assertNotIn('079144',log.read_text())
        self.assertEqual(self.requests,['AT+CSQ']*3)
