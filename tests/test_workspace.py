import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from app import studio as s, workspace as w, gemini

class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=s.DATA,s.DB,gemini.ENABLED
        s.DATA=Path(self.tmp.name);s.DB=s.DATA/'studio.db';gemini.ENABLED=True;s.init()
        self.user=s.session()[0]['id'];self.p=w.create(self.user,'時計塔の約束')
    def tearDown(self):s.DATA,s.DB,gemini.ENABLED=self.old;self.tmp.cleanup()
    def edit(self,op,**kw):self.p=w.mutate(self.user,dict(id=self.p['id'],revision=self.p['revision'],op=op,**kw));return self.p
    def talk(self,ctx,data,text='おまかせ'):
        with patch('app.gemini.text',return_value=(data,{})):
            self.p=w.chat(self.user,dict(id=self.p['id'],revision=self.p['revision'],context=ctx,text=text))
    def generate(self,kind,target,panels=None,fail_at=None):
        q=w.quote(self.user,dict(id=self.p['id'],revision=self.p['revision'],kind=kind,target=target,panels=panels or [0]));self.p=q['project'];calls=[]
        def fake(pid,prompt,dest,reference=None,**kwargs):
            calls.append(dest)
            if fail_at==len(calls):raise ValueError('通信失敗')
            Image.new('RGB',(1280,720),'white').save(dest);return {'estimated_jpy':1}
        with patch('app.gemini.image',side_effect=fake),patch('app.gemini.budget',return_value={'reserved_or_spent_jpy':0,'limit_jpy':500}):
            self.p=w.generate(self.user,dict(id=self.p['id'],quote_id=q['quote']['id']))
        return q,calls
    def setup_scene(self,layout='two'):
        self.edit('world_save',text='空中都市。魔法は時計で動く。')
        self.edit('character_new');cid=self.p['characters'][0]['id']
        self.talk(cid,{'name':'凛','description':'黒髪短髪の少年。大きな時計を持つ。','reply':'設定案です','ready':True})
        self.generate('character',cid);self.talk(cid,{'name':'凛','reply':'命名'},text='凛');self.edit('character_approve',target=cid)
        self.talk(cid,{'reply':'性格案です','personality':'約束を守る','speech':'短く話す','ready':True})
        self.edit('character_persona_approve',target=cid)
        self.edit('scene_new',characters=[cid],layout=layout);scene=self.p['scenes'][0]
        data={'title':'再会','summary':'凛が時計を直した。','reply':'コマ案です','panels':[{'direction':'時計を見つめる少年','speaker':0,'text':'間に合った。','bubble_side':'right'} for _ in w.LAYOUTS[layout][1]]}
        self.talk(scene['id'],data);return scene['id'],data
    def test_end_to_end_snapshots_and_private_assets(self):
        sid,data=self.setup_scene();q,calls=self.generate('scene',sid,[0,1]);self.assertEqual(len(calls),2)
        scene=self.p['scenes'][0];original=copy.deepcopy(scene)
        self.edit('scene_confirm',target=sid);self.edit('world_save',text='新しい世界')
        self.assertEqual(self.p['scenes'][0]['world'],original['world'])
        self.assertTrue(s.file_path(self.user,scene['output']).exists())
        other=s.session()[0]['id']
        with self.assertRaises(PermissionError):s.file_path(other,scene['output'])
        with self.assertRaises(PermissionError):w.mutate(other,dict(id=self.p['id'],revision=self.p['revision'],op='character_new'))
        self.assertEqual(s.state(self.user)['mine'],[])
        with self.assertRaises(ValueError):self.edit('summary_save',target=sid,text='変更')
        self.edit('scene_fork',target=sid);self.assertFalse(self.p['scenes'][-1]['confirmed']);self.assertEqual(self.p['scenes'][0]['output'],original['output'])
    def test_double_generate_never_resends_and_stale_quote(self):
        sid,_=self.setup_scene();q,_=self.generate('scene',sid,[0])
        with patch('app.gemini.image') as image:
            w.generate(self.user,dict(id=self.p['id'],quote_id=q['quote']['id']));image.assert_not_called()
        q=w.quote(self.user,dict(id=self.p['id'],revision=self.p['revision'],kind='scene',target=sid,panels=[1]));self.p=q['project']
        self.edit('summary_save',target=sid,text='変更')
        with self.assertRaises(ValueError):w.generate(self.user,dict(id=self.p['id'],quote_id=q['quote']['id']))
    def test_partial_failure_saves_first_result_and_does_not_retry(self):
        sid,_=self.setup_scene()
        with self.assertRaises(ValueError):self.generate('scene',sid,[0,1],fail_at=2)
        self.p=s.read_work(self.user,self.p['id']);scene=self.p['scenes'][0]
        self.assertIsNotNone(scene['panels'][0]['asset']);self.assertIsNone(scene['panels'][1]['asset']);self.assertIsNone(self.p['busy'])
    def test_selected_and_held_panels_preserved_text_only_no_image_api(self):
        sid,data=self.setup_scene();self.generate('scene',sid,[0,1]);before=copy.deepcopy(self.p['scenes'][0]['panels'])
        self.edit('panel_hold',target=sid,panel=1,held=True)
        data['panels'][0]['text']='やっと直った。';data['panels'][1]['direction']='勝手に変更'
        with patch('app.gemini.image') as image:self.talk(sid,data,'1コマ目のセリフを修正');image.assert_not_called()
        after=self.p['scenes'][0]['panels'];self.assertEqual(after[0]['asset']['raw'],before[0]['asset']['raw']);self.assertNotEqual(after[0]['asset']['file'],before[0]['asset']['file']);self.assertEqual(after[1]['asset'],before[1]['asset']);self.assertEqual(after[1]['direction'],before[1]['direction'])
    def test_world_chat_pending_until_confirmation_and_character_versions(self):
        self.talk('world',{'world':'空中都市','reply':'提案です'});self.assertEqual(self.p['world']['text'],'')
        sid,_=self.setup_scene();old=copy.deepcopy(self.p['scenes'][0]['characters']);cid=self.p['characters'][0]['id']
        self.edit('character_visual_edit',target=cid)
        self.talk(cid,{'name':'凛','description':'長髪に変更','reply':'変更案です'})
        self.assertIsNone(self.p['characters'][0]['asset']);self.assertEqual(self.p['scenes'][0]['characters'],old)
    def test_restart_recovery_and_cross_project_traversal(self):
        with s.transaction() as db:self.p['busy']={'id':'x'};s.put(db,self.p)
        w.init();self.assertIsNone(s.read_work(self.user,self.p['id'])['busy'])
        other=w.create(s.session()[0]['id'],'他人');target=s.DATA/other['id'];target.mkdir();Image.new('RGB',(1,1)).save(target/'private.png')
        with self.assertRaises(PermissionError):s.file_path(self.user,self.p['id']+'/../'+other['id']+'/private.png')
    def test_fixed_dialogue_not_silently_removed(self):
        sid,data=self.setup_scene();self.talk(sid,data,'1コマ目の「間に合った。」を固定セリフにする')
        changed=copy.deepcopy(data)
        for panel in changed['panels']:panel['text']='違うセリフ'
        with self.assertRaises(ValueError):self.talk(sid,changed,'全体を明るくして')
        self.assertEqual(s.read_work(self.user,self.p['id'])['scenes'][0]['panels'][0]['text'],'間に合った。')
