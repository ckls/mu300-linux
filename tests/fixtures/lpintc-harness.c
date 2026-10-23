/* Execute the production module against private MMIO and kernel API fixtures.
 * No /dev/mem, kernel module loading or host register access. */
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define __iomem
#define __init
#define __exit
#define BIT(n) (1U << (n))
#define HZ 100
#define module_param(...)
#define MODULE_PARM_DESC(...)
#define MODULE_LICENSE(...)
#define MODULE_DESCRIPTION(...)
#define module_init(...)
#define module_exit(...)
#define pr_info(...) ((void)0)
#define pr_warn(...) ((void)0)
#define DEFINE_SPINLOCK(n) int n
#define spin_lock_irqsave(lock, flags) ((void)(lock), (flags) = 0)
#define spin_unlock_irqrestore(lock, flags) ((void)(lock), (void)(flags))
typedef uint32_t u32;
typedef uintptr_t phys_addr_t;
struct device_node { int unused; };
struct work_struct { int unused; };
struct delayed_work { void (*fn)(struct work_struct *); int deferrable; };
struct syscore_ops { int (*suspend)(void *); void (*resume)(void *); };
struct syscore { const struct syscore_ops *ops; };

static u32 gic_regs[128], intc_regs[8][4], gate_reg;
static const uintptr_t bases[] = {
    0x640c0000, 0x640d0000, 0x640e0000, 0x640f0000,
    0x64100000, 0x64110000, 0x645b0000, 0x645c0000
};
static int compatible = 1, has_gic = 1, bad_gic_map, bad_gate_map;
static int bad_block = -1, maps, unmaps, writes, queues, registered, cancelled;
static unsigned long queued_delay;
static void *system_power_efficient_wq = (void *)1;
static struct device_node node;
static int of_machine_is_compatible(const char *s)
{ assert(!strcmp(s, "sprd,ums9620")); return compatible; }
static struct device_node *of_find_compatible_node(void *a, void *b, const char *s)
{ (void)a; (void)b; assert(!strcmp(s,"arm,gic-v3")); return has_gic ? &node : NULL; }
static void of_node_put(struct device_node *n) { assert(n == &node); }
static void *of_iomap(struct device_node *n, int index)
{ assert(n == &node && !index); if (bad_gic_map) return NULL; maps++; return gic_regs; }
static void *ioremap(uintptr_t address, unsigned size)
{
    if (address == 0x64900008) {
        assert(size == 4); if (bad_gate_map) return NULL; maps++; return &gate_reg;
    }
    for (int n=0; n<8; n++) if (address == bases[n]) {
        assert(size == 0x10); assert(gate_reg & BIT(11+n));
        if (n == bad_block) return NULL;
        maps++; return intc_regs[n];
    }
    assert(!"unexpected MMIO address"); return NULL;
}
static void iounmap(void *p) { assert(p); unmaps++; }
static u32 readl_relaxed(void *p) { return *(u32 *)p; }
static u32 readl(void *p) { return readl_relaxed(p); }
static void writel_relaxed(u32 value, void *p)
{
    for (int n=0; n<8; n++) {
        assert((gate_reg & BIT(11+n)) || (p != &intc_regs[n][2] && p != &intc_regs[n][3]));
        if (p == &intc_regs[n][2]) { intc_regs[n][2] |= value; writes++; return; }
        if (p == &intc_regs[n][3]) { intc_regs[n][2] &= ~value; writes++; return; }
    }
    assert(!"write outside INTC set/clear registers");
}
#define INIT_DEFERRABLE_WORK(w, cb) ((w)->fn = (cb), (w)->deferrable = 1)
static void queue_delayed_work(void *q, struct delayed_work *w, unsigned long delay)
{ assert(q == system_power_efficient_wq && w->deferrable); queues++; queued_delay = delay; }
static void cancel_delayed_work_sync(struct delayed_work *w)
{ assert(w->deferrable); cancelled++; }
static void register_syscore(struct syscore *s)
{ assert(s->ops->suspend && s->ops->resume); registered++; }
static void unregister_syscore(struct syscore *s)
{ assert(s->ops); assert(cancelled); registered--; }

#include "../../upstream/modules/ums9620_lpintc/ums9620_lpintc.c"

int main(int argc, char **argv)
{
    assert(argc == 2);
    gate_reg = 0x7f800;
    if (!strcmp(argv[1], "lifecycle")) {
        u32 original[8] = {0xf5085c00, 0x2080b9fc, 0, 0, 0, 0, 0, 0x40};
        for (int n=0; n<8; n++) intc_regs[n][2] = original[n];
        gic_regs[0x104/4 + 4] = BIT(14) | BIT(8); /* USB + IPA */
        gic_regs[0x104/4 + 6] = BIT(18); /* PCIe MSI */
        assert(lpintc_init() == 0 && registered == 1);
        assert(added[4] == (BIT(14)|BIT(8)) && added[6] == BIT(18));
        assert(queued_delay == 5*HZ && queues == 1);
        int first_writes = writes;
        lpintc_work.fn(NULL);
        assert(writes == first_writes && queues == 2); /* no repeated MMIO writes */
        gic_regs[0x104/4 + 4] = 0;
        gic_regs[0x104/4 + 2] = BIT(5); /* driver enabled later */
        lpintc_work.fn(NULL);
        assert(intc_regs[4][2] == (BIT(14)|BIT(8)) && added[2] == BIT(5));
        intc_regs[3][2] = BIT(1); /* an unrelated owner adds a bit after load */
        for (int i=0; i<3; i++) {
            assert(lpintc_syscore.ops->suspend(NULL) == 0);
            for (int n=0; n<8; n++)
                assert(intc_regs[n][2] == (original[n] | (n==3 ? BIT(1) : 0)));
            lpintc_syscore.ops->resume(NULL);
            for (int n=0; n<8; n++)
                assert(intc_regs[n][2] == (original[n] | added[n] | (n==3 ? BIT(1) : 0)));
        }
        lpintc_exit();
        assert(!registered && cancelled == 1 && maps == unmaps);
        for (int n=0; n<8; n++)
            assert(intc_regs[n][2] == (original[n] | (n==3 ? BIT(1) : 0)));
    } else if (!strcmp(argv[1], "clock-off")) {
        gate_reg &= ~BIT(15);
        gic_regs[0x104/4 + 4] = BIT(14);
        period = 0;
        assert(lpintc_init() == 0 && !intc[4] && !added[4]);
        assert(period == 1 && queued_delay == HZ && !writes);
        lpintc_exit(); assert(maps == unmaps);
    } else {
        int expected = -ENODEV;
        if (!strcmp(argv[1], "wrong-soc")) compatible = 0;
        else if (!strcmp(argv[1], "no-gic")) has_gic = 0;
        else if (!strcmp(argv[1], "all-clocks-off")) gate_reg = 0;
        else if (!strcmp(argv[1], "bad-gic")) { bad_gic_map=1; expected=-ENOMEM; }
        else if (!strcmp(argv[1], "bad-gate")) { bad_gate_map=1; expected=-ENOMEM; }
        else if (!strcmp(argv[1], "partial-map")) { bad_block=4; expected=-ENOMEM; }
        else assert(!"unknown scenario");
        assert(lpintc_init() == expected);
        assert(!writes && !registered && !queues && maps == unmaps);
    }
    puts("OK");
    return 0;
}
