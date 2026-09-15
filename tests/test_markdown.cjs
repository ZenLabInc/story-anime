const assert=require('node:assert/strict');const {render}=require('../web/markdown.js');
assert.match(render('## 人物\n\n- **名前**：ミナ\n- 黒髪'),/<h3>人物<\/h3><ul><li><strong>名前<\/strong>：ミナ<\/li><li>黒髪<\/li><\/ul>/);
assert.match(render('1. はじめ\n2. おわり'),/<ol><li>はじめ<\/li><li>おわり<\/li><\/ol>/);
for(const input of ['<img src=x onerror=alert(1)>','[go](javascript:alert(1))','![img](https://evil.test/pixel)','<script>alert(1)</script>','**<svg/onload=alert(1)>**'])assert.doesNotMatch(render(input),/<(?:img|script|svg|a)\b/i);
assert.match(render('```\n<script>'),/&lt;script&gt;/);assert.equal(render('`**plain**`'),'<p><code>**plain**</code></p>');
console.log('Markdown formatting, partial fences, raw HTML and unsafe URLs passed');
