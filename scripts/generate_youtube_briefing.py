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
DEFAULT_DOCS = PROJECT_ROOT / "docs"
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
    if not path.is_file():
        raise FileNotFoundError(
            f"{path} does not exist. Copy subscriptions.example.json to subscriptions.json, then add your channel handles."
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    channels = data.get("youtube_channels") if isinstance(data, dict) else None
    if not isinstance(channels, list) or not channels or not all(isinstance(item, str) and item.strip() for item in channels):
        raise ValueError(f"{path} must contain a non-empty youtube_channels string array.")
    return [item.strip().lstrip("@") for item in channels]


def load_state(path: Path) -> dict:
    """Load the private, ignored record of videos already published."""
    if not path.exists():
        return {"version": 1, "channels": {}, "checks": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("channels", {}), dict):
        raise ValueError(f"{path} is not a valid briefing state file.")
    data.setdefault("version", 1)
    data.setdefault("channels", {})
    data.setdefault("checks", [])
    if not isinstance(data["checks"], list):
        raise ValueError(f"{path} has an invalid checks list.")
    return data


def write_state(path: Path, state: dict, videos: list[dict[str, str]], outcome: str, *, remember_videos: bool = True) -> None:
    """Persist successful checks only, so a failed run can safely be retried."""
    checked_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    if remember_videos:
        for video in videos:
            state["channels"][video["channel"]] = {
                "video_id": video["video_id"],
                "source_url": video["source_url"],
                "title": video["title"],
                "author": video["author"],
                "seen_at": checked_at,
            }
    state["last_checked_at"] = checked_at
    state["checks"].append(
        {
            "checked_at": checked_at,
            "outcome": outcome,
            "channels": [video["channel"] for video in videos],
        }
    )
    # This is operational memory, not a historical log. Keep it small and private.
    state["checks"] = state["checks"][-30:]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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


def render_briefing(learnings_dir: Path, briefing_path: Path, briefing_date: str) -> None:
    prompt = RENDER_PROMPT.read_text(encoding="utf-8").format(
        learnings_dir=learnings_dir,
        briefing_date=briefing_date,
    )
    run_codex(prompt, briefing_path)
    html = briefing_path.read_text(encoding="utf-8")
    if re.search(r"\bcto\b", html, re.IGNORECASE):
        briefing_path.unlink(missing_ok=True)
        raise RuntimeError("Codex used a forbidden term; no HTML briefing was retained. Run the script again.")


def write_pages_index(index_path: Path, briefing_name: str, briefing_date: str) -> None:
    """Point the small Pages homepage at the briefing just published."""
    index_path.write_text(
        f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>Know Today</title>
  <style>
    :root {{ color-scheme: light; --ink: #16202a; --muted: #556372; --line: #d9e1ea; --canvas: #f6f8fb; --surface: #fff; --blue: #1d4ed8; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--canvas); color: var(--ink); font: 15px/1.55 -apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, Helvetica, Arial, sans-serif; }}
    main {{ max-width: 800px; margin: 0 auto; padding: 56px 24px; }}
    h1 {{ margin: 0; font-size: 28px; }}
    p {{ color: var(--muted); }}
    a {{ color: var(--blue); text-underline-offset: 3px; }}
    .briefing {{ display: block; margin-top: 24px; padding: 20px; background: var(--surface); border: 1px solid var(--line); border-radius: 12px; text-decoration: none; color: inherit; }}
    .briefing:hover {{ border-color: var(--blue); }}
    .date {{ margin: 0 0 5px; font-size: .82rem; font-weight: 700; }}
    h2 {{ margin: 0; font-size: 18px; }}
  </style>
</head>
<body>
  <main>
    <h1>Know Today</h1>
    <p>Concise, evidence-aware technology briefings.</p>
    <a class=\"briefing\" href=\"briefings/{briefing_name}\">
      <p class=\"date\">{briefing_date}</p>
      <h2>Read the latest briefing</h2>
    </a>
  </main>
</body>
</html>
""",
        encoding="utf-8",
    )


def publish_to_pages(briefing_path: Path, docs_dir: Path, briefing_name: str, briefing_date: str) -> None:
    """Copy the new artifact to Pages, then commit and push only Pages files."""
    public_briefing = docs_dir / "briefings" / briefing_name
    public_briefing.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(briefing_path, public_briefing)
    write_pages_index(docs_dir / "index.html", briefing_name, briefing_date)

    subprocess.run(["git", "add", "--", str(public_briefing), str(docs_dir / "index.html")], cwd=PROJECT_ROOT, check=True)
    staged = subprocess.run(
        ["git", "diff", "--cached", "--quiet", "--", str(public_briefing), str(docs_dir / "index.html")],
        cwd=PROJECT_ROOT,
    )
    if staged.returncode == 0:
        print("GitHub Pages files are already current; no commit or push was needed.")
        return
    if staged.returncode != 1:
        raise RuntimeError("Could not check staged GitHub Pages changes.")
    subprocess.run(["git", "commit", "-m", f"Publish briefing {briefing_date}"], cwd=PROJECT_ROOT, check=True)
    subprocess.run(["git", "push", "origin", "main"], cwd=PROJECT_ROOT, check=True)
    print(f"Published: {public_briefing}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subscriptions", type=Path, default=DEFAULT_SUBSCRIPTIONS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--docs-dir", type=Path, default=DEFAULT_DOCS)
    parser.add_argument("--force", action="store_true", help="Treat the latest video from every channel as new and publish a fresh briefing.")
    parser.add_argument("--no-publish", action="store_true", help="Generate a briefing but do not update GitHub Pages or Git.")
    args = parser.parse_args()

    try:
        proxies = proxy_settings()
        channels = load_channels(args.subscriptions)
        videos_dir = args.output_dir / "videos"
        learnings_dir = args.output_dir / "learnings"
        videos_dir.mkdir(parents=True, exist_ok=True)
        learnings_dir.mkdir(parents=True, exist_ok=True)
        state_path = args.output_dir / "state.json"
        state = load_state(state_path)
        latest_videos: list[dict[str, str]] = []
        new_videos: list[dict[str, str]] = []

        for channel in channels:
            video = newest_video(channel, proxies)
            latest_videos.append(video)
            print(f"@{channel}: {video['title']} ({video['source_url']})")
            previous = state["channels"].get(channel, {})
            if args.force or previous.get("video_id") != video["video_id"]:
                new_videos.append(video)

        if not new_videos:
            write_state(state_path, state, latest_videos, "no-new-sources")
            print("No new sources found. Recorded the check; no briefing was generated or published.")
            return 0

        print(f"New sources found: {len(new_videos)}. Generating and publishing a briefing.")
        run_learnings_dir = args.output_dir / "runs" / datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ") / "learnings"
        run_learnings_dir.mkdir(parents=True, exist_ok=True)

        for video in new_videos:
            video["fetched_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            video_path = videos_dir / f"{video['video_id']}.json"
            video_path.write_text(json.dumps(video, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")
            transcript_path = args.output_dir / f"{video['video_id']}.md"
            if not transcript_path.exists():
                subprocess.run([sys.executable, str(PROJECT_ROOT / "scripts" / "fetch_youtube_transcript.py"), video["source_url"], "--output-dir", str(args.output_dir)], check=True)

            learning_path = learnings_dir / f"{video['video_id']}.md"
            if args.force or not learning_path.exists():
                extract_learnings(transcript_path, learning_path)
                print(f"Learnings: {learning_path}")
            else:
                print(f"Learnings already exist: {learning_path}")
            shutil.copyfile(learning_path, run_learnings_dir / learning_path.name)

        generated_at = datetime.now(timezone.utc)
        timestamp = generated_at.strftime("%Y-%m-%dT%H-%M-%SZ")
        briefing_date = f"{generated_at:%B} {generated_at.day}, {generated_at:%Y}"
        public_briefing_name = f"{generated_at:%Y-%m-%d}.html"
        briefing_path = args.output_dir / "briefings" / f"{timestamp}.html"
        render_briefing(run_learnings_dir, briefing_path, briefing_date)
        print(f"Briefing: {briefing_path}")
        if args.no_publish:
            print("Skipping GitHub Pages publication (--no-publish).")
        else:
            publish_to_pages(briefing_path, args.docs_dir, public_briefing_name, briefing_date)
        write_state(
            state_path,
            state,
            latest_videos,
            "published" if not args.no_publish else "generated-not-published",
            remember_videos=not args.no_publish,
        )
    except (OSError, ValueError, requests.RequestException, subprocess.CalledProcessError, RuntimeError) as error:
        print(f"Could not generate the YouTube briefing: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
