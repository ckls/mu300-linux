"""Parse the actual Docker rootfs shell argument without running Docker/apk."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from helpers import TOP, shells


class RootfsShell(unittest.TestCase):
    def test_container_script_remains_one_complete_argument(self):
        source=(TOP/'openwrt/build-rootfs.sh').read_text()
        start=source.rindex('docker run --rm --platform linux/arm64')
        end=source.index('\n# Remove optional VPN helpers',start)
        command=source[start:end]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            capture=root/'args.json'
            # An accidentally unquoted * must not expand into repository files.
            (root/'AGENTS.md').write_text('fixture only\n')
            env=dict(os.environ,CAPTURE=str(capture))
            prefix='''set -eu
TOP=/input; IN=/input; ROOTFS_DIR=/output; REGDB=/regdb
THEME_APK=/theme.apk; BLOCK_APK=/block.apk; WIFI_APKS=/wifi
KREL=test-kernel; OUT=test.tar.gz; FLAVOUR=openwrt; VER=25.12.5
opt() { :; }
mainline_opt() { :; }
plugin_opt() { :; }
docker() {
    python3 -c 'import sys,json,os; open(os.environ["CAPTURE"],"w").write(json.dumps(sys.argv[1:]))' "$@"
}
'''
            for shell in shells():
                with self.subTest(shell=shell):
                    result=subprocess.run(shell+['-c',prefix+command],cwd=root,env=env,
                                          capture_output=True,text=True,timeout=10)
                    self.assertEqual(result.returncode,0,result.stderr)
                    args=json.loads(capture.read_text())
                    index=args.index('-c',args.index('/bin/sh'))
                    self.assertEqual(len(args),index+2,'Docker script split into extra arguments')
                    # BusyBox ash can ignore noexec for -c. Parse stdin and
                    # fail closed before any build command if noexec is absent.
                    checked=subprocess.run(shell+['-n'],input='exit 97\n'+args[index+1],
                                           capture_output=True,text=True,timeout=10)
                    self.assertEqual(checked.returncode,0,checked.stderr)
