# YourStory — Create full-color manga through chat

[日本語](README.md)

YourStory is an experimental local application for creating manga by describing your ideas in a single chat. It helps shape the setting, characters, art direction, panels, and revisions without requiring a finished script or drawings.

## What it does

- Discuss and revise settings, characters, and scenes in one conversation
- Choose from bundled art-style samples or describe another style
- Generate front, side, and back character views
- Compose Japanese dialogue with a local font instead of relying on image-model lettering
- Export fixed-layout pages, vertical-scroll images, PNG files, ZIP archives, and silent slideshow MP4 files
- Keep confirmed images while creating revisions as separate variants

The application runs on your computer and uses only the Gemini API key you register. There is no hosted account, subscription, AWS setup, or Stripe setup.

## Requirements

- Git
- Python 3.12–3.14
- Google Chrome
- A Japanese font; Noto CJK is recommended on Ubuntu/WSL
- FFmpeg for MP4 export
- A Gemini API key with access to the configured chat and image models

Windows users should run the Python server in WSL2 Ubuntu.

## Install and run

```sh
git clone https://github.com/ZenLabInc/story-anime.git
cd story-anime
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m app.server --local
```

Open <http://127.0.0.1:8765/app> in Chrome. Register your own Gemini API key from Settings, create a manga, and continue through the chat. Google may charge for chat and image-generation requests. Review the current model availability, pricing, and spending limits in Google AI Studio before generating images.

No login, display-name registration, or onboarding consent screen is required. Settings lists recorded input/output token totals and the latest 100 requests, without plan prices or cost estimates. Unknown usage is excluded from totals.

Explicit generation requests and instructions to keep going do not require repeated confirmation. Approving a front view generates the missing side and back views together, preserving the front image.

## Local data and privacy

Workspaces, conversations, and images are stored under `.local/studio/`. The API key is encrypted locally; its encryption key is stored on the same computer under `.local/local-key-encryption`. Back up the entire `.local` directory only while the application is stopped, and never commit or share it.

Text and reference images are sent to Google when generation is requested. Browser speech recognition may use the browser vendor's recognition service. Run this project only on loopback; it is not designed to be exposed as a public server.

## Development

```sh
.venv/bin/python -m unittest discover -s tests -v
node tests/test_router.cjs
node tests/test_chat_shortcuts.cjs
node tests/test_markdown.cjs
node tests/test_voice.cjs
```

Python tests do not call external generation APIs. Passing them does not validate current model availability or image quality.

## License

The source code is available under the [MIT License](LICENSE). See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for bundled third-party components and assets.
