#!/usr/bin/env python3
"""Source and binary fingerprint for the static ARM64 bridge; no device access."""
import hashlib
import json
import struct
import sys
from pathlib import Path
SOURCE = Path(__file__).with_name('mu300-atd-io.c')
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
def inspect(path, source=SOURCE):
    header = path.read_bytes()[:64]
    if len(header) != 64 or header[:6] != b'\x7fELF\x02\x01' or struct.unpack_from('<H', header, 18)[0] != 183:
        raise ValueError('Static helper must be a little-endian ELF64 AArch64 executable')
    # A static helper has no PT_INTERP, so it does not depend on the device libc.
    with path.open('rb') as f:
        off = struct.unpack_from('<Q', header, 32)[0]
        size, count = struct.unpack_from('<HH', header, 54)
        for i in range(count):
            f.seek(off + i * size)
            if struct.unpack('<I', f.read(4))[0] == 3:
                raise ValueError('Static helper must be linked statically')
    return {'format': 1, 'source_sha256': sha(source), 'binary_sha256': sha(path)}
def check(path, source=SOURCE):
    expected = inspect(path, source)
    if json.loads(Path(str(path)+'.build.json').read_text()) != expected:
        raise ValueError('Static helper is stale or modified; run its tracked build.sh for the registered inputs')
if __name__ == '__main__':
    try:
        action, value, *extra = sys.argv[1:]
        source = Path(extra[0]) if extra else SOURCE
        path = Path(value)
        if action == 'stamp':
            Path(str(path)+'.build.json').write_text(json.dumps(inspect(path, source), indent=2)+'\n')
        elif action == 'check': check(path, source)
        else: raise ValueError('expected stamp or check')
    except (OSError, ValueError, struct.error) as e:
        sys.exit(str(e))
