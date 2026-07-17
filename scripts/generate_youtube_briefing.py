#!/usr/bin/env python3
"""Fetch the newest videos from configured channels and generate a static briefing."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUBSCRIPTIONS = PROJECT_ROOT / "subscriptions.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "output" / "youtube"
EXTRACT_PROMPT = PROJECT_ROOT / "prompts" / "extract_youtube_learnings.md"
RENDER_PROMPT = PROJECT_ROOT / "prompts" / "render_youtube_briefing.md"


def proxy_settings() -> dict[str, str] | None:
    """Use only the explicitly configured proxy; never alter global proxy settings."""
    http_proxy = os.environ.get("KNOW_TODAY_HTTP_PROXY")
    https_proxy = os.environ.get("KNOW_TODAY_HTTPS_PROXY")
    if bool(http_proxy) != bool(https_proxy):
        raise ValueError("Set both KNOW_TODAY_HTTP_PROXY and KNOW_TODAY_HTTPS_PROXY, or neither.")
    return {"http": http_proxy, "https": https_proxy} if http_proxy else None


def load_channels(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    channels = data.get("youtube_channels") if isinstance(data, dict) else None
    if not isinstance(channels, list) or not channels or not all(isinstance(item, str) and item.strip() for item in channels):
        raise ValueError(f"{path} must contain a non-empty youtube_channels string array.")
    return [item.strip().lstrip("@") for item in channels]


def newest_video(channel: str, proxies: dict[str, str] | None) -> dict[str, str]:
    response = requests.get(
        f"https://www.youtube.com/@{channel}/videos",
        proxies=proxies,
        timeout=30,
    )
    response.raise_for_status()
    match = re.search(r"watch\?v=([A-Za-z0-9_-]{11})", response.text)
    if not match:
        raise RuntimeError(f"Could not find a video on @{channel}'s videos page.")

    video_id = match.group(1)
    source_url = f"https://www.youtube.com/watch?v={video_id}"
    oembed = requests.get(
        "https://www.youtube.com/oembed",
        params={"url": source_url, "format": "json"},
        proxies=proxies,
        timeout=30,
    )
    oembed.raise_for_status()
    details = oembed.json()
    return {"channel": channel, "video_id": video_id, "source_url": source_url, "title": details.get("title", video_id), "author": details.get("author_name", channel)}


def run_codex(prompt: str, output_path: Path) -> None:
    codex = shutil.which("codex")
    if not codex:
        raise RuntimeError("Codex CLI was not found in PATH. Install it and sign in before running this script.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([codex, "exec", "--sandbox", "read-only", "--ephemeral", "--cd", str(PROJECT_ROOT), "--output-last-message", str(output_path), prompt], check=True)


def extract_learnings(transcript_path: Path, learning_path: Path) -> None:
    prompt = EXTRACT_PROMPT.read_text(encoding="utf-8").format(transcript_path=transcript_path)
    run_codex(prompt, learning_path)


def render_briefing(learnings_dir: Path, briefing_path: Path) -> None:
    prompt = RENDER_PROMPT.read_text(encoding="utf-8").format(learnings_dir=learnings_dir)
    run_codex(prompt, briefing_path)
    html = briefing_path.read_text(encoding="utf-8")
    if re.search(r"\b(?:cto|knowtoday)\b", html, re.IGNORECASE):
        briefing_path.unlink(missing_ok=True)
        raise RuntimeError("Codex used a forbidden term; no HTML briefing was retained. Run the script again.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subscriptions", type=Path, default=DEFAULT_SUBSCRIPTIONS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--force", action="store_true", help="Recreate learning notes even when they already exist.")
    args = parser.parse_args()

    try:
        proxies = proxy_settings()
        channels = load_channels(args.subscriptions)
        videos_dir = args.output_dir / "videos"
        learnings_dir = args.output_dir / "learnings"
        videos_dir.mkdir(parents=True, exist_ok=True)
        learnings_dir.mkdir(parents=True, exist_ok=True)

        for channel in channels:
            video = newest_video(channel, proxies)
            video["fetched_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            video_path = videos_dir / f"{video['video_id']}.json"
            video_path.write_text(json.dumps(video, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")
            print(f"@{channel}: {video['title']} ({video['source_url']})")

            transcript_path = args.output_dir / f"{video['video_id']}.md"
            if not transcript_path.exists():
                subprocess.run([sys.executable, str(PROJECT_ROOT / "scripts" / "fetch_youtube_transcript.py"), video["source_url"], "--output-dir", str(args.output_dir)], check=True)

            learning_path = learnings_dir / f"{video['video_id']}.md"
            if args.force or not learning_path.exists():
                extract_learnings(transcript_path, learning_path)
                print(f"Learnings: {learning_path}")
            else:
                print(f"Learnings already exist: {learning_path}")

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
        briefing_path = args.output_dir / "briefings" / f"{timestamp}.html"
        render_briefing(learnings_dir, briefing_path)
        print(f"Briefing: {briefing_path}")
    except (OSError, ValueError, requests.RequestException, subprocess.CalledProcessError, RuntimeError) as error:
        print(f"Could not generate the YouTube briefing: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
