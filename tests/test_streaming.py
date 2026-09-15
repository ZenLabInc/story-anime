import io,json,unittest
from app.streaming import partial_reply,collect
class StreamingTests(unittest.TestCase):
 def test_partial_root_only_and_escapes(self):
  self.assertEqual(partial_reply('{"state":{"reply":"hidden"},"reply":"こん'), 'こん')
  self.assertEqual(partial_reply('{"reply":"一行\\n二行\\'), '一行\n二行')
  self.assertEqual(partial_reply('{"reply":"\\u304'), '')
  self.assertEqual(partial_reply('{"reply":"\\u3042'), 'あ')
 def test_provider_stream_reaches_callback_before_finished(self):
  seen=[]
  def frames():
   yield b'data: '+json.dumps({'candidates':[{'content':{'parts':[{'text':'{"reply":"hello'}]}}]}).encode()+b'\n'
   self.assertEqual(seen,['hello'])
   yield b'data: '+json.dumps({'candidates':[{'content':{'parts':[{'text':' world"}'}]},'finishReason':'STOP'}],'usageMetadata':{'promptTokenCount':5,'candidatesTokenCount':8}}).encode()+b'\n'
  result=collect(frames(),seen.append)
  self.assertEqual(seen[-1],'hello world');self.assertEqual(result['usageMetadata']['candidatesTokenCount'],8)
 def test_incomplete_rejected(self):
  with self.assertRaises(ValueError):collect(io.BytesIO(b''),lambda _:None)
 def test_native_tools_preserve_signature_and_hide_thoughts(self):
  signature={'functionCall':{'name':'get_workspace','args':{}},'thoughtSignature':'opaque-signature'}
  events=[{'candidates':[{'content':{'parts':[{'text':'private thought','thought':True},{'text':'確認します。'},signature]},'finishReason':'STOP'}]}]
  seen=[];result=collect([b'data: '+json.dumps(e).encode()+b'\n' for e in events],seen.append,json_reply=False)
  self.assertEqual(seen,['確認します。']);self.assertIn(signature,result['candidates'][0]['content']['parts'])
