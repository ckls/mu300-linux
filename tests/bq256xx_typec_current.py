"""Compile the production Type-C current reader with isolated PMIC/DT fixtures."""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

path=Path(sys.argv[1])
source=(path if path.is_file() else path/'drivers/power/supply/bq256xx_charger.c').read_text()
start=re.search(r'^static int bq2560x_chg_typec_iindpm\(',source,re.M).start()
end=source.index('{',start)+1
depth=1
while depth:
    depth+=(source[end]=='{')-(source[end]=='}');end+=1
function=source[start:end]
code=r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <errno.h>
typedef uint32_t u32;
#define GENMASK(h,l) (((1u<<((h)-(l)+1))-1)<<(l))
#define FIELD_GET(mask,val) (((val)&(mask))>>__builtin_ctz(mask))
#define UMP9620_TYPEC_STATUS 0x1c
#define UMP9620_TYPEC_STATE GENMASK(4,0)
#define UMP9620_TYPEC_ATTACHWAIT_SNK 1
#define UMP9620_TYPEC_ATTACHED_SNK 2
#define UMP9620_TYPEC_RP GENMASK(7,6)
struct device_node {int dummy;};
struct regmap {int dummy;};
struct device {struct device_node*of_node;};
struct bq256xx_device {struct device*pmic;};
static struct regmap map;
static struct device_node node;
static struct device dev={&node};
static unsigned status,after_debounce;
static bool node_present=true,map_present=true;
static int io_error,dt_error,poll_error;
static struct regmap* dev_get_regmap(struct device*d,void*p){(void)d;(void)p;return map_present?&map:NULL;}
static struct device_node*of_get_compatible_child(struct device_node*n,const char*c){(void)n;(void)c;return node_present?&node:NULL;}
static void of_node_put(struct device_node*n){(void)n;}
static int of_property_read_u32(struct device_node*n,const char*p,u32*base){(void)n;(void)p;*base=0x380;return dt_error;}
static int regmap_read(struct regmap*m,unsigned addr,unsigned*out){(void)m;assert(addr==0x39c);*out=status;return io_error;}
#define regmap_read_poll_timeout(m,a,out,cond,delay,timeout) ((out)=after_debounce,poll_error)
'''+function+r'''
int main(void){
 struct bq256xx_device b={&dev};unsigned raw;
 for(unsigned state=0;state<32;state++)for(unsigned rp=0;rp<4;rp++){
  status=state|(rp<<6);after_debounce=status;
  int expected=state==2?(rp==1?1500000:rp==2?3000000:0):0;
  assert(bq2560x_chg_typec_iindpm(&b,&raw)==expected);
 }
 /* No permission to source 3 A is inferred from a failed or missing read. */
 status=2|(2<<6);io_error=-EIO;assert(!bq2560x_chg_typec_iindpm(&b,&raw));io_error=0;
 dt_error=-EINVAL;assert(!bq2560x_chg_typec_iindpm(&b,&raw));dt_error=0;
 node_present=false;assert(!bq2560x_chg_typec_iindpm(&b,&raw));node_present=true;
 map_present=false;assert(!bq2560x_chg_typec_iindpm(&b,&raw));map_present=true;
 b.pmic=NULL;assert(!bq2560x_chg_typec_iindpm(&b,&raw));b.pmic=&dev;
 status=1;after_debounce=2|(2<<6);
 assert(bq2560x_chg_typec_iindpm(&b,&raw)==3000000);
 poll_error=-ETIMEDOUT;assert(!bq2560x_chg_typec_iindpm(&b,&raw));
 return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='bq-typec-current-') as temp:
    root=Path(temp);(root/'test.c').write_text(code)
    subprocess.run(['cc','-Wall','-Werror',str(root/'test.c'),'-o',str(root/'test')],check=True)
    subprocess.run([str(root/'test')],check=True)
print('PASS: 128 state/Rp combinations, source 3 A permission, missing data, I/O errors and debounce timeout')
