"""Compile the actual NCM timer callback and exercise USB request exhaustion.

Input is a registered kernel tree (read only). No device or full build needed.
"""
from pathlib import Path
import runpy
import os
import resource
import subprocess
import sys
import tempfile

name = 'drivers/usb/gadget/function/f_ncm.c'
here = Path(__file__).resolve().parent
with tempfile.TemporaryDirectory(prefix='ncm-timer-test-') as directory:
    root = Path(directory)
    path = root/name
    path.parent.mkdir(parents=True)
    path.write_bytes((Path(sys.argv[1])/name).read_bytes())
    helper = here/'usb-ncm.py'
    if helper.exists():
        apply = runpy.run_path(str(helper))['apply']
        apply(root)
        first = path.read_bytes()
        apply(root)
        assert path.read_bytes() == first, 'prepare must be idempotent'
    else:
        patch = here.parent/'upstream/patches/0025-usb-ncm-retry-busy-timer-flush.patch'
        args = ['patch', '-p1', '--batch', '-i', str(patch)]
        if subprocess.run(args+['--forward', '--dry-run'], cwd=root, capture_output=True).returncode == 0:
            subprocess.run(args+['--forward'], cwd=root, check=True)
        else:
            # The normal kernel build has already applied this patch.
            subprocess.run(args+['-R', '--dry-run'], cwd=root, check=True,
                           stdout=subprocess.DEVNULL)

    source = path.read_text()
    start = source.index('static enum hrtimer_restart ncm_tx_timeout(struct hrtimer *data)\n{')
    callback = source[start:source.index('\n}', start)+2]
    code = r'''
#include <assert.h>
#include <stddef.h>
#define READ_ONCE(x) (x)
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define TX_TIMEOUT_NSECS 300000
#define NETDEV_TX_OK 0
#define NETDEV_TX_BUSY 16
typedef int netdev_tx_t;
enum hrtimer_restart {HRTIMER_NORESTART, HRTIMER_RESTART};
struct hrtimer {long long expires, now;};
struct net_device;
struct net_device_ops {netdev_tx_t (*ndo_start_xmit)(void *,struct net_device *);};
struct net_device {struct net_device_ops *netdev_ops;};
struct f_ncm {struct hrtimer task_timer;struct net_device *netdev;};
static int calls, forwards, result;
static netdev_tx_t xmit(void *skb,struct net_device *net){
    assert(!skb && net);++calls;return result;
}
static void hrtimer_forward_now(struct hrtimer *timer,long long interval){
    assert(interval==300000);++forwards;timer->expires=timer->now+interval;
}
''' + callback + r'''
int main(void){
    struct net_device_ops ops={xmit};struct net_device net={&ops};
    struct f_ncm ncm={.task_timer={0,1000000},.netdev=&net};
    /* No data transfer / no attached netdev: no wakeup or periodic retry. */
    ncm.netdev=NULL;assert(ncm_tx_timeout(&ncm.task_timer)==HRTIMER_NORESTART);
    assert(!calls&&!forwards);ncm.netdev=&net;
    result=NETDEV_TX_OK;assert(ncm_tx_timeout(&ncm.task_timer)==HRTIMER_NORESTART);
    assert(calls==1&&!forwards);
    /* Even prolonged request exhaustion must move expiration into the future. */
    result=NETDEV_TX_BUSY;
    for(int i=0;i<10000;++i){
        assert(ncm_tx_timeout(&ncm.task_timer)==HRTIMER_RESTART);
        assert(ncm.task_timer.expires>ncm.task_timer.now);
        ncm.task_timer.now=ncm.task_timer.expires+123;
    }
    assert(calls==10001&&forwards==10000);
    /* Completion ends retry immediately, followed by disconnect. */
    result=NETDEV_TX_OK;assert(ncm_tx_timeout(&ncm.task_timer)==HRTIMER_NORESTART);
    ncm.netdev=NULL;assert(ncm_tx_timeout(&ncm.task_timer)==HRTIMER_NORESTART);
    assert(calls==10002&&forwards==10000);
    return 0;
}
'''
    flags = ['-fsanitize=address,undefined', '-fno-omit-frame-pointer'] if os.environ.get('NCM_TEST_SANITIZE') == '1' else []
    (root/'test.c').write_text(code)
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', *flags, str(root/'test.c'), '-o', str(root/'test')], check=True)
    subprocess.run([str(root/'test')], check=True)
    print('NCM busy -> retry -> complete/disconnect: PASS (10000 busy cycles)')
    # Negative control: removing the actual fix must reproduce the failed flush.
    import re
    broken = re.sub(r'\t\tif \(netdev->netdev_ops->ndo_start_xmit\(NULL, netdev\) == NETDEV_TX_BUSY\) \{.*?\n\t\t\}',
                    '\\t\\tnetdev->netdev_ops->ndo_start_xmit(NULL, netdev);', callback, flags=re.S)
    assert broken != callback, 'negative control did not remove the fix'
    (root/'old.c').write_text(code.replace(callback, broken))
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function', str(root/'old.c'), '-o', str(root/'old')], check=True)
    failed = subprocess.run([str(root/'old')], capture_output=True,
                            preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_CORE, (0, 0)))
    assert failed.returncode != 0 and b'HRTIMER_RESTART' in failed.stderr, failed.stderr
    print('Unfixed callback reproduces lost BUSY flush: PASS (expected assertion failure)')

    # Exercise the real USB Ethernet request-list and completion code, not just
    # a mocked NETDEV_TX_BUSY return. NTB bytes themselves are not modeled.
    ether = (Path(sys.argv[1])/name.replace('f_ncm.c', 'u_ether.c')).read_text()
    def function(text, signature):
        begin = text.index(signature)
        return text[begin:text.index('\n}', begin)+2]
    queue_code = (here/'ncm-tx-fixture.h').read_text()
    for signature in ('static void tx_complete(', 'static inline int is_promisc(',
                      'static netdev_tx_t eth_start_xmit('):
        queue_code += '\n' + function(ether, signature)
    queue_code += '\n' + callback
    queue_code += r'''
int main(void){
    struct net_device_ops ops={eth_start_xmit};
    struct net_device net={.netdev_ops=&ops,.carrier=true};
    struct usb_ep ep={.maxpacket=512};
    struct gether port={.in_ep=&ep,.cdc_filter=USB_CDC_PACKET_TYPE_PROMISCUOUS,
                       .supports_multi_frame=true};
    struct eth_dev dev={.port_usb=&port,.wrap=wrap,.net=&net,.zlp=true};
    struct usb_request req={0};struct f_ncm ncm={.netdev=&net};
    net.priv=&dev;ep.driver_data=&dev;init_list(&dev.tx_reqs);
    /* No request: aggregation and normal skb ownership must be retained. */
    pending=1;packet=(struct sk_buff){.len=100};
    assert(eth_start_xmit(&packet,&net)==NETDEV_TX_BUSY);
    assert(!packet.released&&!wrap_calls);
    assert(ncm_tx_timeout(&ncm.task_timer)==HRTIMER_RESTART);
    assert(pending==1&&!wrap_calls&&!ep.inflight&&forwards==1);
    /* A real request returns; no new network packet is needed to flush. */
    list_add(&req.list,&dev.tx_reqs);
    assert(ncm_tx_timeout(&ncm.task_timer)==HRTIMER_NORESTART);
    assert(!pending&&ep.inflight==&req&&dev.tx_qlen==1&&net.stopped);
    ep.inflight=NULL;req.status=0;req.complete(&ep,&req);
    assert(!net.stopped&&!dev.tx_qlen&&net.stats.tx_packets==1&&net.stats.tx_bytes==100);
    assert(!list_empty(&dev.tx_reqs)&&ntb.released);
    /* Successful aggregation returns its unused USB request immediately. */
    assert(eth_start_xmit(&packet,&net)==NETDEV_TX_OK);
    assert(packet.released&&pending==1&&!list_empty(&dev.tx_reqs)&&!net.stopped);
    assert(!net.stats.tx_dropped);
    assert(ncm_tx_timeout(&ncm.task_timer)==HRTIMER_NORESTART);
    ep.inflight=NULL;req.status=-ESHUTDOWN;req.complete(&ep,&req);
    assert(!dev.tx_qlen&&ntb.released&&!list_empty(&dev.tx_reqs));
    /* Endpoint submission errors keep request accounting and free NTB once. */
    ep_result=-EIO;pending=1;
    long drops=net.stats.tx_dropped;
    assert(ncm_tx_timeout(&ncm.task_timer)==HRTIMER_NORESTART);
    assert(!pending&&ntb.released&&!dev.tx_qlen&&!list_empty(&dev.tx_reqs));
    assert(net.stats.tx_dropped==drops+1);ep_result=0;
    /* Another xmit may have drained aggregation before the retry runs. */
    pending=0;int before=forwards;
    assert(ncm_tx_timeout(&ncm.task_timer)==HRTIMER_NORESTART);
    assert(forwards==before&&!list_empty(&dev.tx_reqs)&&!net.stopped);
    /* Generic suspended gether returns BUSY without consuming data. */
    port.is_suspend=true;pending=1;
    assert(ncm_tx_timeout(&ncm.task_timer)==HRTIMER_RESTART);
    assert(pending==1&&wakeups==1&&!ep.inflight);
    port.is_suspend=false;
    assert(ncm_tx_timeout(&ncm.task_timer)==HRTIMER_NORESTART);
    ep.inflight=NULL;req.status=0;req.complete(&ep,&req);
    /* Disconnect after a busy callback: next retry must stop. */
    list_del(&req.list);pending=1;
    assert(ncm_tx_timeout(&ncm.task_timer)==HRTIMER_RESTART);
    ncm.netdev=NULL;dev.port_usb=NULL;net.carrier=false;before=forwards;
    assert(ncm_tx_timeout(&ncm.task_timer)==HRTIMER_NORESTART);
    assert(forwards==before&&!ep.inflight);
    /* A stale callback holding the still-live netdev sees port=NULL. */
    ncm.netdev=&net;
    assert(ncm_tx_timeout(&ncm.task_timer)==HRTIMER_NORESTART);
    assert(forwards==before);
    return 0;
}
'''
    (root/'queue.c').write_text(queue_code)
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', *flags,
                    str(root/'queue.c'), '-o', str(root/'queue')], check=True)
    subprocess.run([str(root/'queue')], check=True)
    print('Production u_ether TX/completion + NCM timer lifecycle: PASS')
