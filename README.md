# know-today

An AI-curated daily briefing project. See [VISION.md](VISION.md) for the product direction.

## Fetch a YouTube transcript

This first source integration uses [`youtube-transcript-api`](https://github.com/jdepoix/youtube-transcript-api) to retrieve public YouTube captions (including auto-generated captions when available).

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/fetch_youtube_transcript.py 'https://www.youtube.com/watch?v=VIDEO_ID'
```

The command accepts a watch, Shorts, `youtu.be`, or direct 11-character video ID. It writes a readable transcript and raw timestamped data to `output/youtube/`; this is intentionally ignored by Git because it is fetched source material.

No API key is required for this library's standard public-caption endpoint. A fetch can still fail when captions are disabled or unavailable, the video is restricted, or YouTube blocks the requesting network.

### When YouTube blocks the machine's IP

For scheduled use, configure a rotating residential proxy. The upstream library directly supports Webshare's residential proxy service; keep its credentials outside the repository:

```sh
export KNOW_TODAY_WEBSHARE_PROXY_USERNAME='...'
export KNOW_TODAY_WEBSHARE_PROXY_PASSWORD='...'
.venv/bin/python scripts/fetch_youtube_transcript.py 'https://www.youtube.com/watch?v=VIDEO_ID'
```

The credentials are optional and are read only at runtime. Do not use YouTube account cookies: the library warns that doing so can lead to the account being permanently banned.

For a generic HTTP/HTTPS proxy, set both URLs instead:

```sh
export KNOW_TODAY_HTTP_PROXY='http://username:password@host:port'
export KNOW_TODAY_HTTPS_PROXY="$KNOW_TODAY_HTTP_PROXY"
```

## Generate a YouTube briefing

Subscriptions are private local configuration. Create `subscriptions.json` once from the tracked example, then replace the placeholder with the channel handles you want to follow:

```sh
cp subscriptions.example.json subscriptions.json
```

`subscriptions.json` is Git-ignored and must never be committed. Then route only this run through the Raspberry Pi tunnel:

```sh
export KNOW_TODAY_HTTP_PROXY='socks5h://127.0.0.1:1080'
export KNOW_TODAY_HTTPS_PROXY="$KNOW_TODAY_HTTP_PROXY"
.venv/bin/python scripts/generate_youtube_briefing.py
```

The script checks the newest video from every configured channel and stores private check state in `output/youtube/state.json` (which is Git-ignored). If every latest video has already been seen, it records a `no-new-sources` check and exits: it does not call Codex, create HTML, change GitHub Pages, commit, or push.

When at least one channel has a new video, the same command saves its metadata and transcript, asks the local `codex exec` CLI to create per-video learning notes, renders one static HTML briefing from only those new sources, copies it to `docs/briefings/YYYY-MM-DD.html`, updates the Pages homepage, and runs `git commit` plus `git push origin main`. It stages only those two public Pages files, leaving any other local work untouched. All generated source material and the state file remain under Git-ignored `output/youtube/`.

Pass `--force` to treat each channel's current latest video as new. Pass `--no-publish` to generate a briefing without touching GitHub Pages or Git.

## Publish briefings

Public artifacts live in `docs/`, which is intentionally tracked separately from the private generated `output/` directory. GitHub Pages can serve this directory after the repository is public: in the repository's **Settings → Pages**, select **Deploy from a branch**, then choose `main` and the `/docs` folder. The first published briefing is available from `docs/index.html`.

To route through a Raspberry Pi without exposing a public proxy, create a local SSH SOCKS tunnel to the Pi over Tailscale, then use:

```sh
export KNOW_TODAY_HTTP_PROXY='socks5h://127.0.0.1:1080'
export KNOW_TODAY_HTTPS_PROXY="$KNOW_TODAY_HTTP_PROXY"
```

## Daily schedule

Install the scheduler with:

```sh
scripts/run_daily_briefing.sh --install-service
```

On macOS this creates a LaunchAgent that invokes the one-shot checker every 15 minutes and at login. The checker runs the briefing once per local calendar day after `09:00` Finnish time, so it recovers after sleep, reboot, or a temporary network failure without rerunning a successful day. It restores the private Tailscale SSH SOCKS tunnel on port `1080` when needed.

Run one immediate check with `scripts/run_daily_briefing.sh --once`. Logs are written to `~/Library/Logs/know-today/`; the state file is private and Git-ignored under `output/youtube/`.
