"""Compile actual delegate startup/wait callbacks; no hardware or driver load."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from helpers import TOP, BIN, ShellTest
from test_upstream_power_order import function

DELE = TOP / 'upstream/modules/sprd_modem/sipa_delegate'


@unittest.skipUnless(shutil.which('cc'), 'C compiler required')
class DelegateKernel(unittest.TestCase):
    def run_c(self, code):
        with tempfile.TemporaryDirectory(prefix='delegate-ready-') as directory:
            root = Path(directory)
            (root/'test.c').write_text('#include <stddef.h>\n'+code)
            build = subprocess.run(['cc', '-Wall', '-Werror', '-Wno-unused-function',
                            '-fsanitize=undefined', str(root/'test.c'), '-o', str(root/'test')],
                           capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            subprocess.run([str(root/'test')], check=True)

    def test_graph_and_consumer_callback_precede_first_thread_message(self):
        source = (DELE/'sipa_dele_cmn.c').read_text()
        model = r'''
#include <assert.h>
#include <stdbool.h>
#include <errno.h>
struct sipa_delegator {
 int thread,prod_id,cons_prod,cons_user;
 void *local_request_prod,*local_release_prod;
};
struct sipa_rm_create_params { int name,floor_voltage; struct { void *notify_cb,*user_data; } reg_params; void *request_resource,*release_resource; };
struct sipa_rm_register_params { void *notify_cb,*user_data; };
#define pr_debug(...) ((void)0)
static int fail_at,dependency_result,graph,dependency,registered,started,deleted;
static void sipa_dele_cons_notify_cb(void) {}
static int sipa_rm_create_resource(struct sipa_rm_create_params *p) {
 assert(!started);if(fail_at==1)return -ENOMEM;graph=1;return 0;
}
static int sipa_rm_add_dependency(int consumer,int producer) {
 assert(graph&&!started);if(fail_at==2)return -EINVAL;dependency=1;return dependency_result;
}
static int sipa_rm_register(int consumer,struct sipa_rm_register_params *p) {
 assert(graph&&dependency&&!started&&p->notify_cb);if(fail_at==3)return -ENOMEM;registered=1;return 0;
}
static void wake_up_process(int thread) {
 /* Model a CP message processed synchronously at the first wake-up. */
 assert(graph&&dependency&&registered);started++;
}
static void sipa_rm_delete_resource(int producer) { assert(!started);deleted++;graph=dependency=0; }
'''
        checks = r'''
int main(void) {
 struct sipa_delegator d={0};
 for(int pass=0;pass<2;pass++) {
  dependency_result=pass ? -EINPROGRESS : 0;
  for(fail_at=0;fail_at<4;fail_at++) {
   graph=dependency=registered=started=deleted=0;
   int ret=sipa_delegator_start(&d);
   if(!fail_at)assert(!ret&&started==1&&!deleted);
   else assert(ret<0&&!started&&deleted==(fail_at!=1));
  }
 }
 return 0;
}
'''
        self.run_c(model+function(source,'sipa_delegator_start')+checks)

    def test_kernel_wait_ready_failed_timeout_interrupted_and_close_race(self):
        source = (DELE/'sipa_dele_cp_in_ap.c').read_text()
        model = r'''
#include <assert.h>
#include <stdio.h>
#include <errno.h>
#include <stdarg.h>
typedef long ssize_t;
struct device { int unused; };struct device_attribute { int unused; };
struct sipa_delegator { int channel_status,channel_wait; };
struct wrapper { struct sipa_delegator delegator; } instance;
static struct wrapper *s_cp_delegator=&instance;
static int waits,next_status;static long wait_result;
static int atomic_read(int *value) { return *value; }
static unsigned msecs_to_jiffies(unsigned value) { return value; }
static long do_wait(unsigned timeout) {
 assert(timeout==3000);waits++;instance.delegator.channel_status=next_status;return wait_result;
}
#define wait_event_interruptible_timeout(queue,condition,timeout) ((condition) ? 1 : do_wait(timeout))
static int sysfs_emit(char *buf,const char *format,...) {
 va_list a;va_start(a,format);int n=vsprintf(buf,format,a);va_end(a);return n;
}
'''
        checks = r'''
int main(void) {
 char buf[40];
 instance.delegator.channel_status=1;
 assert(sipa_dele_wait_show(0,0,buf)==2&&!waits&&!strcmp(buf,"1\n"));
 instance.delegator.channel_status=-ENODEV;
 assert(sipa_dele_wait_show(0,0,buf)==-ENODEV&&!waits);
 for(int pass=0;pass<5;pass++) {
  instance.delegator.channel_status=0;next_status=1;wait_result=1;
  if(pass==1)wait_result=0;
  if(pass==2)wait_result=-EINTR;
  if(pass==3)next_status=-EIO;
  if(pass==4)next_status=0;
  long ret=sipa_dele_wait_show(0,0,buf);
  long expected[]={2,-ETIMEDOUT,-EINTR,-EIO,-EAGAIN};
  assert(ret==expected[pass]&&waits==pass+1);
 }
 instance.delegator.channel_status=0;
 assert(sipa_dele_ready_show(0,0,buf)==2&&!strcmp(buf,"0\n"));
 instance.delegator.channel_status=-19;
 assert(sipa_dele_ready_show(0,0,buf)==4&&!strcmp(buf,"-19\n"));
 return 0;
}
'''
        self.run_c(model+'\n#include <string.h>\n'+function(source,'sipa_dele_ready_show')+
                   function(source,'sipa_dele_wait_show')+checks)

    def test_connection_status_tracks_open_close_error_and_reopen(self):
        source = (DELE/'sipa_dele_cmn.c').read_text()
        model = r'''
#include <assert.h>
#include <stdbool.h>
#include <errno.h>
#define pr_info(...) ((void)0)
#define pr_err(...) ((void)0)
enum { SMSG_TYPE_OPEN=1,SMSG_TYPE_CLOSE,SMSG_TYPE_CMD,SMSG_TYPE_DONE,SMSG_TYPE_EVENT };
struct smsg { int channel,type,flag,value; };
struct sipa_delegator {
 int dst,chan,channel_status,channel_wait,thread_value,*thread,smsg_cnt;
 bool connected;
 void (*on_open)(void*,int,int),(*on_close)(void*,int,int),(*on_cmd)(void*,int,int),(*on_done)(void*,int,int),(*on_evt)(void*,int,int);
};
static int step,open_error,nopens,ncloses,commands,wakes;
static struct sipa_delegator *current;
static int atomic_xchg(int *p,int v) { int old=*p;*p=v;return old; }
static void wake_up_interruptible_all(int *wait) { wakes++; }
static int smsg_ch_open(int dst,int ch,int timeout) { return open_error; }
static int kthread_should_stop(void) { return step>=6; }
static void usleep_range(int low,int high) {}
static void smsg_set(struct smsg *m,int channel,int type,int flag,int value) { m->channel=channel;m->type=type; }
static int smsg_recv(int dst,struct smsg *m,int timeout) {
 step++;
 switch(step) {
 case 1:m->type=SMSG_TYPE_CLOSE;break;
 case 2:assert(!current->channel_status&&!current->connected);return -EIO;
 case 3:m->type=SMSG_TYPE_OPEN;break;
 case 4:assert(current->channel_status==1&&current->connected);return -EINTR;
 case 5:assert(current->channel_status==1&&current->connected);m->type=SMSG_TYPE_CMD;break;
 default:m->type=SMSG_TYPE_EVENT;break;
 }
 return 0;
}
static void smsg_open_ack(int dst,int ch) {}
static void smsg_close_ack(int dst,int ch) {}
static void on_open(void *d,int flag,int value) { assert(((struct sipa_delegator*)d)->connected);nopens++; }
static void on_close(void *d,int flag,int value) { assert(!((struct sipa_delegator*)d)->connected);ncloses++; }
static void on_message(void *d,int flag,int value) { commands++; }
'''
        checks = r'''
int main(void) {
 struct sipa_delegator d={.thread_value=1,.on_open=on_open,.on_close=on_close,.on_cmd=on_message,.on_done=on_message,.on_evt=on_message};
 d.thread=&d.thread_value;current=&d;
 assert(!conn_thread(&d));assert(nopens==2&&ncloses==1&&commands==2&&wakes==3);
 step=0;open_error=-ENODEV;d.channel_status=0;
 assert(conn_thread(&d)==-ENODEV&&d.channel_status==-ENODEV&&!d.thread);
 assert(nopens==2&&ncloses==1&&commands==2);
 return 0;
}
'''
        self.run_c(model+function(source,'sipa_dele_channel_status')+function(source,'conn_thread')+checks)

    def test_every_pdp_setup_rechecks_the_kernel_gate_including_loaded_modules(self):
        source = (TOP/'rootfs/overlay/opt/mu300/bin/mobile-data').read_text()
        start = source.index('    _m=/lib/modules/$(uname -r)', source.index('up_locked()'))
        end = source.index('    configure_pdp_context', start)
        gate = source[start:end]
        self.assertIn('/opt/mu300/bin/sipa-dele-start', gate)
        self.assertNotIn("! grep -q '^sipa_dele '", gate)
        loader = (TOP/'rootfs/overlay/opt/mu300/bin/sipa-dele-start').read_text()
        self.assertNotIn('dmesg |', loader)
        self.assertIn('sipa_dele_wait', loader)


class DelegateSetup(ShellTest):
    def test_real_setup_gate_cannot_reach_pdp_before_ready(self):
        source = (BIN/'mobile-data').read_text()
        start = source.index('    _m=/lib/modules/$(uname -r)', source.index('up_locked()'))
        end = source.index('    configure_pdp_context', start)
        root = self.tmp/'modules';root.mkdir();(root/'sipa-dele.ko').touch()
        loaded = self.tmp/'loaded'
        self.stub('gate', '''echo gate >> "$STUBLOG/trace"
[ "$MU300_DELE_WAIT" = 20 ] || exit 99
[ "${MARK_LOADED:-1}" != 1 ] || echo 'sipa_dele 123 0' > "$STUBLOG/loaded"
[ "$READY" = 1 ]
''')
        block = source[start:end].replace('/lib/modules/$(uname -r)',str(root))
        block = block.replace('/opt/mu300/bin/sipa-dele-start',str(self.stubs/'gate'))
        block = block.replace('/proc/modules',str(loaded)).replace('/tmp/mu300-sipa-dele.log',str(self.tmp/'gate.log'))
        code = 'setup() {\n'+block+'echo PDP >> "$STUBLOG/trace"\n}\nsetup\n'
        for shell in self.each_shell():
            for already_loaded in (0,1):
                for ready in (0,1):
                    loaded.write_text('sipa_dele 123 0\n' if already_loaded else '')
                    trace=self.tmp/'trace';trace.write_text('')
                    result=self.sh(shell,code,READY=ready)
                    self.assertEqual(result.returncode==0,bool(ready),result.stderr)
                    self.assertEqual(trace.read_text().splitlines(),['gate','PDP'] if ready else ['gate'])
            loaded.write_text('');(self.tmp/'trace').write_text('')
            result=self.sh(shell,code,READY=1,MARK_LOADED=0)
            self.assertNotEqual(result.returncode,0)
            self.assertEqual((self.tmp/'trace').read_text().splitlines(),['gate'])
