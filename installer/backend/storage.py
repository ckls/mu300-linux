"""One topology/identity contract for eMMC and UFS installation paths."""
from pathlib import Path
import re
import sys


def disk_node(node):
    match = re.fullmatch(r'(mmcblk[0-9]+)p[1-9][0-9]*|(sd[a-z]+)[1-9][0-9]*', node)
    if not match:
        raise ValueError('Invalid internal partition / 内置分区节点无效: '+str(node))
    return match[1] or match[2]


def part_node(disk, number):
    if not re.fullmatch(r'mmcblk[0-9]+|sd[a-z]+', disk) or not isinstance(number,int) or number < 1:
        raise ValueError('Invalid disk/partition number / 磁盘或分区号无效')
    return disk+('p' if disk.startswith('mmcblk') else '')+str(number)


def library(root=None):
    # Explicit source/frozen/portable layouts of the same library. An old
    # installed OpenWrt need not contain this new helper to be updatable.
    if getattr(sys,'frozen',False):
        path=Path(sys._MEIPASS)/'storage.sh'
    elif Path(__file__).parent.name == 'backend':
        path=Path(__file__).resolve().parents[2]/'rootfs/overlay/opt/mu300/lib/storage.sh'
    else:
        path=Path(__file__).with_name('storage-lib.sh')
    return path.read_text(encoding='utf-8')


def inventory_script(root):
    return library(root)+r'''
set -e
d=$(readlink -f /dev/block/by-name/userdata)
n=${d##*/}
b=$(mu300_storage_parent "$n")
[ "$(mu300_storage_part userdata "$b")" = "$n" ]
echo NODE=$n
echo DISK=$b
echo STORAGE_KIND=$(mu300_storage_kind "$b")
echo CID=$(mu300_storage_identity "$b")
echo SECTOR_SIZE=$(mu300_storage_sector_size "$b")
echo START=$(cat /sys/class/block/$n/start)
echo SIZE=$(cat /sys/class/block/$n/size)
echo DISK_SIZE=$(cat /sys/class/block/$b/size)
echo FREE=$(df -Pk /data | tail -n1 | awk '{print $4}')
echo STATE=$(getprop ro.crypto.state)
echo TYPE=$(getprop ro.crypto.type)
echo SOURCE=$(awk '$2=="/data" {print $1;exit}' /proc/mounts)
echo MAGIC=$(dd if="$d" bs=1 skip=1024 count=4 2>/dev/null | od -An -tx1 | tr -d ' \n')
echo EXT=$(dd if="$d" bs=1 skip=1080 count=2 2>/dev/null | od -An -tx1 | tr -d ' \n')
for label in mu300root e5root; do
    candidate=$(mu300_storage_part "$label" "$b") || continue
    echo ROOT=$candidate
done
'''


def parse_inventory(text):
    result = dict(line.split('=',1) for line in text.splitlines() if '=' in line)
    disk = disk_node(result['NODE'])
    if result.get('DISK',disk) != disk or not re.fullmatch('[a-f0-9]{32}',result.get('CID','')):
        raise ValueError('Cannot establish storage identity / 无法确认存储身份')
    kind = result.get('STORAGE_KIND','emmc')
    if kind not in ('emmc','ufs') or (kind == 'emmc') != disk.startswith('mmcblk'):
        raise ValueError('Storage type/topology differs / 存储类型与拓扑不匹配')
    result['DISK'] = disk
    result['STORAGE_KIND'] = kind
    result['SECTOR_SIZE'] = int(result.get('SECTOR_SIZE',512))
    if result['SECTOR_SIZE'] not in (512,4096):
        raise ValueError('Unsupported storage logical block size / 不支持的存储逻辑块大小')
    for key in ('START','SIZE','DISK_SIZE','FREE'):
        result[key] = int(result[key])
        if result[key] < 0:
            raise ValueError('Invalid storage geometry / 存储范围无效')
    factor = result['SECTOR_SIZE']//512
    if any(result[key] % factor for key in ('START','SIZE','DISK_SIZE')):
        raise ValueError('Storage alignment differs / 存储对齐不匹配')
    if not result['SIZE'] or result['START']+result['SIZE'] > result['DISK_SIZE']:
        raise ValueError('Partition exceeds its disk / 分区超出所在磁盘范围')
    if result.get('ROOT') and disk_node(result['ROOT']) != disk:
        raise ValueError('Root is on another disk / 根分区不在同一磁盘')
    return result


def gpt_header_commands(info, prefix='/dev/block/'):
    disk = prefix+disk_node(info['NODE'])
    block = info.get('SECTOR_SIZE',512)
    return (f'dd if={disk} bs={block} skip=1 count=1 2>/dev/null',
            f'dd if={disk} bs={block} skip={info["DISK_SIZE"]//(block//512)-1} count=1 2>/dev/null')


def runtime_identity_script():
    return library()+'\nd=$(mu300_storage_disk) && mu300_storage_identity "$d"'
