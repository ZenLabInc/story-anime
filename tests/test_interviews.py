import copy
from unittest.mock import patch
import unittest
import test_workspace as fixtures

class InterviewTests(unittest.TestCase):
    setUp=fixtures.WorkspaceTests.setUp
    tearDown=fixtures.WorkspaceTests.tearDown
    edit=fixtures.WorkspaceTests.edit
    talk=fixtures.WorkspaceTests.talk
    generate=fixtures.WorkspaceTests.generate
    def test_appearance_first_and_personality_cannot_change_images(self):
        self.edit('character_new');cid=self.p['characters'][0]['id']
        self.talk(cid,{'reply':'服装は？','name':'凛','appearance':'短髪の少年','ready':False})
        self.assertEqual(self.p['characters'][0]['visual_state'],'interview')
        with self.assertRaises(ValueError):wquote=self.generate('character',cid)
        self.talk(cid,{'reply':'見た目が揃いました','name':'凛','appearance':'短髪の少年、白シャツ黒ベスト','ready':True})
        self.generate('character',cid);self.talk(cid,{'name':'凛','reply':'命名'},text='凛');self.edit('character_approve',target=cid)
        before=copy.deepcopy(self.p['characters'][0]['asset'])
        self.edit('world_save',text='時計の都市')
        with self.assertRaises(ValueError):self.edit('scene_new',characters=[cid],layout='single')
        with patch('app.gemini.image') as api:
            self.talk(cid,{'reply':'性格案','personality':'寡黙','speech':'俺、と短く話す','ready':True})
            self.edit('character_persona_approve',target=cid);api.assert_not_called()
        self.assertEqual(self.p['characters'][0]['asset'],before)
        self.edit('scene_new',characters=[cid],layout='single')
        self.assertIn('寡黙',self.p['scenes'][0]['characters'][0]['description'])
    def test_world_interview_then_amendment_does_not_change_confirmed_world(self):
        self.talk('world',{'reply':'ルールは？','world':'空中都市','ready':False})
        self.assertFalse(self.p['world_ready']);self.assertEqual(self.p['world']['text'],'')
        self.talk('world',{'reply':'確認してください','world':'空中都市。時計が魔法を動かす。白黒漫画。','ready':True})
        self.edit('world_save');before=copy.deepcopy(self.p['world'])
        self.talk('world',{'reply':'変更案','world':'海底都市。時計が魔法を動かす。白黒漫画。','ready':True})
        self.assertEqual(self.p['world'],before);self.assertNotEqual(self.p['world_draft'],before['text'])

    def test_name_after_image_keeps_asset_and_updates_sidebar_source(self):
        self.edit('character_new');cid=self.p['characters'][0]['id']
        self.talk(cid,{'reply':'準備できました','appearance':'赤い髪、青い制服の少年','ready':True})
        self.assertEqual(self.p['characters'][0]['name'],'新しいキャラ')
        self.generate('character',cid)
        self.assertIn('名前を教えて',self.p['chats'][-1]['reply'])
        with self.assertRaises(ValueError):self.edit('character_approve',target=cid)
        asset=copy.deepcopy(self.p['characters'][0]['asset'])
        with patch('app.gemini.image') as image:
            self.talk(cid,{'reply':'了解','name':'灯'},text='名前は灯にしたい')
            image.assert_not_called()
        self.assertEqual(self.p['characters'][0]['name'],'灯')
        self.assertEqual(self.p['characters'][0]['asset'],asset)
        self.edit('character_approve',target=cid)
        self.assertEqual(self.p['characters'][0]['versions'][-1]['name'],'灯')

    def test_full_color_survives_lettering(self):
        from PIL import Image
        from app import manga
        image=Image.new('RGB',(1280,720),(230,40,90))
        result=manga.letter(image,'こんにちは')
        self.assertEqual(result.getpixel((600,600)),(230,40,90))
        result=manga.letter(image,'')
        self.assertEqual(result.getpixel((600,600)),(230,40,90))

    def test_chat_world_approval_commits_existing_proposal_only(self):
        self.talk('world',{'reply':'案です','world':'海辺の街','ready':True})
        self.talk('world',{'reply':'保存しました','action':'approve','world':'勝手な別の街'},text='うん、その世界でいこう')
        self.assertEqual(self.p['world']['text'],'海辺の街')
        self.talk('world',{'reply':'どこを変えますか？','action':'clarify'},text='修正したい')
        self.assertEqual(self.p['world']['revision'],1)

    def test_chat_character_approval_name_and_immutable_profile(self):
        self.edit('character_new');cid=self.p['characters'][0]['id']
        self.talk(cid,{'reply':'案','appearance':'赤髪、青い制服','ready':True})
        with self.assertRaises(ValueError):self.talk(cid,{'reply':'保存','action':'approve'},text='OK')
        with fixtures.s.transaction() as db:self.p=fixtures.s.get_work(db,self.user,self.p['id'])
        self.generate('character',cid)
        self.talk(cid,{'reply':'確認','action':'approve'},text='この見た目がいい')
        self.assertFalse(self.p['characters'][0]['approved'])
        self.talk(cid,{'reply':'命名','name':'灯'},text='名前は灯')
        c=self.p['characters'][0];self.assertEqual(c['visual_state'],'confirmed')
        self.assertEqual(c['versions'][-1]['name'],'灯')
        self.talk(cid,{'reply':'性格案','personality':'優しい','speech':'僕','ready':True})
        self.talk(cid,{'reply':'保存しました','action':'approve','personality':'無断変更'},text='それでお願い')
        saved=copy.deepcopy(self.p['characters'][0]['versions'][-1])
        self.assertEqual(saved['profile']['personality'],'優しい')
        self.talk(cid,{'reply':'どこを変えますか','action':'clarify'},text='修正したい')
        self.assertEqual(self.p['characters'][0]['versions'][-1],saved)
        self.talk(cid,{'reply':'変更案','action':'revise_appearance','appearance':'黒髪、青い制服','ready':True},text='髪を黒くして')
        self.assertIsNone(self.p['characters'][0]['asset'])
        self.assertEqual(self.p['characters'][0]['versions'][-1],saved)

    def test_scene_chat_approval_does_not_require_panel_number(self):
        fixtures.WorkspaceTests.setup_scene(self)
        scene=self.p['scenes'][0]
        self.generate('scene',scene['id'],[0,1])
        before=copy.deepcopy(self.p['scenes'][0]['panels'])
        self.talk(scene['id'],{'reply':'保存しました','action':'approve'},text='このページでOKです')
        self.assertTrue(self.p['scenes'][0]['confirmed'])
        self.assertEqual(self.p['scenes'][0]['panels'],before)
