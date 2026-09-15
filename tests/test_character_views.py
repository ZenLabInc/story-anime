import copy
import hashlib
import unittest
from unittest.mock import patch
from PIL import Image
import test_workspace as fixtures
from app import workspace as w, studio as s

class CharacterViewsTests(unittest.TestCase):
    setUp=fixtures.WorkspaceTests.setUp
    tearDown=fixtures.WorkspaceTests.tearDown
    edit=fixtures.WorkspaceTests.edit
    talk=fixtures.WorkspaceTests.talk
    def ready(self):
        self.edit('character_new');cid=self.p['characters'][0]['id']
        self.talk(cid,{'reply':'案','appearance':'赤い髪、青い制服の人物','ready':True})
        return cid
    def test_three_separate_portraits_reference_same_front_and_resume_only_missing(self):
        cid=self.ready();q=w.quote(self.user,{'id':self.p['id'],'revision':self.p['revision'],'kind':'character','target':cid})
        self.assertEqual(q['quote']['panels'],[0,1,2]);self.assertEqual(q['quote']['cap_jpy'],180)
        calls=[]
        def draw(pid,prompt,dest,reference=None,**kw):
            calls.append((str(dest),str(reference) if reference else None,kw,prompt))
            if len(calls)==3:raise ValueError('背面の通信失敗')
            Image.new('RGB',(400,600),(220,80,90)).save(dest);return {'estimated_jpy':1}
        with patch('app.gemini.image',side_effect=draw),patch('app.gemini.budget',return_value={'reserved_or_spent_jpy':0,'limit_jpy':700}):
            with self.assertRaises(ValueError):w.generate(self.user,{'id':self.p['id'],'quote_id':q['quote']['id']})
        self.p=s.read_work(self.user,self.p['id']);c=self.p['characters'][0]
        self.assertIsNone(c['asset']);self.assertEqual(set(c['view_assets']),{'front','side'})
        self.assertIsNone(calls[0][1]);self.assertEqual(calls[1][1],calls[0][0]);self.assertEqual(calls[2][1],calls[0][0])
        self.assertEqual(calls[0][2]['aspect_ratio'],'2:3')
        saved=copy.deepcopy(c['view_assets']);front_hash=hashlib.sha256((s.DATA/saved['front']['file']).read_bytes()).hexdigest()
        q=w.quote(self.user,{'id':self.p['id'],'revision':self.p['revision'],'kind':'character','target':cid})
        self.assertEqual(q['quote']['panels'],[2]);self.assertEqual(q['quote']['cap_jpy'],60)
        with patch('app.gemini.image',side_effect=draw),patch('app.gemini.budget',return_value={'reserved_or_spent_jpy':0,'limit_jpy':700}):self.p=w.generate(self.user,{'id':self.p['id'],'quote_id':q['quote']['id']})
        c=self.p['characters'][0];self.assertEqual(c['view_assets']['front'],saved['front']);self.assertEqual(c['view_assets']['side'],saved['side'])
        self.assertEqual(calls[-1][1],calls[0][0]);self.assertEqual(len(calls),4)
        self.assertEqual(hashlib.sha256((s.DATA/c['asset']['front']).read_bytes()).hexdigest(),front_hash)
        self.assertEqual(Image.open(s.DATA/c['asset']['sheet']).size,(1200,600));self.assertEqual(c['name_state'],'pending')
        self.talk(cid,{'action':'revise_appearance','appearance':'黒髪に変更、青い制服','ready':True,'reply':'別案です'})
        self.assertEqual(self.p['characters'][0]['view_assets'],{})
    def test_front_change_requires_regenerating_dependent_views(self):
        cid=self.ready()
        with self.assertRaises(ValueError):w.quote(self.user,{'id':self.p['id'],'revision':self.p['revision'],'kind':'character','target':cid,'views':[1]})
        from app.character_views import selected
        self.assertEqual(selected(self.p['characters'][0],[0]),[0])
        with self.assertRaises(ValueError):selected({'view_assets':{'front':{},'side':{}}},[0])

    def test_individual_views_save_and_finish_without_regenerating_front(self):
        cid=self.ready();calls=[]
        def draw(pid,prompt,dest,reference=None,**kw):
            calls.append((str(dest),str(reference) if reference else None))
            Image.new('RGB',(400,600),'blue').save(dest);return {'estimated_jpy':1}
        with patch('app.gemini.image',side_effect=draw),patch('app.gemini.budget',return_value={'reserved_or_spent_jpy':0,'limit_jpy':700}):
            for view in range(3):
                q=w.quote(self.user,{'id':self.p['id'],'revision':self.p['revision'],'kind':'character','target':cid,'views':[view]})
                self.p=w.generate(self.user,{'id':self.p['id'],'quote_id':q['quote']['id']})
                self.assertIsNone(self.p['error']);self.assertTrue(self.p['chats'][-1]['images'])
                self.assertEqual(len(self.p['characters'][0]['view_assets']),view+1)
        self.assertEqual(len(calls),3);self.assertEqual(calls[1][1],calls[0][0]);self.assertEqual(calls[2][1],calls[0][0])
        self.assertTrue(self.p['characters'][0]['asset']['sheet'])
