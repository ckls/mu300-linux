"""Execute initramfs eMMC polling with file fixtures, never block devices."""
from helpers import TOP, ShellTest


class PartitionWait(ShellTest):
    def setUp(self):
        super().setUp()
        source=(TOP/'boot/init').read_text()
        loop=source.split('find_partitions() {',1)[1].split('    detect_linux_slot',1)[0]
        # Isolate the real readiness loop before slot detection and writes.
        self.loop='mu300_storage_disk() { echo mmcblk0; }\nmu300_storage_part() { echo mmcblk0p1; }\npoll() {'+loop.replace('/sys/class/block',str(self.tmp/'block')).replace('/dev/',str(self.tmp/'dev')+'/').replace('-b "$misc"','-f "$misc"')+'\n}\npoll\n'
        block=self.tmp/'block/mmcblk0p1';block.mkdir(parents=True)
        (block/'uevent').write_text('PARTNAME=misc\n')
        (self.tmp/'dev').mkdir()
        self.stub('usleep','[ "${WAIT_FAST:-1}" = 1 ] || exit 1\n[ "$1" != 0 ] || exit 0\necho fast >> "$STUBLOG/waits"\n[ "${WAIT_READY:-0}" != 1 ] || touch "$STUBLOG/dev/mmcblk0p1"\nexit 0')
        self.stub('sleep','echo slow >> "$STUBLOG/waits"\n[ "${WAIT_READY:-0}" != 1 ] || touch "$STUBLOG/dev/mmcblk0p1"\nexit 0')
        self.stub('mdev','echo scan >> "$STUBLOG/scans"')
        # Standalone ash may prefer built-in applets over PATH. Keep every
        # delay/scan inside the fixture, including the zero-duration probe.
        self.loop=self.loop.replace('usleep ',str(self.stubs/'usleep')+' ')
        self.loop=self.loop.replace('else sleep 1;', 'else '+str(self.stubs/'sleep')+' 1;')
        self.loop=self.loop.replace('mdev -s',str(self.stubs/'mdev')+' -s')

    def run_poll(self,shell,fast=1,ready=0):
        for name in ['waits','scans','dev/mmcblk0p1']:(self.tmp/name).unlink(missing_ok=True)
        result=self.sh(shell,self.loop,WAIT_FAST=fast,WAIT_READY=ready)
        self.assertEqual((result.returncode,result.stderr),(0,''))
        return [(self.tmp/name).read_text().splitlines() if (self.tmp/name).exists() else [] for name in ['waits','scans']]

    def test_fast_and_unsupported_usleep_have_same_timeout_and_scan_budget(self):
        for shell in self.each_shell():
            for fast,count,kind in [(1,200,'fast'),(0,20,'slow')]:
                waits,scans=self.run_poll(shell,fast=fast)
                self.assertEqual(waits,[kind]*count)
                self.assertEqual(scans,['scan']*20)

    def test_ready_partition_exits_after_first_wait_in_either_mode(self):
        for shell in self.each_shell():
            for fast in [0,1]:
                waits,scans=self.run_poll(shell,fast=fast,ready=1)
                self.assertEqual(len(waits),1)
                self.assertEqual(len(scans),0 if fast else 1)
