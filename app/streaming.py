"""Provider SSE and partial root reply decoding. Never expose structured state."""
import json

def partial_reply(raw):
    decoder=json.JSONDecoder();i=0
    try:
        while raw[i].isspace():i+=1
        if raw[i]!='{':return ''
        i+=1
        while True:
            while raw[i].isspace() or raw[i]==',':i+=1
            key,end=decoder.raw_decode(raw,i);i=end
            while raw[i].isspace():i+=1
            if raw[i]!=':':return ''
            i+=1
            while raw[i].isspace():i+=1
            if key=='reply':
                if raw[i]!='"':return ''
                start=i;i+=1;end=i;escaped=False
                while i<len(raw):
                    c=raw[i]
                    if c=='"' and not escaped:return decoder.raw_decode(raw,start)[0][:1500]
                    if c=='\\' and not escaped:escaped=True
                    else:escaped=False
                    i+=1
                    if not escaped:end=i
                # Trim incomplete escapes (including unicode escape digits).
                fragment=raw[start:end]
                while len(fragment)>1:
                    try:return json.loads(fragment+'"')[:1500]
                    except ValueError:fragment=fragment[:-1]
                return ''
            _,i=decoder.raw_decode(raw,i)
    except (ValueError,IndexError,TypeError):return ''

def collect(response,on_text,json_reply=True):
    raw='';last={};parts=[];finished=False
    for line in response:
        if not line.startswith(b'data:'):continue
        packet=json.loads(line[5:].decode())
        if packet.get('error'):raise ValueError('Provider stream error')
        if 'usageMetadata' in packet:last['usageMetadata']=packet['usageMetadata']
        candidates=packet.get('candidates',[])
        if not candidates:continue
        candidate=candidates[0]
        if candidate.get('finishReason'):last['finishReason']=candidate['finishReason'];finished=True
        for part in candidate.get('content',{}).get('parts',[]):
            parts.append(part)
            if not part.get('thought') and 'text' in part:
                raw+=part.get('text','');on_text((partial_reply(raw) if json_reply else raw).encode('utf-8','ignore').decode('utf-8'))
    if not finished:raise ValueError('Incomplete provider stream')
    return {'candidates':[{'content':{'parts':parts},'finishReason':last.get('finishReason')}],'usageMetadata':last.get('usageMetadata',{})}
