/* Userspace fixture for the production eth_start_xmit/tx_complete callbacks.
 * USB completions are scheduled explicitly; this is not a kernel race test.
 * NTB encoding and checksum repair are outside this queue-ownership fixture.
 */
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdlib.h>
#include <errno.h>
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define READ_ONCE(x) (x)
#define TX_TIMEOUT_NSECS 300000
#define NETDEV_TX_OK 0
#define NETDEV_TX_BUSY 16
#define GFP_ATOMIC 0
#define USB_CDC_PACKET_TYPE_PROMISCUOUS 1
#define USB_CDC_PACKET_TYPE_BROADCAST 2
#define USB_CDC_PACKET_TYPE_ALL_MULTICAST 4
#define DBG(...) ((void)0)
#define VDBG(...) ((void)0)
#define fallthrough __attribute__((fallthrough))
#define spin_lock_irqsave(lock,flags) ((void)(lock),(flags)=0)
#define spin_unlock_irqrestore(lock,flags) ((void)(lock),(void)(flags))
#define spin_lock(lock) ((void)(lock))
#define spin_unlock(lock) ((void)(lock))
#define ether_complete_pseudo_csum(skb) ((void)(skb))
typedef unsigned char u8;
typedef unsigned short u16;
typedef int netdev_tx_t;
enum hrtimer_restart {HRTIMER_NORESTART,HRTIMER_RESTART};
struct list_head {struct list_head *next,*prev;};
static void init_list(struct list_head *h){h->next=h->prev=h;}
static int list_empty(struct list_head *h){return h->next==h;}
static void list_add(struct list_head *e,struct list_head *h){
    e->next=h->next;e->prev=h;h->next->prev=e;h->next=e;
}
static void list_del(struct list_head *e){e->prev->next=e->next;e->next->prev=e->prev;}
#define list_first_entry(h,t,m) container_of((h)->next,t,m)
struct sk_buff {int len;u8 data[1500];int released;};
struct usb_ep;
struct usb_request {
    struct list_head list;void *buf,*context;
    void (*complete)(struct usb_ep *,struct usb_request *);
    int zero,length,status;
};
struct usb_ep {int maxpacket;void *driver_data;struct usb_request *inflight;};
struct gether {struct usb_ep *in_ep;u16 cdc_filter;bool is_suspend,supports_multi_frame,is_fixed;int fixed_in_len;};
struct net_device;
struct net_device_ops {netdev_tx_t (*ndo_start_xmit)(struct sk_buff *,struct net_device *);};
struct net_device {
    void *priv;struct net_device_ops *netdev_ops;bool stopped,carrier;
    struct {long tx_errors,tx_bytes,tx_packets,tx_dropped;} stats;
};
struct eth_dev {
    int lock,req_lock,tx_qlen;struct gether *port_usb;struct list_head tx_reqs;
    struct sk_buff *(*wrap)(struct gether *,struct sk_buff *);
    struct net_device *net;bool zlp;
};
struct hrtimer {long long now,expires;};
struct f_ncm {struct hrtimer task_timer;struct net_device *netdev;};
static struct sk_buff ntb,packet;
static int pending,wrap_calls,ep_result,wakeups,freed,forwards;
static void *netdev_priv(struct net_device *n){return n->priv;}
static void netif_stop_queue(struct net_device *n){n->stopped=true;}
static void netif_start_queue(struct net_device *n){n->stopped=false;}
static void netif_wake_queue(struct net_device *n){n->stopped=false;}
static int netif_carrier_ok(struct net_device *n){return n->carrier;}
static void netif_trans_update(struct net_device *n){(void)n;}
static void atomic_inc(int *p){++*p;}
static void atomic_dec(int *p){--*p;}
static int ether_wakeup_host(struct gether *p){assert(p);++wakeups;return 0;}
static int is_multicast_ether_addr(u8 *p){return *p&1;}
static int is_broadcast_ether_addr(u8 *p){return *p==255;}
static void release(struct sk_buff *s){assert(s&&!s->released);s->released=1;++freed;}
#define dev_kfree_skb_any(s) release(s)
#define dev_consume_skb_any(s) release(s)
static int usb_ep_queue(struct usb_ep *ep,struct usb_request *r,int flags){
    (void)flags;if(ep_result)return ep_result;
    assert(!ep->inflight);ep->inflight=r;return 0;
}
static void hrtimer_forward_now(struct hrtimer *t,long long interval){
    assert(interval==300000);t->expires=t->now+interval;++forwards;
}
static struct sk_buff *wrap(struct gether *p,struct sk_buff *skb){
    (void)p;++wrap_calls;
    if(skb){release(skb);++pending;return NULL;}
    if(!pending)return NULL;
    ntb=(struct sk_buff){.len=pending*100};pending=0;return &ntb;
}
