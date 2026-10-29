#!/usr/bin/env python3
"""Remove an unused menu parent without altering themes or user plugins."""
import argparse
import base64
import hashlib
import json
from pathlib import Path


def candidate(name):
    name = name.removeprefix('./')
    return (name.startswith('usr/share/luci/menu.d/') and name.endswith('.json')
            or name == 'lib/apk/db/installed')


def apk_database(data, changed):
    """Update checksums for the modified menu files, retaining package ownership."""
    lines = data.decode().splitlines(keepends=True)
    output, folder, i = [], '', 0
    while i < len(lines):
        line = lines[i]
        if line.startswith('F:'):
            folder = line[2:].strip()
        if not line.strip():
            folder = ''
        if not line.startswith('R:'):
            output.append(line); i += 1; continue
        end = i + 1
        while end < len(lines) and lines[end].strip() and not lines[end].startswith(('R:', 'F:')):
            end += 1
        name = (folder + '/' + line[2:].strip()).lstrip('/')
        record = lines[i:end]
        if name in changed:
            digest = 'Q1' + base64.b64encode(hashlib.sha1(changed[name]).digest()).decode()
            record = [f'Z:{digest}\n' if x.startswith('Z:') else x for x in record]
        output.extend(record)
        i = end
    return ''.join(output).encode()


def plan(files):
    """Pure transform shared by offline directory and streaming tar builders."""
    removed = set()
    changed = {}
    menus = {name: json.loads(data) for name, data in files.items()
             if name.startswith('usr/share/luci/menu.d/') and name.endswith('.json')}
    # Preserve the parent if a user-installed plugin actually needs it.
    used = any(key.startswith('admin/vpn/') for menu in menus.values() for key in menu)
    for name, menu in menus.items():
        if not used and 'admin/vpn' in menu:
            del menu['admin/vpn']
            changed[name] = (json.dumps(menu, ensure_ascii=False, indent=2) + '\n').encode()
    database = 'lib/apk/db/installed'
    if database in files:
        new = apk_database(files[database], changed)
        if new != files[database]:
            changed[database] = new
    return removed, changed


def cleanup(root):
    root = Path(root).resolve()
    files = {}
    for directory in ('usr/share/luci/menu.d',):
        base = root / directory
        if base.exists():
            for path in base.rglob('*'):
                name = path.relative_to(root).as_posix()
                if candidate(name) and path.is_file():
                    if path.is_symlink() or not path.resolve().is_relative_to(root):
                        raise ValueError('UI resource escapes staging: ' + name)
                    files[name] = path.read_bytes()
    database = root / 'lib/apk/db/installed'
    if database.exists():
        if database.is_symlink() or not database.resolve().is_relative_to(root):
            raise ValueError('APK database escapes staging')
        files['lib/apk/db/installed'] = database.read_bytes()
    removed, changed = plan(files)
    for name in sorted(removed):
        (root / name).unlink()
    for name, data in changed.items():
        (root / name).write_bytes(data)
    return sorted(removed), sorted(changed)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(dict(zip(('removed', 'changed'), cleanup(args.root)))))
