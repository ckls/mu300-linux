"""Exercise affinity selection without entering the persistent boot writer."""
from helpers import ShellTest, BIN

class RecorderCPU(ShellTest):
    def test_lowest_capacity_cluster_and_missing_topology(self):
        text=(BIN/'early-recorder').read_text()
        helper=text[text.index('# --- cpus begin'):text.index('# --- cpus end')]
        for shell in self.each_shell():
            root=self.tmp/'cpus'
            for n,capacity in enumerate(['1024','512','512','invalid']):
                p=root/f'cpu{n}'/'cpu_capacity'
                p.parent.mkdir(parents=True,exist_ok=True)
                p.write_text(capacity+'\n')
            result=self.sh(shell,helper+'\nlittle_cpus',MU300_CPUDIR=root)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(result.stdout.strip(),'1,2')
            result=self.sh(shell,helper+'\nlittle_cpus',MU300_CPUDIR=self.tmp/'missing')
            self.assertEqual(result.stdout.strip(),'')
