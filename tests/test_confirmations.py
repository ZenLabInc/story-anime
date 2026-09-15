import unittest
from unittest.mock import patch
import test_workspace as fixtures
from app import confirmations as c, studio as s, workspace as w

class Confirmations(unittest.TestCase):
    setUp=fixtures.WorkspaceTests.setUp
    tearDown=fixtures.WorkspaceTests.tearDown
    def offer(self):
        self.p['world_draft']='夜の街';self.p['active_context']='world'
        w.history(self.p,'world','夜の街にして','この世界観で確定しますか？')
        c.attach(self.p)
        with s.transaction() as db:s.put(db,self.p)
        return dict(id=self.p['id'],revision=self.p['revision'],message_id=self.p['chats'][-1]['id'])
    def test_accept_persists_world_without_api(self):
        body=self.offer()
        with patch('app.gemini.agent_turn') as llm,patch('app.gemini.image') as image:
            result=c.accept(self.user,body)
            llm.assert_not_called();image.assert_not_called()
        self.assertEqual(result['world']['text'],'夜の街')
        self.assertEqual(result['chats'][-2]['confirmation']['status'],'accepted')
        body['revision']=result['revision']
        with self.assertRaises(ValueError):c.accept(self.user,body)
    def test_changed_draft_cannot_be_confirmed_by_old_button(self):
        body=self.offer()
        with s.transaction() as db:
            p=s.get_work(db,self.user,self.p['id']);p['world_draft']='朝の街';s.put(db,p)
        with self.assertRaises(ValueError):c.accept(self.user,body)
    def test_scene_button_confirms_all_panels(self):
        f=fixtures.WorkspaceTests();f.setUp()
        try:
            sid,_=f.setup_scene();f.generate('scene',sid,[0,1])
            with s.transaction() as db:
                p=s.get_work(db,f.user,f.p['id']);c.attach(p,sid);s.put(db,p)
            result=c.accept(f.user,dict(id=p['id'],revision=p['revision'],message_id=p['chats'][-1]['id']))
            self.assertTrue(result['scenes'][0]['confirmed'])
            self.assertEqual(len(result['scenes'][0]['panels']),2)
        finally:f.tearDown()

    def test_character_confirmation_is_not_offered_again(self):
        from app.agent_tools import Toolset
        tool=Toolset(self.p,self.user,'キャラを作って')
        cid=tool.call('create_character',{'name':'ミナ','appearance':'黒髪','personality':'明るい','speech':'丁寧','background':'学生'})['id']
        character=w.item(self.p,'characters',cid);character['asset']={'sheet':'test.png'}
        w.history(self.p,cid,'OK','確定しますか？');c.attach(self.p,cid)
        with s.transaction() as db:s.put(db,self.p)
        result=c.accept(self.user,dict(id=self.p['id'],revision=self.p['revision'],message_id=self.p['chats'][-1]['id']))
        self.assertTrue(result['characters'][0]['approved'])
        self.assertIsNone(c.proposal(result,cid))
