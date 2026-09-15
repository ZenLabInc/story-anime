import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app import studio as s, gemini, yourstory as y

class YourStoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=(s.DATA,s.DB,gemini.ENABLED)
        s.DATA=Path(self.tmp.name);s.DB=s.DATA/'studio.db';gemini.ENABLED=True;s.init();self.user=s.session()[0]['id'];self.w=y.create(self.user)
        self.profile={'genre':'少年漫画','setting':'魔法学園','characters':[{'name':'蓮','description':'男子、黒髪、強気'},{'name':'律','description':'男子、白髪、冷静'}],'story':'二人のライバルが魔法で激突する','ending':'互いを認め合う','style':y.DEFAULT_STYLE,'fixed_lines':[]}
    def tearDown(self):s.DATA,s.DB,gemini.ENABLED=self.old;self.tmp.cleanup()
    def talk(self,text,p=None):
        with patch('app.gemini.text',return_value=({'profile':p or self.profile,'reply':'設定をまとめました。'},{})):
            self.w=y.chat(self.user,self.w['id'],text,self.w['revision'])
        return self.w
    def test_unordered_request_updates_all_and_not_dialogue(self):
        w=self.talk('男子2人が魔法学園で戦う漫画。最後は互いを認める。人物名はおまかせ')
        self.assertEqual(w['step'],'brief_review');self.assertEqual(w['profile']['characters'],self.profile['characters']);self.assertEqual(w['profile']['fixed_lines'],[])
        self.assertEqual(w['shots'],[])
    def test_inferred_fixed_line_rejected(self):
        p=copy.deepcopy(self.profile);p['fixed_lines']=['男子2人が戦う漫画を描きたい']
        w=self.talk('男子2人が戦う漫画を描きたい',p);self.assertEqual(w['profile']['fixed_lines'],[])
    def test_explicit_fixed_line_and_any_panel(self):
        p=copy.deepcopy(self.profile);p['fixed_lines']=['負けない。']
        self.talk('「負けない。」というセリフを残したい',p)
        shots=[{'text':'負けない。' if i==1 else '行くぞ','direction':'対峙','speaker':i%2,'bubble_side':'left','expression':'neutral'} for i in range(4)]
        with patch('app.gemini.text',return_value=({'title':'対決','shots':shots},{})):
            w=y.script(self.user,self.w['id'],self.w['revision'])
        self.assertEqual(w['shots'][1]['text'],'負けない。');self.assertNotEqual(w['shots'][-1]['text'],'負けない。')
    def test_brief_undo(self):
        self.talk('結末から考えたい')
        w=y.chat(self.user,self.w['id'],'戻る',self.w['revision'])
        self.assertEqual(w['step'],'interview');self.assertEqual(w['profile']['characters'],[])
    def test_quote_includes_character_reference(self):
        self.talk('おまかせ')
        shots=[{'text':'行くぞ','direction':'対峙する','speaker':i%2} for i in range(4)]
        with patch('app.gemini.text',return_value=({'title':'対決','shots':shots},{})):
            w=y.script(self.user,self.w['id'],self.w['revision'])
        w=s.approve(self.user,w['id'],w['revision'])
        self.assertEqual(w['quote']['images'],5)
        self.assertEqual(w['quote']['reference_images'],1)
        self.assertEqual(w['quote']['external_api_cap_jpy'],300)

    def test_manga_only_and_preapproval(self):
        self.assertEqual(self.w['mode'],'comic')
        with self.assertRaises(ValueError):y.script(self.user,self.w['id'],self.w['revision'])
    def test_balloon_fits_long_japanese(self):
        try:from PIL import Image;from app.manga import letter,bubble_box
        except ImportError:self.skipTest('Pillow requires venv')
        for side in ('left','right'):
            box=bubble_box('あ'*55,side);self.assertTrue(0<=box[0]<box[2]<=1280);self.assertTrue(0<=box[1]<box[3]<=720)
            im=letter(Image.new('RGB',(1280,720),'gray'),'あ'*55,side)
            self.assertEqual(im.size,(1280,720));self.assertEqual(im.getpixel((int((box[0]+box[2])/2),box[1]+10)),(255,255,255))
