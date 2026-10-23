"""Exercise the actual unbind descriptor cleanup from a read-only kernel tree."""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

TOP=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='mu300-usb-unbind-') as folder:
    root=Path(folder)
    for name in ['f_ncm.c','f_rndis.c']:
        path=root/'drivers/usb/gadget/function'/name
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes((Path(sys.argv[1])/'drivers/usb/gadget/function'/name).read_bytes())
    patch=TOP/'upstream/patches/0025-usb-gadget-ncm-rndis-os-desc-table-double-free.patch'
    cmd=['patch','-p1','--batch','-i',str(patch)]
    if subprocess.run(cmd+['--forward','--dry-run'],cwd=root,capture_output=True).returncode==0:
        subprocess.run(cmd+['--forward'],cwd=root,check=True)
    else:
        subprocess.run(cmd+['-R','--dry-run'],cwd=root,check=True)
    for name,function in [('f_ncm.c','ncm_unbind'),('f_rndis.c','rndis_unbind')]:
        text=(root/'drivers/usb/gadget/function'/name).read_text()
        start=text.index('static void '+function+'(')
        body=text[start:text.index('\n}',start)]
        cleanup=re.search(r'kfree\(f->os_desc_table\);\s*f->os_desc_table = NULL;\s*f->os_desc_n = 0;',body)
        assert cleanup, 'missing lifecycle cleanup: '+name
        source=root/'test.c'
        source.write_text(r'''
#include <assert.h>
#include <stddef.h>
struct usb_function { void *os_desc_table; int os_desc_n; };
static int frees;
static void kfree(void *p) {if(p){assert(++frees==1);}}
static void unbind(struct usb_function *f) {
'''+cleanup[0]+r'''
}
int main(void) {
    struct usb_function f={.os_desc_table=(void*)1,.os_desc_n=1};
    unbind(&f); assert(!f.os_desc_table && !f.os_desc_n && frees==1);
    /* Rebind with OS descriptors disabled: no new allocation, then unbind. */
    unbind(&f); assert(frees==1);
    return 0;
}
''')
        binary=root/'test'
        subprocess.run(['gcc','-O2','-Wall','-Wextra','-Werror',str(source),'-o',str(binary)],check=True)
        subprocess.run([str(binary)],check=True)
        print(name+': descriptor-enabled unbind, disabled rebind and second unbind passed')
