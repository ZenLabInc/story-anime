import copy
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
try:
    from app import core
except ImportError:
    core = None

@unittest.skipIf(core is None, 'Prototype tests require .venv and requirements.txt')
class PrototypeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.old=core.DATA; core.DATA=Path(self.temp.name)
        self.p=core.create('待って。\n約束だよ。','約束だよ。','二人は別れない')
    def tearDown(self): core.DATA=self.old; self.temp.cleanup()
    def test_original_and_fixed(self):
        body=copy.deepcopy(self.p); body['shots'][1]['text']='さようなら。'
        with self.assertRaises(ValueError): core.update(self.p,body)
        self.assertEqual(core.load(self.p['id'])['original'],'待って。\n約束だよ。')
    def test_lock_and_character_change(self):
        body=copy.deepcopy(self.p); body['shots'][0]['locked']=True; core.update(self.p,body)
        with self.assertRaises(ValueError): core.quote(self.p,['1'])
        body=copy.deepcopy(self.p); body['characters'][0]['color']='#ffffff'
        with self.assertRaises(ValueError): core.update(self.p,body)
    def test_target_invalidation_and_undo(self):
        for s in self.p['shots']: s['asset']={'id':s['id'],'sha256':'unchanged'}
        core.save(self.p); body=copy.deepcopy(self.p); body['shots'][0]['expression']='smile'
        core.update(self.p,body)
        self.assertIsNone(self.p['shots'][0]['asset']); self.assertTrue(all(s['asset']['sha256']=='unchanged' for s in self.p['shots'][1:]))
        core.restore(self.p); self.assertEqual(self.p['shots'][0]['asset']['sha256'],'unchanged')
    def test_stale_quote_and_overspend(self):
        q=core.quote(self.p,['1']); body=copy.deepcopy(self.p); core.update(self.p,body)
        with self.assertRaises(ValueError): core.start(self.p,q['id'])
        self.p['used_seconds']=120
        with self.assertRaises(ValueError): core.quote(self.p,['1'])
    def test_duplicate_ids_and_expiry(self):
        with self.assertRaises(ValueError): core.quote(self.p,['1','1'])
        q=core.quote(self.p,['1']); q['expires']=0
        with self.assertRaises(ValueError): core.start(self.p,q['id'])
    def test_double_submit(self):
        q=core.quote(self.p,['1'])
        with patch('app.core.threading.Thread'):
            first=core.start(self.p,q['id']); second=core.start(self.p,q['id'])
        self.assertEqual(first['id'],second['id']); self.assertEqual(len(self.p['jobs']),1)
    def test_failed_render_preserves_assets_and_quota(self):
        self.p['shots'][0]['asset']={'id':'old'}; core.save(self.p); q=core.quote(self.p,['1'])
        with patch('app.core.threading.Thread'): j=core.start(self.p,q['id'])
        with patch('app.core.render',side_effect=ValueError('test failure')): core.worker(copy.deepcopy(self.p),j['id'])
        p=core.load(self.p['id']); self.assertEqual(p['used_seconds'],0); self.assertEqual(p['shots'][0]['asset']['id'],'old'); self.assertEqual(p['jobs'][0]['status'],'failed')
    def test_input_never_silently_truncated(self):
        with self.assertRaises(ValueError): core.create('\n'.join(['多すぎる。']*7))
        with self.assertRaises(ValueError): core.create('あ'*241)
    def test_fixed_must_not_cross_shots(self):
        with self.assertRaises(ValueError): core.create('待って。約束だよ。','待って。約束だよ。')
    def test_character_change_invalidates_all_unlocked_assets(self):
        for shot in self.p['shots']: shot['asset']={'id':shot['id']}
        body=copy.deepcopy(self.p); body['characters'][0]['color']='#ffffff'
        core.update(self.p,body)
        self.assertTrue(all(s['asset'] is None for s in self.p['shots']))
    def test_stale_editor_cannot_overwrite(self):
        old=copy.deepcopy(self.p); body=copy.deepcopy(self.p); core.update(self.p,body)
        with self.assertRaises(ValueError): core.update(self.p,old)
    def test_invalid_input_types(self):
        with self.assertRaises(ValueError): core.create(['台本'])
        with self.assertRaises(ValueError): core.create('台本',ending='a'*301)
    def test_path_traversal(self):
        with self.assertRaises(ValueError): core.load('../secret')

if __name__=='__main__': unittest.main()
