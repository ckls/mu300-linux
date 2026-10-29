"""UFS geometry uses real logical blocks while public offsets remain 512B."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import uuid
import zlib

from helpers import TOP, ShellTest
sys.path.insert(0,str(TOP))
from installer.backend import gpt, storage, uninstall


def snapshot(block, sectors=64*2097152):
    factor=block//512;total=sectors//factor;count=128;rows=(count*128+block-1)//block
    table=bytearray(count*128)
    for number,name,start,end in ((1,'misc',2048,4095),(2,'userdata',4096,16*2097152-1)):
        e=bytearray(128);e[:16]=uuid.UUID('0fc63daf-8483-4772-8e79-3d69d8477de4').bytes_le
        e[16:32]=uuid.UUID(int=number).bytes_le
        struct.pack_into('<QQ',e,32,start//factor,(end+1)//factor-1)
        text=name.encode('utf-16-le');e[56:56+len(text)]=text;table[(number-1)*128:number*128]=e
    def header(at,other,entries):
        h=bytearray(block);h[:8]=b'EFI PART';struct.pack_into('<II',h,8,0x10000,92)
        struct.pack_into('<QQQQ',h,24,at,other,2+rows,total-2-rows)
        h[56:72]=uuid.UUID(int=999).bytes_le
        struct.pack_into('<QIII',h,72,entries,count,128,zlib.crc32(table))
        struct.pack_into('<I',h,16,zlib.crc32(h[:92]));return h
    first=bytes(block)+header(1,total-1,2)+table
    last=table+header(total-1,1,total-1-rows)
    return first,last,sectors


class UfsGeometry(unittest.TestCase):
    def test_both_sector_sizes_share_public_geometry_and_roundtrip(self):
        for block in (512,4096):
            with self.subTest(block=block):
                first,last,total=snapshot(block);info=gpt.gpt_space(first,last,total)
                self.assertEqual(info['sector_size'],block)
                self.assertEqual(info['parts'][1]['start'],4096)
                self.assertEqual(info['parts'][1]['end'],16*2097152-1)
                start=20*2097152;need=8*2097152
                current=gpt.gpt_add_root(first,last,total,start,need)
                root=uninstall.partition(gpt.gpt_space(*current,total),'mu300root')
                self.assertEqual((root['start'],root['end']),(start,start+need-1))
                restored,_,_,wipe=uninstall.device_layout(current,total,'mu300root')
                self.assertFalse(wipe)
                self.assertEqual(restored,[first,last])

    def test_4kn_backup_commands_address_actual_last_lba(self):
        info=dict(NODE='sda75',DISK_SIZE=1999372288,SECTOR_SIZE=4096)
        a,b=storage.gpt_header_commands(info)
        self.assertIn('bs=4096 skip=1 ',a)
        self.assertIn('bs=4096 skip=249921535 ',b)

    def test_shrunk_userdata_uninstall_restores_both_sector_sizes(self):
        for block in (512,4096):
            with self.subTest(block=block):
                first,last,total=snapshot(block)
                original=(first,last)
                info=gpt.gpt_space(first,last,total)
                data=uninstall.partition(info,'userdata')
                need=8*2097152
                end=data['end']-need
                entries=bytearray(uninstall.table(first))
                struct.pack_into('<Q',entries,(data['n']-1)*128+40,(end+1)//(block//512)-1)
                shrunk=uninstall.with_table(original,entries,total)
                current=gpt.gpt_add_root(*shrunk,total,end+1,need)
                restored,prior,root,wipe=uninstall.restored_layout(original,current,total,'mu300root')
                self.assertTrue(wipe)
                self.assertEqual(prior,data)
                self.assertEqual(restored,list(original))
                inferred,expanded,_,growth=uninstall.device_layout(current,total,'mu300root')
                self.assertTrue(growth)
                self.assertEqual(expanded,data)
                self.assertEqual(inferred,list(original))

    def test_mixed_or_corrupt_gpt_is_rejected(self):
        a,b,total=snapshot(4096)
        for first,last in ((a,b[:-1]),(a[:-1],b),(a,b[:-4096]+bytes(4096))):
            with self.assertRaises(ValueError):gpt.gpt_space(first,last,total)
        bad=bytearray(a);bad[8192+32]^=1
        with self.assertRaises(ValueError):gpt.gpt_space(bad,b,total)

    def test_topology_and_inventory_validation(self):
        for node,disk,number in (('mmcblk0p75','mmcblk0',75),('sda75','sda',75),('sdaa123','sdaa',123)):
            self.assertEqual(storage.disk_node(node),disk)
            self.assertEqual(storage.part_node(disk,number),node)
        for bad in ('sda','sda0','sda75/../sdb','mmcblk0','dm-39','sda75;reboot'):
            with self.assertRaises(ValueError):storage.disk_node(bad)
        raw='NODE=sda75\nDISK=sda\nSTORAGE_KIND=ufs\nCID='+('a'*32)+'\nSECTOR_SIZE=4096\nSTART=4096\nSIZE=16773120\nDISK_SIZE=1999372288\nFREE=1000\n'
        self.assertEqual(storage.parse_inventory(raw)['SECTOR_SIZE'],4096)
        for old,new in (('STORAGE_KIND=ufs','STORAGE_KIND=emmc'),('START=4096','START=4097'),('DISK=sda','DISK=sdb'),
                        ('SIZE=16773120','SIZE=0'),('SIZE=16773120','SIZE=1999372288')):
            with self.assertRaises(ValueError):storage.parse_inventory(raw.replace(old,new))


class StorageLibrary(ShellTest):
    def make_disk(self, kind):
        sys=self.tmp/'sys';sys.mkdir()
        controller=self.tmp/'devices'/'22000000.ufs'
        device=controller/'host0'/'target0:0:0'/'0:0:0:0'
        disk=device/'block'/'sda' if kind=='ufs' else self.tmp/'devices'/'mmc0'/'card'/'block'/'mmcblk0'
        name=disk.name;disk.mkdir(parents=True)
        (disk/'queue').mkdir();(disk/'queue/logical_block_size').write_text('4096' if kind=='ufs' else '512')
        (sys/name).symlink_to(disk,target_is_directory=True)
        if kind=='ufs':
            (disk/'device').symlink_to(device,target_is_directory=True)
            desc=controller/'string_descriptors';desc.mkdir()
            (desc/'serial_number').write_text('unique-serial-A\n');(desc/'manufacturer_name').write_text('SAMSUNG\n')
        else:
            (disk/'device').mkdir();(disk/'device/type').write_text('MMC\n');(disk/'device/cid').write_text('a'*32+'\n')
        node=storage.part_node(name,75);part=disk/node;part.mkdir()
        (part/'partition').write_text('75');(part/'uevent').write_text('DEVTYPE=partition\nPARTNAME=userdata\n')
        (sys/node).symlink_to(part,target_is_directory=True)
        return sys,controller,name,node

    def test_usb_userdata_label_never_becomes_internal_disk(self):
        sys,_,disk,_=self.make_disk('ufs')
        usb=self.tmp/'devices/usb1/host1/target1:0:0/1:0:0:0'
        other=usb/'block/sdb';part=other/'sdb75';part.mkdir(parents=True)
        (other/'device').symlink_to(usb,target_is_directory=True)
        (part/'partition').write_text('75')
        (part/'uevent').write_text('DEVTYPE=partition\nPARTNAME=userdata\n')
        (sys/'sdb').symlink_to(other,target_is_directory=True)
        (sys/'sdb75').symlink_to(part,target_is_directory=True)
        code=(TOP/'rootfs/overlay/opt/mu300/lib/storage.sh').read_text()+'\nmu300_storage_disk\n'
        for shell in self.each_shell():
            r=self.sh(shell,code,MU300_STORAGE_SYS=sys)
            self.assertEqual(r.returncode,0,r.stderr)
            self.assertEqual(r.stdout.strip(),disk)

    def test_ufs_and_emmc_identity_and_parent(self):
        for kind in ('ufs','emmc'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as t:
                original=self.tmp;self.tmp=Path(t)
                try:
                    sys,controller,disk,node=self.make_disk(kind)
                    code=(TOP/'rootfs/overlay/opt/mu300/lib/storage.sh').read_text()+f'''
mu300_storage_parent {node}
mu300_storage_disk
mu300_storage_sector_size {disk}
mu300_storage_identity {disk}
'''
                    for shell in self.each_shell():
                        r=self.sh(shell,code,MU300_STORAGE_SYS=sys)
                        self.assertEqual(r.returncode,0,r.stderr)
                        values=r.stdout.splitlines();self.assertEqual(values[:3],[disk,disk,'4096' if kind=='ufs' else '512'])
                        expected=hashlib.sha256(b'ufs:SAMSUNG:unique-serial-A:0').hexdigest()[:32] if kind=='ufs' else 'a'*32
                        self.assertEqual(values[3],expected)
                finally:self.tmp=original


if __name__=='__main__':unittest.main()
