import copy
import unittest
from unittest.mock import patch
import test_workspace as fixtures
from app import workspace as w, studio as s

class ConversationTests(unittest.TestCase):
    setUp=fixtures.WorkspaceTests.setUp
    tearDown=fixtures.WorkspaceTests.tearDown
    edit=fixtures.WorkspaceTests.edit
    talk=fixtures.WorkspaceTests.talk
    generate=fixtures.WorkspaceTests.generate

    def say(self,data,text='その案でお願い'):
        with patch('app.gemini.text',return_value=(data,{})) as api, patch('app.gemini.image') as image:
            self.p=w.chat(self.user,{'id':self.p['id'],'revision':self.p['revision'],'context':'studio','text':text})
            api.assert_called_once();image.assert_not_called()
            self.assertIn('active_context',api.call_args.args[1])
            self.assertLessEqual(len(api.call_args.args[1].encode()),18000)
        return self.p

    def test_world_approval_and_character_intake_share_one_turn(self):
        self.say({'operation':'edit','target':'world','world':'現代のジム起業','ready':True,'reply':'世界観の案'})
        reply='黒髪で自信なさげな理系大学生ですね。普段はどんな服装ですか？'
        self.say({'operation':'edit','target':'world','action':'approve','reply':reply,'character_intake':{'appearance':'黒髪、好青年だが自信なさげな顔','personality':'コミュニケーションが苦手','background':'理系大学の大学生','ready':False}},'OK。主人公は理系大学生で黒髪です')
        c=self.p['characters'][0]
        self.assertEqual(self.p['world']['text'],'現代のジム起業')
        self.assertEqual(c['background'],'理系大学の大学生');self.assertIn('黒髪',c['appearance'])
        self.assertEqual(c['personality'],'コミュニケーションが苦手');self.assertEqual(self.p['active_context'],c['id'])
        self.assertEqual(self.p['chats'][-1]['reply'],reply);self.assertIsNone(c['asset']);self.assertIsNone(c['approved'])

    def test_invalid_simultaneous_intake_does_not_partially_approve(self):
        self.say({'operation':'edit','target':'world','world':'現代','ready':True,'reply':'案'})
        with self.assertRaises(ValueError):
            self.say({'operation':'edit','target':'world','action':'approve','reply':'返答','character_intake':{'appearance':12}})
        stored=s.read_work(self.user,self.p['id'])
        self.assertEqual(stored['world']['text'],'');self.assertEqual(stored['characters'],[])

    def test_world_draft_is_attached_even_when_not_ready(self):
        self.say({'operation':'edit','target':'world','action':'update','reply':'概要をまとめました','world':'現代。AIによる失業が増え、少年がジムを起業する。','ready':False},'現代のジム経営です')
        proposal=self.p['chats'][-1]['proposal']
        self.assertEqual(proposal['text'],self.p['world_draft']);self.assertFalse(proposal['ready'])
        snapshot=copy.deepcopy(proposal)
        self.say({'operation':'edit','target':'world','action':'approve','reply':'承認'},'この下書きで確定して')
        self.assertEqual(self.p['world']['text'],snapshot['text'])
        self.say({'operation':'edit','target':'world','action':'update','reply':'変更案','world':'近未来の街','ready':True},'別の時代に変更したい')
        self.assertEqual(self.p['chats'][-3]['proposal'],snapshot)
        self.assertEqual(self.p['world']['text'],snapshot['text'])

    def test_one_conversation_world_character_and_return_to_world(self):
        self.say({'operation':'edit','target':'world','reply':'世界観案','world':'空中都市','ready':True})
        self.say({'operation':'edit','target':'world','action':'approve','reply':'保存'})
        self.say({'operation':'new_character','reply':'外見案','appearance':'青い髪の少年、白い制服','ready':True},'主人公をつくろう')
        cid=self.p['characters'][0]['id'];self.generate('character',cid)
        self.say({'operation':'edit','target':cid,'action':'approve','name':'空','reply':'保存'},'この見た目でOK。名前は空')
        self.say({'operation':'edit','target':cid,'reply':'性格案','personality':'明るい','speech':'僕、丁寧','ready':True})
        self.say({'operation':'edit','target':cid,'action':'approve','reply':'保存'})
        saved=copy.deepcopy(self.p['characters'][0]['versions'])
        self.say({'operation':'edit','target':'world','reply':'変更案','world':'海底都市','ready':True},'世界観だけ変えたい')
        self.assertEqual(self.p['world']['text'],'空中都市')
        self.assertEqual(self.p['characters'][0]['versions'],saved)
        self.assertEqual(self.p['active_context'],'world')
        self.say({'operation':'clarify','reply':'誰を変えますか？'},'あの子を変えたい')
        self.assertEqual(len(self.p['characters']),1)

    def test_scene_created_in_chat_and_confirmed_scene_is_forked(self):
        sid,_=fixtures.WorkspaceTests.setup_scene(self)
        cid=self.p['characters'][0]['id']
        self.generate('scene',sid,[0,1]);self.edit('scene_confirm',target=sid)
        original=copy.deepcopy(self.p['scenes'][0]);panels=copy.deepcopy(original['panels'])
        panels[0]['text']='また会おう。'
        self.say({'operation':'fork_scene','target':sid,'action':'update','reply':'別案です','title':'再会の別案','summary':'挨拶した','panels':panels,'selected_panels':[0]},'最初のシーンの1コマ目のセリフを変えて')
        self.assertEqual(self.p['scenes'][0],original)
        self.assertFalse(self.p['scenes'][1]['confirmed'])
        self.assertEqual(self.p['scenes'][1]['panels'][1],original['panels'][1])
        self.say({'operation':'new_scene','reply':'次のシーン','cast':[cid],'layout':'single','title':'翌日','summary':'待ち合わせ','panels':[{'direction':'広場','speaker':0,'text':'おはよう','bubble_side':'right'}]},'次のシーンは空の1コマで')
        self.assertEqual(len(self.p['scenes']),3)
        self.assertEqual(self.p['scenes'][-1]['characters'][0]['name'],'凛')

    def test_invalid_target_cannot_change_other_project_or_create_partial_draft(self):
        before=copy.deepcopy(self.p)
        with self.assertRaises(ValueError):self.say({'operation':'edit','target':'foreign-character','reply':'保存','action':'approve'})
        with s.transaction() as db:self.p=s.get_work(db,self.user,self.p['id'])
        self.assertEqual(self.p['characters'],before['characters'])
        with self.assertRaises(ValueError):self.say({'operation':'new_scene','reply':'案','cast':[],'layout':'single','panels':[]})
        with s.transaction() as db:self.p=s.get_work(db,self.user,self.p['id'])
        self.assertEqual(self.p['scenes'],[])
        self.assertIsNone(self.p['busy'])
