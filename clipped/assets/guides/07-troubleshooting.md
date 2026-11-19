# Troubleshooting

**The clipped window doesn't open.** clipped uses a Microsoft Edge (or Chrome) app window. If neither is installed it opens a normal browser tab instead; you can also force that with `clipped app --window browser`, or run `clipped serve` and visit <http://localhost:8000> yourself. If another program uses port 8000, the app picks the next free port automatically; for `clipped serve` use `--port 8010`. With a Web-application Google client, add the new redirect URI too.

**Transcription fails with "unexpected keyword argument 'metadata_errors'".** Fixed in this version: update clipped (`git pull`, then `pip install -e .`). clipped now decodes audio with ffmpeg itself instead of going through PyAV.

**"YouTube access expired or was revoked."** Your Google app is still in *Testing* mode, which expires sign-ins after 7 days. Publish the app (see the YouTube guide, step 3), then click **Connect YouTube** again.

**Uploads are private even though I chose Public.** Your Google Cloud project hasn't passed the YouTube API audit yet. See the YouTube guide, step 7. In the meantime, switch videos to Public in YouTube Studio.

**"quotaExceeded".** You've used the day's 10,000 API units (about 6 uploads). clipped resumes automatically after midnight Pacific time.

**Thumbnail not set.** Verify your channel with a phone number at <https://www.youtube.com/verify>.

**Captions are missing or use the wrong font.** Your ffmpeg lacks libass. Install one of the builds in the ffmpeg guide and run `clipped doctor`.

**The first clip takes a long time.** The first run downloads the whisper speech model (about 150 MB for `base`). Later clips take seconds to a minute, depending on your CPU. A smaller model (`tiny`) is faster. A larger one (`small`, `medium`) is more accurate.

**Secrets are stored in a file, not the keychain.** No OS keyring was found (common on headless Linux and in Docker). The file is readable only by your user account. On Linux desktops, install `gnome-keyring` or KWallet and restart clipped.

**Where are the logs?** On the dashboard (live), and in the `logs` folder inside the data directory shown in **Settings → About**.
