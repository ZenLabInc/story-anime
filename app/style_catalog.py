"""Original, pre-generated style references; custom descriptions remain supported."""
STYLES=[
 {'id':'shonen','label':'少年漫画','description':'力強い線・鮮やかな色・躍動感','prompt':'日本の少年漫画風。力強くメリハリのあるペン線、鮮やかなフルカラー、くっきりしたセル塗り、躍動感のある表情。'},
 {'id':'shojo','label':'繊細な少女漫画','description':'細い線・淡いパステル・柔らかな表情','prompt':'繊細で柔らかな日本の少女漫画風。細いペン線、淡いパステル調のフルカラー、透明感のある塗り、優しい表情。'},
 {'id':'seinen','label':'落ち着いた青年漫画','description':'緻密な描写・自然な頭身・深い陰影','prompt':'落ち着いた日本の青年漫画風。自然な頭身、緻密なペン線とハッチング、抑えたフルカラー、深い陰影。写真ではなく手描き漫画。'},
 {'id':'slice-of-life','label':'やわらかな日常漫画','description':'丸い線・温かな色・親しみやすさ','prompt':'温かくやわらかな日常漫画風。丸みのあるシンプルな線、自然な少し低めの頭身、温かなフルカラー、平面的な塗り。'},
 {'id':'comical','label':'コミカル','description':'デフォルメ・太い輪郭・大きな表情','prompt':'コミカルな日本の漫画風。3頭身のデフォルメ、大きな表情、太い輪郭線、明快なフルカラー、シンプルなセル塗り。'}]

def public_styles():
    import json
    from app.studio import ROOT
    path=ROOT/'planning/style-assets.json'
    if not path.exists():return []
    base=json.loads(path.read_text()).get('base_url','')
    return [{**x,'image':base+'/'+x['id']+'.webp'} for x in STYLES] if base.startswith('https://') or base=='/styles' else []
