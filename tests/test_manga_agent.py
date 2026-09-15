import copy,unittest
from unittest.mock import patch
import test_workspace as fixtures
from app import manga_agent as agent,workspace as w,studio as s
from app.agent_tools import Toolset
class AgentTests(unittest.TestCase):
    setUp=fixtures.WorkspaceTests.setUp
    tearDown=fixtures.WorkspaceTests.tearDown
    def test_multiple_native_tools_and_result_roundtrip(self):
        self.p['world_draft']='現代の街'
        with s.transaction() as db:s.put(db,self.p)
        calls=[{'functionCall':{'name':'confirm_world','args':{}},'thoughtSignature':'preserve'}, {'functionCall':{'name':'create_character','args':{'appearance':'黒髪の青年','background':'理系大学生','personality':'内気'}}}]
        def model(pid,system,contents,tools,on_text=None):
            if len(contents)==1:return calls,{}
            self.assertEqual(contents[-2]['parts'],calls)
            self.assertEqual(contents[-1]['parts'][0]['functionResponse']['response']['confirmed'],True)
            self.assertIn('id',contents[-1]['parts'][1]['functionResponse']['response'])
            return [{'text':'世界観を確定し、黒髪の大学生の情報を保存しました。服装はどうしますか？'}],{}
        with patch('app.gemini.agent_turn',side_effect=model),patch('app.gemini.image') as image:
            result=agent.chat(self.user,dict(id=self.p['id'],revision=self.p['revision'],text='世界観OK、黒髪の内気な理系大学生です'))
            self.assertEqual(result['world']['text'],'現代の街');self.assertEqual(len(result['characters']),1);image.assert_not_called()
    def test_no_same_turn_generation_or_new_proposal_approval(self):
        w.history(self.p,'world','人物を作りたい','生成してよいですか？')
        t=Toolset(self.p,self.user,'はい')
        t.call('update_world',{'text':'現代'})
        with self.assertRaises(ValueError):t.call('confirm_world',{})
        cid=t.call('create_character',{'appearance':'黒髪の青年'})['id']
        with self.assertRaises(ValueError):t.call('generate_images',{'id':cid,'confirmation_id':self.p['chats'][-1]['id']})
        self.assertIsNone(t.execute)
    def test_failed_tool_does_not_mutate_and_agent_can_recover(self):
        t=Toolset(self.p,self.user,'人物を作る')
        with self.assertRaises(ValueError):t.call('create_character',{'name':'a'*61})
        self.assertEqual(self.p['characters'],[])
        self.assertEqual(len(t.artifacts),0)
    def test_free_text_confirmation_can_generate_without_quote_ui(self):
        t=Toolset(self.p,self.user,'人物を作る');cid=t.call('create_character',{'appearance':'黒髪'})['id']
        t.call('set_art_style',{'prompt':'柔らかな漫画風'})
        w.history(self.p,cid,'三面図を作りたい','この人物の三面図を生成してよいですか？')
        n=Toolset(self.p,self.user,'OK')
        n.call('generate_images',{'id':cid,'confirmation_id':self.p['chats'][-1]['id']})
        self.assertTrue(n.execute);self.assertGreater(self.p['quotes'][n.execute]['cap_jpy'],0)
        self.assertEqual(n.artifacts,[])
        with self.assertRaises(ValueError):n.call('update_character',{'id':cid,'name':'変更'})
    def test_delegated_generation_can_follow_same_turn_settings(self):
        t=Toolset(self.p,self.user,'見た目も任せるのでどんどん生成して')
        cid=t.call('create_character',{'appearance':'黒髪'})['id']
        t.call('set_art_style',{'prompt':'柔らかな漫画風'})
        t.call('generate_images',{'id':cid,'authorization':'user_request','instruction':'どんどん生成して','views':[0,1,2]})
        self.assertEqual(self.p['quotes'][t.execute]['panels'],[0,1,2])

    def test_front_approval_batches_missing_views_and_preserves_front(self):
        t=Toolset(self.p,self.user,'人物を作る')
        cid=t.call('create_character',{'appearance':'黒髪'})['id']
        t.call('set_art_style',{'prompt':'柔らかな漫画風'})
        c=w.item(self.p,'characters',cid)
        c['view_assets']={'front':{'file':'front.png'}}
        n=Toolset(self.p,self.user,'正面OK')
        n.call('generate_images',{'id':cid,'authorization':'front_approved','instruction':'正面OK','views':[1]})
        self.assertEqual(self.p['quotes'][n.execute]['panels'],[1,2])
        self.assertEqual(c['view_assets']['front']['file'],'front.png')

    def test_authorization_requires_real_user_evidence(self):
        t=Toolset(self.p,self.user,'相談したい')
        cid=t.call('create_character',{'appearance':'黒髪'})['id']
        t.call('set_art_style',{'prompt':'柔らかな漫画風'})
        with self.assertRaises(ValueError):
            t.call('generate_images',{'id':cid,'authorization':'user_request','instruction':'生成して'})
        self.assertIsNone(t.execute)

    def test_generation_completion_message_is_saved_with_images(self):
        from PIL import Image
        f=fixtures.WorkspaceTests();f.setUp()
        try:
            sid,_=f.setup_scene()
            q=w.quote(f.user,dict(id=f.p['id'],revision=f.p['revision'],kind='scene',target=sid,panels=[0,1]))
            message='時計のセリフを確認してください。OKなら次の場面を考えましょう。'
            with s.transaction() as db:
                p=s.get_work(db,f.user,f.p['id'])
                p['quotes'][q['quote']['id']]['completion_message']=message
                s.put(db,p)
            def image(pid,prompt,dest,reference=None,**kwargs):
                Image.new('RGB',(1280,720),'white').save(dest)
                return {'estimated_jpy':1}
            with patch('app.gemini.image',side_effect=image),patch('app.gemini.budget',return_value={'reserved_or_spent_jpy':0,'limit_jpy':500}):
                result=w.generate(f.user,dict(id=f.p['id'],quote_id=q['quote']['id']))
            self.assertEqual(result['chats'][-1]['reply'],message)
            self.assertTrue(result['chats'][-1]['images'])
        finally:f.tearDown()

    def test_shorts_preview_includes_all_four_panels_not_cover(self):
        scene={'publication':{'preset':'shorts'},'output':'cover.png','panels':[{'asset':{'file':f'panel-{i}.png'}} for i in range(4)]}
        self.assertEqual(w.scene_preview_images(scene),[f'panel-{i}.png' for i in range(4)])
        scene['publication']['preset']='scroll'
        self.assertEqual(w.scene_preview_images(scene),['cover.png'])

    def test_multiple_bubbles_edit_preserves_art_and_other_panels(self):
        f=fixtures.WorkspaceTests();f.setUp()
        try:
            sid,_=f.setup_scene();f.generate('scene',sid,[0,1])
            old=copy.deepcopy(f.p['scenes'][0]);t=Toolset(f.p,f.user,'1コマ目に吹き出しを4つ入れて')
            panels=[{k:p[k] for k in ['direction','text','speaker','bubble_side']} for p in old['panels']]
            panels[0]['bubbles']=[{'text':line,'speaker':0,'bubble_side':side} for line,side in [('ついにできた！','right'),('ここからが始まりだ。','left'),('誰に届けよう。','right'),('まずは試してもらおう。','left')]]
            with patch('app.gemini.image') as image:
                t.call('update_scene',{'id':sid,'title':old['title'],'summary':old['summary'],'panels':panels,'selected_panels':[0]})
                image.assert_not_called()
            scene=f.p['scenes'][0]
            self.assertEqual(len(scene['panels'][0]['bubbles']),4)
            self.assertEqual(scene['panels'][0]['asset']['raw'],old['panels'][0]['asset']['raw'])
            self.assertEqual(scene['panels'][1],old['panels'][1])
            self.assertTrue(scene['output'])
        finally:f.tearDown()

    def test_read_only_question_does_not_change_canon(self):
        with patch('app.gemini.agent_turn',return_value=([{'text':'こんにちは。漫画についても相談できます。'}],{})):
            result=agent.chat(self.user,dict(id=self.p['id'],revision=self.p['revision'],text='こんにちは'))
        self.assertEqual(result['characters'],[]);self.assertEqual(result['world']['text'],'')
    def test_combined_profile_confirmation_accepts_presented_visual(self):
        t=Toolset(self.p,self.user,'見た目も性格もこれでOK')
        cid=t.call('create_character',{'name':'ミナ','appearance':'黒髪','personality':'親切','speech':'丁寧語'})['id']
        c=w.item(self.p,'characters',cid);c['asset']={'sheet':'existing.png'}
        t=Toolset(self.p,self.user,'見た目も性格もこれでOK')
        t.call('confirm_character',{'id':cid,'scope':'profile'})
        self.assertEqual(c['visual_state'],'confirmed');self.assertEqual(c['persona_state'],'confirmed')
        self.assertEqual(c['versions'][-1]['profile']['personality'],'親切')
    def test_text_edit_reletters_without_image_call_and_preserves_other_panel(self):
        f=fixtures.WorkspaceTests();f.setUp()
        try:
            sid,_=f.setup_scene();f.generate('scene',sid,[0,1]);original=copy.deepcopy(f.p['scenes'][0])
            t=Toolset(f.p,f.user,'1コマ目のセリフだけ変更')
            panels=[{k:p[k] for k in ['direction','text','speaker','bubble_side']} for p in original['panels']]
            panels[0]['text']='できた。'
            with patch('app.gemini.image') as image:
                t.call('update_scene',{'id':sid,'title':original['title'],'summary':original['summary'],'panels':panels,'selected_panels':[0]});image.assert_not_called()
            after=f.p['scenes'][0]
            self.assertEqual(after['panels'][1],original['panels'][1]);self.assertEqual(after['panels'][0]['asset']['raw'],original['panels'][0]['asset']['raw'])
            self.assertNotEqual(after['panels'][0]['asset']['file'],original['panels'][0]['asset']['file']);self.assertTrue(after['output'])
        finally:f.tearDown()
    def test_missing_or_old_confirmation_rejected(self):
        t=Toolset(self.p,self.user,'人物を作る');cid=t.call('create_character',{'appearance':'黒髪'})['id']
        n=Toolset(self.p,self.user,'生成して')
        with self.assertRaises(ValueError):n.call('generate_images',{'id':cid,'confirmation_id':'missing'})
        w.history(self.p,cid,'質問','返答')
        n=Toolset(self.p,self.user,'OK')
        with self.assertRaises(ValueError):n.call('generate_images',{'id':cid,'confirmation_id':'old'})

    def test_failed_edit_can_retry_after_releasing_fixed_line(self):
        f=fixtures.WorkspaceTests();f.setUp()
        try:
            sid,_=f.setup_scene();f.generate('scene',sid,[0,1]);scene=f.p['scenes'][0]
            old='最後の一通、届けてきます。';scene['panels'][0]['text']=old;scene['fixed_lines']=[old]
            with s.transaction() as db:s.put(db,f.p)
            panels=[{k:p[k] for k in ['direction','text','speaker','bubble_side']} for p in scene['panels']];panels[0]['text']='お待たせしました。'
            edit={'functionCall':{'name':'update_scene','args':{'id':sid,'title':scene['title'],'summary':scene['summary'],'panels':panels,'selected_panels':[0]}}}
            rounds=iter([[edit],[edit],[{'functionCall':{'name':'release_fixed_lines','args':{'id':sid,'lines':[old]}}}],[edit],[{'text':'セリフを変更しました。'}]])
            with patch('app.gemini.agent_turn',side_effect=lambda *a,**k:(next(rounds),{})),patch('app.gemini.image') as image:
                result=agent.chat(f.user,{'id':f.p['id'],'revision':f.p['revision'],'text':'セリフを「お待たせしました。」へ変更して'})
                image.assert_not_called()
            updated=result['scenes'][0]['panels'][0]
            self.assertEqual(updated['text'],'お待たせしました。')
            self.assertEqual(updated['asset']['raw'],scene['panels'][0]['asset']['raw'])
            trace=result['chats'][-1]['tool_trace'];self.assertEqual([x['ok'] for x in trace],[False,False,True,True])
        finally:f.tearDown()
