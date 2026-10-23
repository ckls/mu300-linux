"""Local dashboard semantics on the imported pure ucode parser."""
import json
import subprocess
import unittest
from helpers import ucode, ucode_paths
from test_dashboard_neighbors import NR_REPLY, LTE_REPLY

@unittest.skipUnless(ucode(), 'ucode required')
class CellParser(unittest.TestCase):
    def call(self,name,*args):
        code="import * as cp from 'mu300.cellparse'; print(sprintf('%J', cp."+name+"("+','.join(json.dumps(a) for a in args)+")));"
        p=subprocess.run(ucode()+ucode_paths()[2:]+['-e',code],capture_output=True,text=True,timeout=10)
        self.assertEqual(p.returncode,0,p.stderr)
        return json.loads(p.stdout)

    def test_nr_array_signed_values_and_reported_band(self):
        rows=self.call('nr_neighbours',NR_REPLY,'spengmd')
        self.assertEqual(len(rows),6)
        self.assertEqual({r['band'] for r in rows},{78})
        self.assertEqual(rows[0]['rsrp'],-108.7)
        self.assertEqual(rows[0]['sinr'],3.4)
        self.assertEqual(rows[2]['sinr'],-7.5)

    def test_lte_csv_blocks_and_full_band_table(self):
        rows=self.call('sp_ltenb',LTE_REPLY)
        self.assertEqual([(r['band'],r['arfcn'],r['pci']) for r in rows],[(3,1650,211),(45,46600,123)])
        self.assertEqual(rows[0]['rsrp'],-95)

    def test_spq_ambiguous_and_unknown_frequency_never_guesses_band(self):
        for frequency, candidates in [(627264,[77,78]),(999999,[])]:
            rows=self.call('nr_neighbours',f'0,0,0,0,0,0,0,0,1,{frequency},687,-10830,-1100,330,0,0,0','spq')
            self.assertIsNone(rows[0]['band'])
            self.assertEqual(rows[0]['band_candidates'],candidates)

    def test_operator_decodes_only_explicit_ucs2(self):
        for charset,want in [('UCS2','中国'),('GSM','4E2D56FD'),('unknown','4E2D56FD')]:
            self.assertEqual(self.call('cops_fragment','+COPS: 0,0,"4E2D56FD",7','',charset)['name'],want)
        self.assertEqual(self.call('cops_fragment','+COPS: 0,2,"46001",7','','UCS2')['plmn'],'46001')

    def test_qos_rejects_invalid_cid_and_qci(self):
        for row in ['x,9,0,0,0,0,1000,2000','1,0','1,256','1,-1']:
            self.assertIsNone(self.call('qos_fragment',row))
        self.assertEqual(self.call('qos_fragment','1,9,0,0,0,0,1000,2000'),dict(qci=9,dl=1,ul=2))
