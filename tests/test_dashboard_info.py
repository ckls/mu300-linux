"""Native snapshot regressions retain the original dashboard wire contract."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from native_dashboard_fixture import Snapshot

class DashboardInfo(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.snap=Snapshot(self.root)

    def test_sim_presence_uses_only_the_scoped_powered_owner_cache(self):
        s=self.snap
        self.assertEqual(s.run('sim_state','0'),'unknown')
        s.write('run/mu300-registration/sim0.json','{"slot":0,"state":"absent"}')
        self.assertEqual(s.run('sim_state','0'),'unknown')
        s.write('run/mu300-registration/sim-power0','')
        self.assertEqual(s.run('sim_state','0'),'absent')
        self.assertEqual(s.run('sim_state','1'),'unknown')
        for value in ('{"slot":1,"state":"absent"}','{"slot":0,"state":"invalid"}','broken json','null'):
            s.write('run/mu300-registration/sim0.json',value)
            self.assertEqual(s.run('sim_state','0'),'unknown')
        for value in ('ready','locked'):
            s.write('run/mu300-registration/sim0.json',json.dumps(dict(slot=0,state=value)))
            self.assertEqual(s.run('sim_state','0'),value)
        self.assertEqual(s.run('sim_state','invalid'),'unknown')

    def test_info_reports_the_requested_slot_and_clears_on_owner_loss(self):
        s=self.snap
        s.write('run/mu300-at/owner/pid','123')
        s.write('proc/123/cmdline','owner')
        fifo=s.root/'run/mu300-at/cmd';os.mkfifo(fifo)
        s.write('run/mu300-registration/sim-power0','')
        s.write('run/mu300-registration/sim0.json','{"slot":0,"state":"absent"}')
        self.assertEqual(s.run(slot='0')['modem']['sims'][0],dict(slot=0,state='absent'))
        self.assertEqual(s.run(slot='1')['modem']['sims'][1],dict(slot=1,state='unknown'))
        (s.root/'run/mu300-at/owner/pid').unlink()
        self.assertEqual(s.run(slot='0')['modem']['sims'][0],dict(slot=0,state='unknown'))

    def test_dns_reuses_both_status_snapshots(self):
        data=self.snap.run()
        self.assertEqual(data['wan']['dns'],'1.1.1.1, 2001:4860:4860::8888')
        # inactive DNS must never override the active netifd answer.
        self.snap.responses['network.interface.wan.status']['inactive']={'dns-server':['WRONG']}
        self.assertNotIn('WRONG',self.snap.run()['wan']['dns'])

    def test_mac_only_station_is_counted_without_fabricated_metrics(self):
        self.snap.stations=[{'mac':'e6:7a:77:59:7e:47'}]
        data=self.snap.run()['wifi']
        self.assertEqual(data['clients_n'],1)
        self.assertEqual(data['clients'][0],dict(mac='e6:7a:77:59:7e:47',host='Xiaomi-17-Pro',ip='192.168.77.105',signal=None,tx=None,rx=None,conn=None))

    def test_complete_station_blocks_and_deduplication(self):
        self.snap.stations=[{'mac':'E6:7A:77:59:7E:47','sta_info':{'signal':-42,'tx_bitrate':{'bitrate':8667},'rx_bitrate':{'bitrate':4333},'connected_time':125}},
                            {'mac':'aa:bb:cc:dd:ee:ff'},{'mac':'e6:7a:77:59:7e:47'},{'mac':'invalid'}]
        data=self.snap.run()['wifi'];self.assertEqual(data['clients_n'],2)
        self.assertEqual(data['clients'][0]['signal'],-42)
        self.assertEqual(data['clients'][0]['tx'],'866.7 Mbit/s')
        self.assertEqual(data['clients'][0]['rx'],'433.3 Mbit/s')
        self.assertEqual(data['clients'][0]['conn'],'2 min')
        self.assertIsNone(data['clients'][1]['host'])

    def test_empty_station_table_and_query_failure_are_distinct(self):
        self.snap.responses['hostapd.wlan0.get_clients']=None
        for stations,count in [([],0),(None,None)]:
            self.snap.stations=stations
            self.assertEqual(self.snap.run()['wifi']['clients_n'],count)
        self.snap.responses['hostapd.wlan0.get_clients']={'clients':{'aa:bb:cc:dd:ee:ff':{}}}
        self.assertEqual(self.snap.run()['wifi']['clients_n'],1)

    def test_conntrack_prefers_scalar_and_uses_existing_table_format_when_needed(self):
        scalar=self.root/'proc/sys/net/netfilter/nf_conntrack_count'
        table=self.root/'proc/net/nf_conntrack'
        for counter,rows,expected in [('163',None,163),('0','x\ny\n',0),(None,'x\ny\n',2),('bad','x\n',1),(None,'',0),(None,None,None)]:
            for path,value in [(scalar,counter),(table,rows)]:
                if value is None:path.unlink(missing_ok=True)
                else:path.parent.mkdir(parents=True,exist_ok=True);path.write_text(value)
            self.assertEqual(self.snap.run()['conns'],expected)

    def test_conntrack_table_is_counted_across_chunk_boundaries(self):
        self.snap.write('proc/net/nf_conntrack','x'*4095+'\n'+'entry\n'*10000)
        self.assertEqual(self.snap.run()['conns'],10001)

    def test_json_strings_quotes_unicode_and_newlines(self):
        for value in ['normal','A\\B"C','中文热点 🛜','line1\nline2\rline3']:
            # Read-only system-file strings cannot corrupt the surrounding JSON.
            self.snap.write('tmp/sysinfo/model',value)
            self.assertEqual(self.snap.run()['model'],value.replace('\n','').replace('\r',''))
