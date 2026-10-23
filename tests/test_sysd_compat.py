"""Hold the ucode service to this branch's original button/thermal behavior."""
import subprocess
import unittest
from pathlib import Path
from helpers import BIN, ucode, ucode_paths
import test_device_scripts as old

def runtime_available():
    if not ucode():return False
    p=subprocess.run(ucode()+['-e',"import * as a from 'uloop'; import * as b from 'socket'; print(type(a.process));"],capture_output=True,text=True)
    return p.returncode==0 and p.stdout=='function'

class NativeService:
    def script(self,shell,path,*args,**env):
        if Path(path).name not in ['mu300-buttons','thermal-guard']:
            return super().script(shell,path,*args,**env)
        thermal=Path(path).name=='thermal-guard'
        if not thermal:
            root=self.tmp/'sysd-root';(root/'proc').mkdir(parents=True,exist_ok=True)
            (root/'proc'/'uptime').symlink_to('/proc/uptime') if not (root/'proc'/'uptime').exists() else None
            env['MU300_SYSROOT']=root
            env['MU300_RUN']=self.tmp/'run'
            env['MU300_SYSD_PARTS']='keys led';env['MU300_SYSD_ONCE']='1'
        cmd=ucode()+ucode_paths()[2:]+[str(BIN/'mu300-sysd')]+(['--round'] if thermal else [])
        result=subprocess.run(cmd,env=self.env(**env),capture_output=True,text=True,timeout=20)
        return result

@unittest.skipUnless(runtime_available(),'real ucode/uloop/socket required')
class NativeButtons(NativeService,old.Buttons):
    def setUp(self):
        super().setUp()
        # The release ships a full busybox sleep. The minimal OpenWrt test
        # image lacks fractional sleep, so the key feeder uses real Python sleep.
        self.stub('sleep', 'exec python3 -c "import sys,time;time.sleep(float(sys.argv[1]))" "$1"')

@unittest.skipUnless(runtime_available(),'real ucode/uloop/socket required')
class NativeThermal(NativeService,old.ThermalGuard):pass
