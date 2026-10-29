#!/usr/bin/env python3
"""Run the shipped ucode GPT tool on sparse files, never physical disks.

Uses the existing local OpenWrt base image and removes its own temp fixtures.
Run in WSL: python3 tests/ufs_gpt_runtime.py
"""
from pathlib import Path
import subprocess
import tempfile

from test_ufs_storage import snapshot, TOP, gpt


def run():
    for block in (512,4096):
        with tempfile.TemporaryDirectory(prefix='mu300-ufs-gpt-') as tmp:
            folder=Path(tmp);disk=folder/'disk'
            first,last,total=snapshot(block)
            with disk.open('wb') as stream:
                stream.write(first);stream.seek(total*512-len(last));stream.write(last)
            def command(*args, ok=True):
                cmd=['docker','run','--rm','--platform','linux/arm64',
                     '-v',str(folder)+':/fixtures',
                     '-v',str(TOP/'desktop/boot/mu300-gpt')+':/tool:ro',
                     '--entrypoint','/usr/bin/ucode','mu300-openwrt-base:25.12.5',
                     '/tool',args[0],'/fixtures/disk',*map(str,args[1:])]
                r=subprocess.run(cmd,capture_output=True,text=True,timeout=45)
                assert (r.returncode==0)==ok,r.stdout+r.stderr
                return r.stdout
            listing=command('list')
            assert '2 4096 33554431 userdata' in listing,listing
            prior=16*2097152-4096;target=4*2097152;need=4*2097152
            command('plan','resize:userdata:'+str(target),'mu300root:'+str(need))
            with disk.open('rb') as stream:
                assert stream.read(len(first))==first
            command('carve-userdata',target,need,prior)
            # Geometry and CRC are independently verified by the Python codec.
            with disk.open('rb') as stream:
                a=stream.read(len(first));stream.seek(total*512-len(last));b=stream.read()
            info=gpt.gpt_space(a,b,total)
            root=next(p for p in info['parts'] if p['name']=='mu300root')
            assert root['start']==4096+target and root['end']+1-root['start']==need
            command('uuid',root['n'])
            command('resize','mu300root',need//2)
            command('add','testroot',need//2)
            with disk.open('rb') as stream:
                a=stream.read(len(first));stream.seek(total*512-len(last));b=stream.read()
            gpt.gpt_space(a,b,total)
            before=(a,b)
            command('carve-userdata',target,need,prior,ok=False)
            if block == 4096:
                command('resize','mu300root',2049,ok=False)
                command('add','unaligned',2049,ok=False)
            with disk.open('rb') as stream:
                a=stream.read(len(first));stream.seek(total*512-len(last));b=stream.read()
            assert (a,b)==before
            print(f'{block}-byte GPT: list/plan/carve/uuid/resize/add and rejected retry verified',flush=True)


if __name__=='__main__':run()
