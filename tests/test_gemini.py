import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app import gemini, ai_story
class GeminiTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=(gemini.DB,gemini.ENABLED)
        gemini.DB=Path(self.tmp.name)/'usage.db';gemini.ENABLED=True
    def tearDown(self):gemini.DB,gemini.ENABLED=self.old;self.tmp.cleanup()
    def test_cap_and_unknown_never_retries(self):
        with patch.object(gemini,'key',return_value='secret'),patch('urllib.request.urlopen',side_effect=TimeoutError) as call:
            allowed=gemini.CONFIG['budget_jpy']//gemini.CONFIG['image_request_cap_jpy']
            for _ in range(allowed):
                with self.assertRaises(ValueError):gemini.request('test','image','test')
            self.assertEqual(call.call_count,allowed)
            with self.assertRaises(ValueError):gemini.request('test','image','test')
            self.assertEqual(call.call_count,allowed)
            self.assertEqual(gemini.budget()['reserved_or_spent_jpy'],allowed*gemini.CONFIG['image_request_cap_jpy'])
    def test_disabled_never_reads_secret_or_sends(self):
        gemini.ENABLED=False
        with patch.object(gemini,'key') as key,patch('urllib.request.urlopen') as call:
            with self.assertRaises(ValueError):gemini.text('test','x')
            key.assert_not_called();call.assert_not_called()
    def test_invalid_script_no_fixed_mutation(self):
        p={'title':'再会','shots':[{'text':'またね','direction':'駅','speaker':0}]*4}
        self.assertEqual(len(ai_story.validate(p,4,2,'またね')['shots']),4)
        for field,value in [('text','変更'),('speaker',2),('direction','')]:
            bad=json.loads(json.dumps(p));bad['shots'][-1][field]=value
            with self.assertRaises(ValueError):ai_story.validate(bad,4,2,'またね')
    def test_success_settles_usage_but_missing_usage_keeps_cap(self):
        import io
        response={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'{"ok":true}'}]}}], 'usageMetadata':{'promptTokenCount':100,'candidatesTokenCount':100}}
        with patch.object(gemini,'key',return_value='secret'),patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps(response).encode())):
            gemini.text('test','test')
        self.assertLess(gemini.budget()['reserved_or_spent_jpy'],1)
        del response['usageMetadata']
        with patch.object(gemini,'key',return_value='secret'),patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps(response).encode())):
            gemini.text('test','test')
        self.assertGreaterEqual(gemini.budget()['reserved_or_spent_jpy'],10)

    def test_oversize_before_send(self):
        with patch.object(gemini,'key',return_value='secret'),patch('urllib.request.urlopen') as call:
            with self.assertRaises(ValueError):gemini.text('test','あ'*7000)
            call.assert_not_called();self.assertEqual(gemini.budget()['calls'],0)

    def test_production_uses_provider_cap_instead_of_validation_cap(self):
        with patch.dict(os.environ, {'YOURSTORY_RUNTIME':'production'}):
            self.assertIsNone(gemini.budget()['limit_jpy'])
            gemini.reserve_global('production-call','test','text','model',gemini.CONFIG['budget_jpy'])
            self.assertEqual(gemini.budget()['calls'],1)
