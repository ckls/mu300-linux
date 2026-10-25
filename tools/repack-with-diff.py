#!/usr/bin/env python3
"""Stream a verified MU300 ZIP, adding Diff Studio without extracting rootfs."""
import copy
import hashlib
import json
from pathlib import Path
import runpy
import zipfile

TOP=Path(__file__).resolve().parents[1]


def repack(source,target,studio,revision):
    if target.exists():raise ValueError('Target release already exists')
    tool=json.loads((studio/'diff-tool.json').read_text())
    patches={}
    with zipfile.ZipFile(source) as old:
        manifest=json.loads(old.read('desktop/manifest.json'))
        checks={**manifest['magisk'],**manifest['desktop']}
        for name,wanted in tool['files'].items():
            if name in checks:
                if checks[name]!=wanted:raise ValueError('Existing native runtime differs: '+name)
            else:patches[name]=(studio/name).read_bytes()
        for name in ('diff-tool.json','docs/DIFF-STUDIO.md'):patches[name]=(studio/name).read_bytes()
        patches['START-HERE.md']=old.read('START-HERE.md')+(
            '\n## Diff Studio / 差异更新工具\n\n'
            'Windows: **OpenWrt-Diff-Studio.exe**. Apple Silicon: **OpenWrt-Diff-Studio.app**.\n\n'
            '完整解压后打开；与安装器共用 tools 目录，请勿单独移动程序。'
            '使用说明见 [DIFF-STUDIO.md](docs/DIFF-STUDIO.md)。\n').encode()
        payload={n:checks[n] for n in manifest['magisk_layout'].values()}
        patches['desktop/TOOLS-REVISION.json']=(json.dumps({'format':1,'kind':'tools-only',
            'source_commit':revision['source_commit'],'source_fingerprint':revision['source_fingerprint'],
            'firmware_unchanged':payload,'base_archive':source.name},indent=2)+'\n').encode()
        manifest['desktop'].update({n:hashlib.sha256(v).hexdigest() for n,v in patches.items()})
        patches['desktop/manifest.json']=(json.dumps(manifest,indent=2)+'\n').encode()
        with zipfile.ZipFile(target,'x') as output:
            for member in old.infolist():
                with output.open(copy.copy(member),'w',force_zip64=True) as dst:
                    if member.filename in patches:dst.write(patches[member.filename])
                    else:
                        with old.open(member) as src:
                            for block in iter(lambda:src.read(1<<20),b''):dst.write(block)
            for name,data in patches.items():
                if name in old.namelist():continue
                info=zipfile.ZipInfo(name);info.create_system=3
                mode=0o755 if name.startswith('OpenWrt-Diff-Studio.app/Contents/MacOS/') else 0o644
                info.external_attr=(0o100000|mode)<<16;info.compress_type=zipfile.ZIP_DEFLATED
                output.writestr(info,data)
    return payload
