import copy, unittest
from PIL import Image
from app import manga,art_direction,workspace as w
from app.agent_tools import Toolset
import test_workspace as fixtures

class ArtControls(unittest.TestCase):
    setUp=fixtures.WorkspaceTests.setUp
    tearDown=fixtures.WorkspaceTests.tearDown
    def test_style_required_and_saved_without_rewriting_images(self):
        t=Toolset(self.p,self.user,'キャラを作る');cid=t.call('create_character',{'appearance':'黒髪'})['id']
        w.history(self.p,cid,'生成したい','三面図を生成してよいですか？')
        n=Toolset(self.p,self.user,'OK')
        with self.assertRaisesRegex(ValueError,'テイスト'):n.call('generate_images',{'id':cid,'confirmation_id':self.p['chats'][-1]['id']})
        before=copy.deepcopy(self.p['characters'])
        n.call('set_art_style',{'prompt':'細い線、淡い水彩風のフルカラー、少女漫画の雰囲気'})
        self.assertEqual(before,self.p['characters']);self.assertIn('水彩',self.p['art_style']['prompt'])
    def test_no_stretch_and_exact_ratios(self):
        source=Image.new('RGB',(100,100),'red');out=art_direction.normalize(source,(160,90))
        self.assertEqual(out.size,(160,90));self.assertEqual(out.getpixel((0,45)),(255,255,255));self.assertEqual(out.getpixel((80,45)),(255,0,0))
        for name,(_,boxes) in w.LAYOUTS.items():
            for x1,y1,x2,y2 in boxes:self.assertEqual((x2-x1)*9,(y2-y1)*16,name)
    def test_exact_text_supported_and_missing_glyph_rejected(self):
        text='「AI氷河期」でも50社目…やるぞ！'
        self.assertEqual(manga.validate_dialogue(text),text)
        self.assertEqual(''.join(''.join(c) for c in manga.columns(text)),text)
        self.assertIn('AI',sum(manga.columns(text),[]));self.assertIn('50',sum(manga.columns(text),[]))
        with self.assertRaises(ValueError):manga.validate_dialogue(chr(0x10ffff))
        with self.assertRaises(ValueError):manga.validate_dialogue('a'*121)
        self.assertEqual(manga.letter(Image.new('RGB',(500,500)),text).size,(1280,720))
    def test_dialogue_not_given_to_image_model(self):
        work={'characters':[{'name':'ミナ','description':'修理屋'}],'answers':{'story':'雨の町','style':'柔らかな水彩風'}}
        prompt=manga.art_prompt(work,{'text':'原文を絶対に渡さない','speaker':0,'direction':'ラジオを修理する','expression':'微笑む'})
        self.assertNotIn('原文を絶対に渡さない',prompt);self.assertIn('柔らかな水彩風',prompt)

    def test_punctuation_cannot_overflow_balloon(self):
        text='…'*55
        self.assertEqual(''.join(''.join(c) for c in manga.columns(text)),text)
        self.assertLess(manga.bubble_box(text,'right')[3]+45,720)
    def test_style_samples_are_media_and_allow_custom(self):
        t=Toolset(self.p,self.user,'見本を見せて')
        result=t.call('show_style_samples',{})
        self.assertEqual(len(result['styles']),5)
        self.assertTrue(result['custom_supported'])
