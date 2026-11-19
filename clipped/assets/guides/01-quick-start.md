# Quick start

clipped runs entirely on your computer. It finds popular Twitch clips in the categories you pick, turns them into captioned vertical Shorts, and uploads them to **your** YouTube channel with **your** API keys. Nothing is sent to a clipped server. There isn't one.

## What you need

| Thing | Cost | Time |
| --- | --- | --- |
| A Twitch account with two-factor authentication on | free | 2 min |
| A Twitch developer app (Client ID + Secret) | free | 3 min |
| A Google Cloud project with the YouTube APIs enabled | free | 10 min |
| ffmpeg (bundled in the desktop app) | free | - |
| Optional: AI titles (one click: Claude sign-in, OpenRouter, or free local Ollama) | free to pay-as-you-go | 2 min |

## Steps

1. **Install and open clipped.** It opens in its own window (run `clipped shortcut` once to put it on your Desktop and Start Menu). Everything runs on your own computer.
2. **Twitch keys:** follow [Get your Twitch Client ID and Secret](#/guides/twitch), paste both into **Settings → Twitch**, and click **Test**.
3. **YouTube:** follow [Connect YouTube (Google Cloud setup)](#/guides/youtube), then click **Connect YouTube** in Settings.
4. **Pick categories:** in **Categories**, search for a game (Valorant, Counter-Strike, Fortnite, anything) and add it. Each category has its own minimum views, clip age window, language, daily limit, allowlist/blocklist and hashtags.
5. **Press Start** on the dashboard. clipped fetches clips, renders the best ones, and puts them in the **Review** queue.
6. **Review:** watch each Short, edit the title, description, hashtags, hook text or thumbnail, switch **Subtitles** off if a clip works better without them, then click **Approve**. Nothing is uploaded until you approve it.
7. When you trust the results, you can switch categories (or everything) to **Auto mode**. Read [Auto mode & staying safe](#/guides/safety) first.

## What happens to each clip

fetch top clips → skip anything already seen → download → transcribe on your computer (whisper) → burn in word-by-word captions → reframe to 9:16 → hook (trim dead air, flash-forward, on-screen hook text) → title, description and hashtags → thumbnail → review queue or scheduled upload.

Every upload credits the streamer by name, links their channel and the original clip, and includes `#Shorts`.

## Where your data lives

* Settings, queue and history: a SQLite file in your user data folder (shown under **Settings → About**).
* API keys: your operating system's keychain (Windows Credential Manager, macOS Keychain, or Linux Secret Service). Keys are never logged and never leave your computer except to the service they belong to.
* Whisper speech models are downloaded once from Hugging Face on first use, then run offline.
