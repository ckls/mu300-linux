"""Refuse silently reused helpers when the architecture, source or bytes differ."""
import json
import runpy
import struct
import tempfile
import unittest
from pathlib import Path
from helpers import TOP

class Artifact(unittest.TestCase):
    def test_static_arm64_and_fingerprint_validation(self):
        api=runpy.run_path(str(TOP/'tools/atd-io/artifact.py'))
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'bridge'
            data=bytearray(64)
            data[:6]=b'\x7fELF\x02\x01'
            struct.pack_into('<H',data,18,183)
            p.write_bytes(data)
            meta=Path(str(p)+'.build.json')
            record=api['inspect'](p)
            meta.write_text(json.dumps(record))
            api['check'](p)
            p.write_bytes(data+b'changed')
            with self.assertRaisesRegex(ValueError,'stale or modified'):api['check'](p)
            p.write_bytes(data)
            record['source_sha256']='old'
            meta.write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError,'stale or modified'):api['check'](p)

    def test_wrong_architecture_dynamic_and_truncated_are_rejected(self):
        api=runpy.run_path(str(TOP/'tools/atd-io/artifact.py'))
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'bridge'
            p.write_bytes(b'not ELF')
            with self.assertRaisesRegex(ValueError,'AArch64'):api['inspect'](p)
            data=bytearray(68)
            data[:6]=b'\x7fELF\x02\x01'
            struct.pack_into('<H',data,18,62)
            p.write_bytes(data)
            with self.assertRaisesRegex(ValueError,'AArch64'):api['inspect'](p)
            struct.pack_into('<H',data,18,183)
            struct.pack_into('<Q',data,32,64)
            struct.pack_into('<HH',data,54,4,1)
            struct.pack_into('<I',data,64,3)
            p.write_bytes(data)
            with self.assertRaisesRegex(ValueError,'statically'):api['inspect'](p)
