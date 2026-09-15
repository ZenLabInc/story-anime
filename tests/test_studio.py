import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app import studio as s

class StudioTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.old=(s.DATA,s.DB)
        s.DATA=Path(self.temp.name); s.DB=s.DATA/'studio.db'; s.init()
        self.u,self.token=s.session(); self.v,_=s.session(); self.u=self.u['id']; self.v=self.v['id']
    def tearDown(self): s.DATA,s.DB=self.old; self.temp.cleanup()
    def draft(self,mode='漫画'):
        w=s.create(self.u)
        for text in [mode,'アオ：旅人／ユイ：案内人','二人が再会する。約束をする。','またね。','やさしい']:
            w=s.chat(self.u,w['id'],text,w['revision'])
        return w
    def ready(self,mode='漫画'):
        w=self.draft(mode); return s.approve(self.u,w['id'],w['revision'])
    def reserve(self,w):
        with patch.object(s.threading.Thread,'start'): return s.generate(self.u,w['id'],w['quote']['id'])
    def test_modes_and_approval(self):
        for mode,n,cr in [('漫画',4,20),('アニメ',6,240)]:
            w=self.ready(mode); self.assertEqual(len(w['shots']),n);self.assertEqual(w['quote']['credits'],cr)
        w=self.draft()
        with self.assertRaises(ValueError):s.generate(self.u,w['id'],'none')
    def test_duplicate_and_restart_refund_once(self):
        w=self.ready();j=self.reserve(w)
        self.assertEqual(s.generate(self.u,w['id'],w['quote']['id'])['id'],j['id'])
        self.assertEqual(s.state(self.u)['user']['balance'],480)
        s.init();s.init();self.assertEqual(s.state(self.u)['user']['balance'],500)
    def test_shared_wallet_prevents_overspend(self):
        for _ in range(2):self.reserve(self.ready('アニメ'))
        with self.assertRaises(ValueError):self.reserve(self.ready('アニメ'))
        self.assertEqual(s.state(self.u)['user']['balance'],20)
    def test_stale_quote_and_revision(self):
        w=self.ready();old=copy.deepcopy(w);w=s.chat(self.u,w['id'],'2コマ目を微笑む表情に',w['revision'])
        with self.assertRaises(ValueError):s.generate(self.u,w['id'],old['quote']['id'])
        with self.assertRaises(ValueError):s.chat(self.u,w['id'],'戻る',old['revision'])
        w=s.approve(self.u,w['id'],w['revision'])
        with s.transaction() as db:w['quote']['expires']=0;s.put(db,w)
        with self.assertRaises(ValueError):self.reserve(w)
    def test_fixed_lock_undo(self):
        w=self.draft()
        with self.assertRaises(ValueError):s.chat(self.u,w['id'],'4コマ目のセリフを「変更」に',w['revision'])
        w=s.chat(self.u,w['id'],'1コマ目を保持',w['revision'])
        with self.assertRaises(ValueError):s.chat(self.u,w['id'],'1コマ目を微笑む表情に',w['revision'])
        w=s.chat(self.u,w['id'],'戻る',w['revision']);self.assertFalse(w['shots'][0]['locked'])
    def complete(self):
        w=self.draft(); folder=s.DATA/w['id'];folder.mkdir()
        for name in ['comic.png','poster.png','project.zip']:(folder/name).write_bytes(b'test')
        for shot in w['shots']:shot['asset']={'sha256':shot['id']}
        w['output']={k:str(Path(w['id'])/v) for k,v in [('file','comic.png'),('poster','poster.png'),('zip','project.zip')]};w['approved']=w['revision']
        with s.transaction() as db:s.put(db,w)
        return w
    def test_publish_snapshot_privacy_likes(self):
        w=self.complete()
        with self.assertRaises(PermissionError):s.read_work(self.v,w['id'])
        with self.assertRaises(PermissionError):s.file_path(self.v,w['output']['file'])
        w=s.publish(self.u,w['id'],w['revision'],True)
        s.file_path(self.v,w['output']['file'])
        with self.assertRaises(PermissionError):s.file_path(self.v,w['output']['zip'])
        s.like(self.v,w['id'],True);s.like(self.v,w['id'],True)
        g=s.state(self.v)['gallery'][0];self.assertEqual(g['likes'],1);self.assertNotIn('answers',g)
        with self.assertRaises(ValueError):s.like(self.u,w['id'],True)
        w=s.chat(self.u,w['id'],'2コマ目を微笑む表情に',w['revision'])
        self.assertEqual(s.state(self.v)['gallery'][0]['file'],g['file'])
        self.assertIsNone(w['shots'][1]['asset']);self.assertEqual(w['shots'][0]['asset']['sha256'],'1')
        s.publish(self.u,w['id'],w['revision'],False)
        with self.assertRaises(PermissionError):s.file_path(self.v,g['file'])
    def test_adapt_preserves_original(self):
        w=self.complete();a=s.adapt(self.u,w['id'])
        self.assertEqual(len(a['shots']),6);self.assertEqual(a['shots'][-1]['text'],'またね。')
        self.assertEqual(s.read_work(self.u,w['id']),w);self.assertEqual(s.state(self.u)['user']['balance'],500)
    def test_failed_worker_refunds(self):
        try:import app.studio_render
        except ImportError:self.skipTest('Pillow requires .venv')
        w=self.ready();j=self.reserve(w)
        with patch('app.studio_render.make_asset',side_effect=ValueError('test failure')):s.worker(w,j)
        self.assertEqual(s.state(self.u)['user']['balance'],500)
        self.assertTrue(all(x['asset'] is None for x in s.read_work(self.u,w['id'])['shots']))

if __name__=='__main__':unittest.main()
