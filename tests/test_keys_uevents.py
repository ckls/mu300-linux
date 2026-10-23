"""Real event parser with recvmsg replaced; no input, sysfs writes or netlink access."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from helpers import TOP

@unittest.skipUnless(os.name=='posix' and shutil.which('gcc'),'Linux gcc required')
class KeyUevents(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix='mu300-keys-events-')
        cls.addClassCleanup(cls.tmp.cleanup)
        source=Path(cls.tmp.name)/'test.c'
        source.write_text(r'''
#define main keys_program
#define recvmsg fake_recvmsg
#include "mu300-keys.c"
#undef main
#undef recvmsg
static int test_case;
ssize_t fake_recvmsg(int fd, struct msghdr *msg, int flags) {
    (void)fd; (void)flags;
    if(test_case==3) { errno=ENOBUFS; return -1; }
    const char data[]="change@/devices/test\0ACTION=change\0SUBSYSTEM=power_supply\0DEVPATH=/devices/test/battery\0";
    struct sockaddr_nl *sa=msg->msg_name;
    memset(sa,0,sizeof(*sa)); sa->nl_family=AF_NETLINK;
    if(test_case==1) sa->nl_pid=42;
    msg->msg_namelen=sizeof(*sa);
    msg->msg_flags=test_case==2 ? MSG_TRUNC : 0;
    memcpy(msg->msg_iov[0].iov_base,data,sizeof(data));
    return sizeof(data);
}
int main(int argc,char **argv) {
    if(argc!=2)return 2;
    test_case=atoi(argv[1]);
    subsystems[0]=test_case==4 ? "extcon" : "power_supply"; nsub=1;
    uevent_read(-1);
    return 0;
}
''')
        cls.binary=Path(cls.tmp.name)/'test'
        p=subprocess.run(['gcc','-O2','-Wall','-Wextra','-Werror','-I',str(TOP/'tools/keys'),str(source),'-o',str(cls.binary)],capture_output=True,text=True)
        if p.returncode: raise RuntimeError(p.stderr)

    def result(self,n):
        p=subprocess.run([str(self.binary),str(n)],capture_output=True,text=True,timeout=5)
        self.assertEqual(p.returncode,0,p.stderr)
        return p.stdout

    def test_kernel_event_emitted_once(self):
        self.assertEqual(self.result(0),'uevent change power_supply battery\n')

    def test_userspace_sender_and_unsubscribed_event_rejected(self):
        self.assertEqual(self.result(1),'')
        self.assertEqual(self.result(4),'')

    def test_overflow_and_truncation_request_state_recheck(self):
        self.assertEqual(self.result(2),'uevent overflow - -\n')
        self.assertEqual(self.result(3),'uevent overflow - -\n')
