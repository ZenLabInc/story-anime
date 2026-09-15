import unittest
from unittest.mock import patch
from PIL import Image
import test_workspace as fixtures
from app import workspace as w, studio as s

class GenerationChatTests(unittest.TestCase):
    setUp=fixtures.WorkspaceTests.setUp
    tearDown=fixtures.WorkspaceTests.tearDown
    edit=fixtures.WorkspaceTests.edit
    talk=fixtures.WorkspaceTests.talk
    generate=fixtures.WorkspaceTests.generate
    def say(self,data,text='お願いします'):
        with patch('app.gemini.text',return_value=(dict(reply='返答',**data),{})):
            self.p=w.chat(self.user,{'id':self.p['id'],'revision':self.p['revision'],'context':'studio','text':text})
        return self.p
    def ready(self):
        self.edit('character_new');cid=self.p['characters'][0]['id']
        self.talk(cid,{'reply':'案','appearance':'赤い髪、青い服','ready':True});return cid
    def request(self,cid):
        self.say({'operation':'quote_generation','target':cid},'画像を生成して')
        return next(iter(self.p['quotes'].values()))
    def test_quote_then_consent_generates_once(self):
        cid=self.ready()
        def draw(pid,prompt,path,*args,**kwargs):Image.new('RGB',(40,60),'white').save(path);return {}
        with patch('app.gemini.image',side_effect=draw) as images,patch('app.gemini.budget',return_value={'limit_jpy':700,'reserved_or_spent_jpy':0}):
            q=self.request(cid);images.assert_not_called()
            self.assertIn('ご自身のGemini APIキー',self.p['chats'][-1]['reply']);self.assertNotIn('円',self.p['chats'][-1]['reply'])
            data={'operation':'confirm_generation','target':cid,'quote_id':q['id']}
            self.say(data);self.assertEqual(images.call_count,3);self.assertIsNotNone(self.p['characters'][0]['asset'])
            self.assertEqual(self.p['quotes'][q['id']]['consent']['text'],'お願いします')
            self.say(data);self.assertEqual(images.call_count,3)
    def test_missing_expired_wrong_and_cancelled_consent_never_spend(self):
        cid=self.ready()
        with patch('app.gemini.image') as images:
            self.say({'operation':'confirm_generation','target':cid,'quote_id':'invented'})
            q=self.request(cid)
            self.say({'operation':'confirm_generation','target':'world','quote_id':q['id']})
            q=self.request(cid)
            with s.transaction() as db:
                self.p['quotes'][q['id']]['expires']=0;s.put(db,self.p)
            self.say({'operation':'confirm_generation','target':cid,'quote_id':q['id']})
            q=self.request(cid);self.say({'operation':'cancel_generation'})
            self.say({'operation':'confirm_generation','target':cid,'quote_id':q['id']})
            images.assert_not_called()
    def test_intervening_question_invalidates_quote(self):
        cid=self.ready();q=self.request(cid)
        self.say({'operation':'clarify'},'まだ迷っている')
        with patch('app.gemini.image') as images:
            self.say({'operation':'confirm_generation','target':cid,'quote_id':q['id']});images.assert_not_called()
    def test_hold_and_selected_panel_quote(self):
        sid,_=fixtures.WorkspaceTests.setup_scene(self)
        self.say({'operation':'hold_panels','target':sid,'panels':[0],'held':True},'1コマ目は保持')
        self.assertTrue(self.p['scenes'][0]['panels'][0]['held'])
        with self.assertRaises(ValueError):self.say({'operation':'quote_generation','target':sid,'panels':[0]})
        self.p=s.read_work(self.user,self.p['id'])
        self.say({'operation':'quote_generation','target':sid,'panels':[1]})
        q=next(iter(self.p['quotes'].values()));self.assertEqual(q['panels'],[1]);self.assertEqual(q['cap_jpy'],60)
    def test_preflight_failure_requires_new_quote(self):
        cid=self.ready();q=self.request(cid)
        with patch('app.gemini.budget',return_value={'limit_jpy':700,'reserved_or_spent_jpy':699}),patch('app.gemini.image') as images:
            self.say({'operation':'confirm_generation','target':cid,'quote_id':q['id']});images.assert_not_called()
        self.assertFalse(self.p['quotes']);self.assertIn('運営',self.p['error'])
