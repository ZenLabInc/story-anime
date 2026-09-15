import unittest
from PIL import Image
from app import manga

class MultiBubbles(unittest.TestCase):
    def test_four_long_bubbles_fit_supported_sizes(self):
        bubbles=[{'text':'あ'*120,'speaker':0,'bubble_side':'right' if i%2==0 else 'left'} for i in range(4)]
        for size in [(720,1280),(864,1080),(1280,720)]:
            layouts=manga.bubble_layout(bubbles,size)
            for i,l in enumerate(layouts):
                x,y,r,b=l['box']
                self.assertTrue(0<=x<r<=size[0] and 0<=y<b+22<=size[1])
                for other in layouts[i+1:]:
                    a,c,d,e=other['box']
                    self.assertTrue(r<=a or d<=x or b<=c or e<=y)
            self.assertEqual(manga.letter_panel(Image.new('RGB',size,'gray'),{'bubbles':bubbles},size).size,size)
    def test_long_single_and_limit(self):
        self.assertEqual(manga.validate_dialogue('あ'*120),'あ'*120)
        with self.assertRaises(ValueError):manga.validate_dialogue('あ'*121)
        with self.assertRaises(ValueError):manga.dialogues({'bubbles':[{'text':'a','speaker':0,'bubble_side':'right'}]*5})
