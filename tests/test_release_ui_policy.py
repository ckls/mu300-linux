"""Exercise resource pruning, package records and user-installed menu ownership."""
import base64
import hashlib
import json
from pathlib import Path
import runpy
import tempfile
import unittest

TOP = Path(__file__).resolve().parents[1]
policy = runpy.run_path(str(TOP/'tools/release-ui-policy.py'))
ASSET = 'www/luci-static/aurora/patches/admin-services-openclash-config.css'
CSS = 'www/luci-static/aurora/main.css'
MENU = 'usr/share/luci/menu.d/luci-base.json'
LIST = 'lib/apk/packages/luci-theme-aurora.list'
DB = 'lib/apk/db/installed'


class Resources(unittest.TestCase):
    def root(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        values = {ASSET:b'old integration', CSS:b'.card{color:red}:is(.nav)[data-section=vpn]{--icon:shield}.other{color:blue}',
                  MENU:json.dumps({'admin/vpn':{'title':'VPN'},'admin/network':{'title':'Network'}}).encode(),
                  LIST:('/'+ASSET+'\n/'+CSS+'\n').encode(),
                  DB:('P:luci-theme-aurora\nF:www/luci-static/aurora/patches\nR:'+Path(ASSET).name+'\nZ:Q1old\n'
                      'F:www/luci-static/aurora\nR:main.css\nZ:Q1old\n\nP:luci-base\nF:usr/share/luci/menu.d\nR:luci-base.json\nZ:Q1old\n\n').encode()}
        for name,data in values.items():
            p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
        return root

    def test_empty_menu_removed_but_upstream_theme_unchanged(self):
        root=self.root();keep=root/'www/luci-static/aurora/patches/admin-network-wireless.css'
        keep.write_text('.wifi{display:flex}')
        policy['cleanup'](root)
        self.assertEqual((root/ASSET).read_bytes(),b'old integration')
        self.assertEqual(keep.read_text(),'.wifi{display:flex}')
        self.assertEqual((root/CSS).read_text(),'.card{color:red}:is(.nav)[data-section=vpn]{--icon:shield}.other{color:blue}')
        self.assertEqual(json.loads((root/MENU).read_text()),{'admin/network':{'title':'Network'}})
        self.assertIn('openclash',(root/LIST).read_text())
        db=(root/DB).read_text();self.assertIn('openclash',db)
        for name in (MENU,):
            self.assertIn('Z:Q1'+base64.b64encode(hashlib.sha1((root/name).read_bytes()).digest()).decode(),db)
        snapshot={p.relative_to(root):p.read_bytes() for p in root.rglob('*') if p.is_file()}
        self.assertEqual(policy['cleanup'](root),([],[]))
        self.assertEqual(snapshot,{p.relative_to(root):p.read_bytes() for p in root.rglob('*') if p.is_file()})

    def test_custom_child_menu_retains_its_parent_and_user_configuration(self):
        root=self.root();custom=root/'usr/share/luci/menu.d/custom.json'
        custom.write_text('{"admin/vpn/custom":{"title":"User service"}}')
        config=root/'etc/config/user-service';config.parent.mkdir(parents=True);config.write_text('credentials-stay')
        policy['cleanup'](root)
        self.assertIn('admin/vpn',json.loads((root/MENU).read_text()))
        self.assertEqual(config.read_text(),'credentials-stay')

    def test_invalid_menu_fails_before_removing_any_resource(self):
        root=self.root();(root/MENU).write_text('invalid json')
        with self.assertRaises(ValueError):policy['cleanup'](root)
        self.assertTrue((root/ASSET).is_file())

    def test_non_menu_files_are_never_rewritten(self):
        files={CSS:b'[data-section=vpn]{color:red}',ASSET:b'original theme',
               'etc/config/openclash':b'user data'}
        self.assertEqual(policy['plan'](files),(set(),{}))

    @unittest.skipUnless(hasattr(Path,'symlink_to'), 'Requires filesystem symlink support')
    def test_symlink_escape_is_rejected(self):
        root=self.root();(root/MENU).unlink()
        outside=root.parent/(root.name+'-outside')
        outside.write_text('leave alone');self.addCleanup(lambda:outside.unlink(missing_ok=True))
        try:(root/MENU).symlink_to(outside)
        except OSError:self.skipTest('Symlink creation unavailable')
        with self.assertRaisesRegex(ValueError,'escapes staging'):policy['cleanup'](root)
        self.assertEqual(outside.read_text(),'leave alone')


if __name__=='__main__':unittest.main()
