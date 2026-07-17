#!/usr/bin/env python3
"""Fetch a YouTube transcript and save it as Markdown and JSON."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.proxies import GenericProxyConfig, WebshareProxyConfig


def video_id_from(value: str) -> str:
    """Accept a YouTube video ID, watch URL, youtu.be URL, or Shorts URL."""
    value = value.strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", value):
        return value

    parsed = urlparse(value)
    host = parsed.netloc.lower().removeprefix("www.").removeprefix("m.")
    if host == "youtu.be":
        candidate = parsed.path.strip("/").split("/")[0]
    elif host in {"youtube.com", "youtube-nocookie.com"}:
        if parsed.path == "/watch":
            candidate = parse_qs(parsed.query).get("v", [""])[0]
        else:
            parts = parsed.path.strip("/").split("/")
            candidate = parts[1] if len(parts) >= 2 and parts[0] in {"shorts", "embed", "live"} else ""
    else:
        candidate = ""

    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate):
        raise ValueError("Provide a YouTube video URL or its 11-character video ID.")
    return candidate


def timestamp(seconds: float) -> str:
    total_seconds = int(seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}" if hours else f"{minutes:02}:{seconds:02}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", help="YouTube video URL or 11-character video ID")
    parser.add_argument(
        "--languages",
        nargs="+",
        default=["en"],
        help="Caption language preference, in priority order (default: en)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output/youtube"),
        help="Directory for generated files (default: output/youtube)",
    )
    parser.add_argument(
        "--webshare-proxy-username",
        default=os.environ.get("KNOW_TODAY_WEBSHARE_PROXY_USERNAME"),
        help="Webshare residential-proxy username (or set KNOW_TODAY_WEBSHARE_PROXY_USERNAME)",
    )
    parser.add_argument(
        "--webshare-proxy-password",
        default=os.environ.get("KNOW_TODAY_WEBSHARE_PROXY_PASSWORD"),
        help="Webshare residential-proxy password (or set KNOW_TODAY_WEBSHARE_PROXY_PASSWORD)",
    )
    parser.add_argument(
        "--http-proxy",
        default=os.environ.get("KNOW_TODAY_HTTP_PROXY"),
        help="HTTP proxy URL (or set KNOW_TODAY_HTTP_PROXY)",
    )
    parser.add_argument(
        "--https-proxy",
        default=os.environ.get("KNOW_TODAY_HTTPS_PROXY"),
        help="HTTPS proxy URL (or set KNOW_TODAY_HTTPS_PROXY)",
    )
    args = parser.parse_args()

    supplied_proxy_values = [args.webshare_proxy_username, args.webshare_proxy_password]
    if any(supplied_proxy_values) and not all(supplied_proxy_values):
        parser.error("Supply both Webshare proxy credentials or neither.")
    generic_proxy_values = [args.http_proxy, args.https_proxy]
    if any(generic_proxy_values) and not all(generic_proxy_values):
        parser.error("Supply both HTTP and HTTPS proxy URLs or neither.")
    if all(supplied_proxy_values) and all(generic_proxy_values):
        parser.error("Choose either Webshare residential credentials or generic proxy URLs, not both.")

    try:
        video_id = video_id_from(args.video)
        proxy_config = None
        if all(supplied_proxy_values):
            proxy_config = WebshareProxyConfig(
                proxy_username=args.webshare_proxy_username,
                proxy_password=args.webshare_proxy_password,
            )
        elif all(generic_proxy_values):
            proxy_config = GenericProxyConfig(
                http_url=args.http_proxy,
                https_url=args.https_proxy,
            )
        transcript = YouTubeTranscriptApi(proxy_config=proxy_config).fetch(
            video_id, languages=args.languages
        )
    except Exception as error:
        print(f"Could not fetch the transcript: {error}", file=sys.stderr)
        print(
            "The video may have no captions, restrict transcripts, or block this network. "
            "No YouTube API key is needed by this library's normal fetch path.",
            file=sys.stderr,
        )
        return 1

    fetched_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    data = {
        "video_id": transcript.video_id,
        "source_url": f"https://www.youtube.com/watch?v={transcript.video_id}",
        "fetched_at": fetched_at,
        "language": transcript.language,
        "language_code": transcript.language_code,
        "is_generated": transcript.is_generated,
        "snippets": transcript.to_raw_data(),
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / f"{video_id}.json"
    markdown_path = args.output_dir / f"{video_id}.md"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        f"# YouTube transcript: {video_id}",
        "",
        f"Source: {data['source_url']}",
        f"Fetched: {fetched_at}",
        f"Language: {transcript.language} ({transcript.language_code})",
        f"Caption type: {'auto-generated' if transcript.is_generated else 'manually created'}",
        "",
        "## Transcript",
        "",
    ]
    lines.extend(f"- [{timestamp(item['start'])}] {item['text']}" for item in data["snippets"])
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"Saved {len(transcript)} snippets.")
    print(f"Markdown: {markdown_path}")
    print(f"JSON: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
