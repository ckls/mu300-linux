#!/usr/bin/env python3
"""Repack regression using synthetic GUI/firmware; no device or compiler."""
import hashlib
import importlib.util
import json
from pathlib import Path
import runpy
import unittest
import zipfile

TOP=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('diff_fixture',TOP/'tools/tests/package-diff-studio.py')
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
repack=runpy.run_path(str(TOP/'tools/repack-with-diff.py'))['repack']
verify=runpy.run_path(str(TOP/'tools/build-release.py'))['verify_archive']


class Repack(unittest.TestCase):
    def test_payloads_and_runtime_preserved_with_complete_diff_manifest(self):
        case=fixture.DiffPackaging();case.setUp();self.addCleanup(case.doCleanups)
        root=case.root;old=root.parent/'old.zip';new=root.parent/'new.zip'
        files={p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*') if p.is_file()}
        files['payload/boot-linux.img']=files.pop('files/boot.img')
        files['payload/mu300-openwrt.tar.gz']=files.pop('files/openwrt.ext4.gz')
        manifest={'format':2,'kernel':'7.2','magisk_layout':{'boot-linux.img':'payload/boot-linux.img','mu300-openwrt.tar.gz':'payload/mu300-openwrt.tar.gz'},
                  'magisk':{n:hashlib.sha256(v).hexdigest() for n,v in files.items() if n.startswith('payload/')},
                  'desktop':{n:hashlib.sha256(v).hexdigest() for n,v in files.items() if not n.startswith('payload/')}}
        with zipfile.ZipFile(old,'w') as z:
            for name,data in files.items():z.writestr(name,data)
            z.writestr('desktop/manifest.json',json.dumps(manifest))
        verify(old);fixture.tool['attach'](root)
        repack(old,new,root,{'source_commit':'a'*40,'source_fingerprint':'b'*64})
        verify(new,require_diff=True)
        with zipfile.ZipFile(new) as z:
            self.assertEqual(len(z.namelist()),len(set(z.namelist())))
            for name in ('payload/boot-linux.img','payload/mu300-openwrt.tar.gz','tools/backend/openwrt-backend.exe','tools/macos/backend/openwrt-backend'):
                self.assertEqual(z.read(name),files[name])
            after=json.loads(z.read('desktop/manifest.json'));self.assertEqual(after['magisk'],manifest['magisk'])
            self.assertTrue(z.getinfo('OpenWrt-Diff-Studio.app/Contents/MacOS/openwrt-installer').external_attr>>16&0o111)
            self.assertIn(b'Diff Studio',z.read('START-HERE.md'))
            self.assertNotIn('payload/boot-linux.img',json.loads(z.read('diff-tool.json'))['files'])


if __name__=='__main__':unittest.main()
