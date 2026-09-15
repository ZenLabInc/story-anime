# YourStory — チャットで作るフルカラー漫画

自分のストーリーを話すだけで、世界観・キャラクター・漫画のコマを作れるローカルアプリです。**自分のPCで起動し、自分のGemini APIキーで使います。** 月額契約、AWS、Googleログイン、Stripeの設定は不要です。

> 実験的なプロトタイプです。アプリの月額利用料はありませんが、会話・画像生成にはGoogleのAPI利用料金がかかります。生成前の確認に「OK」と答えると画像生成が始まります。

## できること

- 一つのチャットで世界観・人物・シーンの相談、追加、修正
- 5種類の画風見本から選択、または好みの画風を自由に指定
- 正面・横・背面のキャラクター画像と、確定した設定の保存
- 日本語の吹き出し付き漫画、固定レイアウトのページ・縦読み画像
- PNG、ZIP、静止画を順に表示する無音MP4のダウンロード
- Enterで改行、Macは⌘Enter／WindowsはCtrl+Enterで送信

キャラや設定はサイドバーから確認できます。確定済みのコマを修正するときは元を保持します。動画生成AI、公開ギャラリー、月額課金は提供しません。

## 1. 必要なものを用意する

- **Git**（リポジトリのダウンロード用）
- **Python 3.12〜3.14** と pip
- **Google Chrome**（音声入力は環境によって使えない場合があります）
- **日本語フォント**。macOSは標準フォント、Ubuntu/WSLは下記のNoto CJKを使います。
- **FFmpeg**（MP4を書き出す場合）
- **Gemini APIキー**。取得方法は手順4へ。

Windowsは **WSL2 + Ubuntu** で実行してください。このアプリはファイルロックにUnixの機能を使うため、WindowsのPowerShellから直接のPython起動には対応していません。ブラウザはWindows側のChromeで構いません。

### macOS

PythonとGitが未導入なら公式の [Python](https://www.python.org/downloads/) と [Git](https://git-scm.com/downloads) からインストールしてください。Homebrewを使っている場合は次でも準備できます。

```sh
brew install python git ffmpeg
```

### Ubuntu / WindowsのWSL2 Ubuntu

Ubuntuのターミナルで実行します。

```sh
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip fonts-noto-cjk libraqm0 ffmpeg
```

## 2. ダウンロードして準備する

まず `python3 --version` を実行し、3.12以上か確認してください。macOS標準の3.9などが表示された場合は、新しく導入した `python3.14` などを以降の `python3` の代わりに使ってください。

「ターミナル」を開き、以下を1行ずつコピーして実行します。`git clone` はコードをPCへコピーし、`cd` はそのフォルダへ移動する操作です。

```sh
git clone https://github.com/ZenLabInc/story-anime.git
cd story-anime
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
```

`.venv` はこのアプリ専用のPython環境です。ほかのアプリとライブラリが混ざるのを防ぎます。

## 3. 起動する

```sh
.venv/bin/python -m app.server --local
```

ターミナルを開いたまま、Chromeで **[http://127.0.0.1:8765/app](http://127.0.0.1:8765/app)** を開きます。`127.0.0.1` は自分のPCを指します。メールアドレスやGoogleログインは不要です。

初回はデータの扱いの案内を確認し、表示名を入力してください。停止はターミナルで **Ctrl+C**。次回は同じフォルダで上の起動コマンドを実行するだけです。

## 4. 自分のAPIキーを登録する

1. [Google AI Studio](https://aistudio.google.com/apikey) でGemini APIキーを取得します。
2. Google側で画像生成モデルが利用できることと、請求設定・料金・利用上限を確認します。
3. アプリ左下のアカウント設定を開き、「Gemini APIキー」に入力して保存します。
4. 「新しい漫画」からタイトルを入力し、チャットを始めます。

キーの保存時はモデルへのアクセスだけを確認し、画像は生成しません。画像生成の実行権限や課金設定まですべて保証する確認ではありません。キーをGitHub、動画、スクリーンショット、チャット本文に貼らないでください。動画撮影中の登録操作にも注意してください。

キーが未登録・無効な場合は生成を停止します。会社や他人のキーへ自動で切り替わることはありません。

## 5. 最初の漫画を作る

例えば、次のように話しかけます。

> 海辺の町で、パン屋を継いだ青年が初めてのお客さんを迎える話。やわらかな日常漫画の画風で、縦読みの短い漫画を作りたい。

AIと相談し、画風・世界観・人物を決めます。画像生成の確認に答え、完成した画像を見て「この見た目でOK」「髪を短くして」などと返してください。漫画が完成したら「PNGでダウンロードしたい」「ショート用の無音動画にして」と頼めます。

## 保存場所とバックアップ

- 作品・会話・画像：`.local/studio/`
- APIキーの暗号鍵：`.local/local-key-encryption`
- 概算の生成履歴：`.local/gemini-usage.db`

アプリを止めてから **`.local` フォルダ全体** をコピーするとバックアップできます。このフォルダは秘密情報と作品を含むので公開しないでください。APIキーは暗号化して保存しますが、同じPCに暗号鍵があるためPC自体の保護も必要です。

このアプリはPC内の個人利用向けです。ポート開放や公開サーバーとしての運用はしないでください。生成時は文章や参照画像をGoogleへ送信します。音声入力はブラウザ提供元の認識サービスへ送信される場合があります。

## 困ったとき

| 症状 | 対処 |
|---|---|
| `python3` が見つからない | Pythonをインストールし、ターミナルを開き直してください |
| `fcntl` が見つからない | WindowsではWSL2のUbuntuから起動してください |
| 8765番ポートが使用中 | 起動済みのアプリを止めるか、`--port 8766` を付けて `http://127.0.0.1:8766/app` を開いてください |
| APIキーを保存できない | キーの制限、Gemini API、対象モデルへのアクセスをGoogle側で確認してください |
| 生成時に403・429が出る | モデルの権限、請求設定、利用上限をGoogle側で確認してください。無限に再送しないでください |
| 日本語が□になる | Noto CJKをインストールするか、起動前に `YOURSTORY_FONT` に日本語フォントの絶対パスを指定してください |
| MP4を書き出せない | `ffmpeg -version` が動くか確認してください |
| 画像・人物が不自然 | AI生成の限界があります。対象を指定して修正を依頼してください。再生成にもAPI料金がかかります |

モデル名と概算単価は `planning/assumptions.json` の `gemini` にあります。提供終了・アクセス制限で使えない場合は利用可能な互換モデルへ設定を変更してください。内部の費用推定はGoogleの確定請求額ではありません。

## 開発者向け

```sh
.venv/bin/python -m unittest discover -s tests -v
node tests/test_router.cjs
node tests/test_chat_shortcuts.cjs
node tests/test_markdown.cjs
node tests/test_voice.cjs
```

Pythonテストは外部の生成APIを呼びません。実APIでの品質確認とは区別してください。

主な実装：`app/server.py`（HTTP）、`app/manga_agent.py`（LLM会話）、`app/agent_tools.py`（制作操作）、`app/workspace.py`（作品）、`web/`（画面）。旧ホスト版の互換コードは一部残っていますが、`--local` では認証サービス・課金・運営キーを使いません。

[データの扱い](docs/accounts-plans.md) · [機能と制約](docs/product.md) · [公開前の確認結果](docs/release-check.md)

## ライセンス

コードは[MIT License](LICENSE)。第三者のライブラリ・アイコン・生成画像については[Third-party notices](THIRD_PARTY_NOTICES.md)を参照してください。
