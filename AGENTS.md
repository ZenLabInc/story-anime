# YourStory — ローカル漫画制作

README.md、docs/service.md、docs/product.md、docs/economics.md、docs/handoff.mdを読んでから変更する。
- 個人向け・漫画専用・フルカラー・一つのチャットを中心にする。
- 世界観・人物・シーンはLLMのnative tool loopで操作する。固定質問順を追加しない。
- 確定素材、指定セリフ、変更対象外の画像を保持する。
- 本人のGemini APIキーだけで生成する。未登録・失効時の別キーへの代替は禁止。
- 秘密値・作品・社内情報・本番運用記録をGitへ追加しない。
- 公開配布版は --local でloopbackにのみbindする。AWS・Stripe・メール設定は不要。
- planning/assumptions.json変更時は python3 scripts/cost_model.py --write と全Pythonテストを実行する。
- モック確認と実API検証を区別し、追加の生成を無断で行わない。
