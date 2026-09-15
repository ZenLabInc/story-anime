import copy
import json
import unittest
from unittest.mock import patch
import test_workspace as fixtures
from app import workspace as w, studio as s, membership

class SoftDeleteTests(unittest.TestCase):
    setUp=fixtures.WorkspaceTests.setUp
    tearDown=fixtures.WorkspaceTests.tearDown
    edit=fixtures.WorkspaceTests.edit
    talk=fixtures.WorkspaceTests.talk
    generate=fixtures.WorkspaceTests.generate

    def test_hides_project_preserves_data_and_blocks_old_urls_and_generation(self):
        sid,_=fixtures.WorkspaceTests.setup_scene(self)
        self.generate('scene',sid,[0,1]);self.edit('scene_confirm',target=sid)
        original=copy.deepcopy(self.p);asset=s.DATA/original['scenes'][0]['output']
        with patch('app.gemini.text') as text,patch('app.gemini.image') as image:
            w.soft_delete(self.user,{'id':self.p['id'],'revision':self.p['revision']})
            text.assert_not_called();image.assert_not_called()
        self.assertEqual(w.projects(self.user),[]);self.assertTrue(asset.exists())
        with s.transaction() as db:retained=json.loads(db.execute('SELECT data FROM works WHERE id=?',(self.p['id'],)).fetchone()[0])
        for key in ['characters','world','scenes','chats']:self.assertEqual(retained[key],original[key])
        self.assertTrue(retained['deleted_at']);self.assertEqual(retained['deleted_by'],self.user)
        with self.assertRaises(PermissionError):s.read_work(self.user,self.p['id'])
        with self.assertRaises(PermissionError):s.file_path(self.user,original['scenes'][0]['output'])
        with self.assertRaises(PermissionError):w.chat(self.user,{'id':self.p['id'],'revision':retained['revision'],'context':'studio','text':'再生成して'})
        with patch('app.membership.plan',return_value=('free',{'projects':1})):membership.project_allowed(self.user)

    def test_other_user_stale_revision_and_busy_project_cannot_be_deleted(self):
        other=s.session()[0]['id']
        with self.assertRaises(PermissionError):w.soft_delete(other,{'id':self.p['id'],'revision':self.p['revision']})
        with self.assertRaises(ValueError):w.soft_delete(self.user,{'id':self.p['id'],'revision':0})
        self.p['busy']={'id':'running','kind':'image'}
        with s.transaction() as db:s.put(db,self.p)
        with self.assertRaises(ValueError):w.soft_delete(self.user,{'id':self.p['id'],'revision':self.p['revision']})
        self.assertEqual(len(w.projects(self.user)),1)
