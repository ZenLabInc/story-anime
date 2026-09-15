import copy,json,subprocess,unittest,zipfile,shutil
from PIL import Image
import test_workspace as fixtures
from app import publication as pub,studio as s,workspace as w,manga
from app.agent_tools import Toolset

class PublicationTests(unittest.TestCase):
    setUp=fixtures.WorkspaceTests.setUp
    tearDown=fixtures.WorkspaceTests.tearDown
    edit=fixtures.WorkspaceTests.edit
    talk=fixtures.WorkspaceTests.talk
    generate=fixtures.WorkspaceTests.generate
    setup_scene=fixtures.WorkspaceTests.setup_scene
    def test_prior_proposal_confirmation_required(self):
        t=Toolset(self.p,self.user,'ショート用')
        t.call('propose_publication',{'preset':'shorts','destination':'YouTubeショート'})
        with self.assertRaises(ValueError):t.call('confirm_publication',{})
        self.assertNotIn('publication',self.p)
        Toolset(self.p,self.user,'その形でOK').call('confirm_publication',{})
        self.assertEqual(self.p['publication']['panel_aspect'],'9:16')
        with self.assertRaises(ValueError):Toolset(self.p,self.user,'2コマ').call('propose_publication',{'preset':'unknown','destination':'test'})
    def test_pixel_geometry_and_reading_order(self):
        colors=['red','blue','green','yellow'];images=[Image.new('RGB',(1280,720),c) for c in colors]
        page=pub.compose({'publication':pub.proposal('page-four','')},images)
        self.assertEqual(page.size,(1080,1536))
        for pos,color in zip([(700,450),(200,450),(700,1153),(200,1153)],colors):self.assertEqual(page.getpixel(pos),Image.new('RGB',(1,1),color).getpixel((0,0)))
        scroll=pub.compose({'publication':pub.proposal('scroll','')},images)
        self.assertEqual(scroll.size,(1080,5544))
        for i,color in enumerate(colors):self.assertEqual(scroll.getpixel((540,i*1398+675)),Image.new('RGB',(1,1),color).getpixel((0,0)))
        short=pub.compose({'publication':pub.proposal('shorts','')},images)
        self.assertEqual(short.size,(1080,1920))
        for key in pub.PRESETS:
            size=pub.panel_size({'publication':pub.proposal(key,'')})
            self.assertEqual(manga.letter(Image.new('RGB',size),'「AIでも50社目！」',size=size).size,size)
    def scenes(self):
        dest=w.folder(self.p);panels=[]
        for i,color in enumerate(['red','blue']):
            path=dest/f'{i}.png';Image.new('RGB',(720,1280),color).save(path);panels.append({'asset':{'file':w.relative(path)}})
        return [{'id':'export-fixture','panels':panels}]
    def test_zip_and_original_preservation(self):
        scenes=self.scenes();before=copy.deepcopy(scenes)
        result=pub.export(self.p,scenes,'scroll');self.assertEqual(scenes,before)
        self.assertEqual(pub.export(self.p,scenes,'scroll')['id'],result['id'])
        self.assertEqual(len(self.p['exports']),1)
        with zipfile.ZipFile(s.DATA/result['files'][-1]['path']) as z:self.assertEqual(z.namelist(),['page-01.png','panel-01.png','panel-02.png'])
        with self.assertRaises(ValueError):pub.export(self.p,[{'panels':[{}]}],'scroll')
    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg runtime required')
    def test_real_mp4_dimensions_timing_and_frame_order(self):
        result=pub.export(self.p,self.scenes(),'shorts');path=s.DATA/result['files'][0]['path']
        data=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)]))
        video=data['streams'][0];self.assertEqual((video['width'],video['height']),(1080,1920));self.assertEqual(video['codec_name'],'h264');self.assertEqual(video['pix_fmt'],'yuv420p');self.assertAlmostEqual(float(data['format']['duration']),10,places=1)
        for second,channel in [(1,0),(6,2)]:
            raw=subprocess.check_output(['ffmpeg','-v','error','-ss',str(second),'-i',str(path),'-frames:v','1','-vf','scale=1:1','-f','rawvideo','-pix_fmt','rgb24','-']);self.assertGreater(raw[channel],200)

    def test_scene_snapshots_approved_format_and_rejects_wrong_layout(self):
        self.setup_scene()
        cast=[self.p['characters'][0]['id']]
        with self.assertRaisesRegex(ValueError,'掲載形式'):Toolset(self.p,self.user,'作って').call('create_scene',{'cast':cast,'layout':'two','title':'新作'})
        self.p['publication']=pub.proposal('page-four','漫画サイト')
        with self.assertRaisesRegex(ValueError,'コマ数'):Toolset(self.p,self.user,'作って').call('create_scene',{'cast':cast,'layout':'two','title':'新作'})
        scene=Toolset(self.p,self.user,'4コマ').call('create_scene',{'cast':cast,'layout':'four','title':'新作'})['scene']
        self.p['publication']=pub.proposal('shorts','YouTube')
        self.assertEqual(scene['publication']['preset'],'page-four')
