#!/usr/bin/env python3
"""Independently verify briefing claims with Gemini Google Search grounding."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_MAX_SEARCHES = 25
DEFAULT_REGULAR_SEARCHES = 8
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "www.youtu.be"}
GROUNDING_REDIRECT_HOST = "vertexaisearch.cloud.google.com"


def load_dotenv(path: Path) -> None:
    """Load only missing environment variables from the project's private .env file."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


def clean_markdown(value: str) -> str:
    value = re.sub(r"\[[^\]]+\]\([^)]*\)", lambda match: match.group(0).split("]", 1)[0][1:], value)
    value = re.sub(r"[*_`#]", "", value)
    return re.sub(r"\s+", " ", value).strip()


def claim_candidates(learnings_dir: Path) -> list[dict[str, str]]:
    """Collect concrete release and capability claims from the existing learning notes."""
    candidates: list[dict[str, str]] = []
    for learning_path in sorted(learnings_dir.glob("*.md")):
        text = learning_path.read_text(encoding="utf-8")
        section = re.search(r"^## What changed or is newly possible\s*$([\s\S]*?)(?=^## |\Z)", text, re.MULTILINE)
        if not section:
            continue
        items = re.split(r"(?m)^\s*\d+\.\s+", section.group(1))
        for item in items[1:]:
            claim = clean_markdown(item)
            if len(claim) < 40:
                continue
            candidates.append({"learning_file": learning_path.name, "claim": claim[:1200]})

    # Keep stable order while avoiding nearly identical claim searches from multiple notes.
    unique: list[dict[str, str]] = []
    seen: set[str] = set()
    for candidate in candidates:
        fingerprint = re.sub(r"[^a-z0-9]+", " ", candidate["claim"].lower()).strip()[:180]
        if fingerprint not in seen:
            seen.add(fingerprint)
            unique.append(candidate)
    return unique


def is_public_evidence_url(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    return parsed.scheme in {"http", "https"} and host not in YOUTUBE_HOSTS and host != GROUNDING_REDIRECT_HOST


def resolve_url(url: str) -> str:
    """Resolve a grounding redirect to a public canonical destination when possible."""
    if "vertexaisearch.cloud.google.com/grounding-api-redirect/" not in url:
        return url
    try:
        response = requests.head(url, allow_redirects=True, timeout=15, headers={"User-Agent": "Know-Today/1.0"})
        return response.url if response.ok else url
    except requests.RequestException:
        return url


def grounding_sources(response: object) -> list[dict[str, str]]:
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return []
    metadata = getattr(candidates[0], "grounding_metadata", None)
    chunks = getattr(metadata, "grounding_chunks", None) or []
    sources: list[dict[str, str]] = []
    seen: set[str] = set()
    for chunk in chunks:
        web = getattr(chunk, "web", None)
        url = getattr(web, "uri", None) if web else None
        if not url:
            continue
        url = resolve_url(url)
        if not is_public_evidence_url(url) or url in seen:
            continue
        seen.add(url)
        sources.append({"url": url, "title": getattr(web, "title", None) or url})
        if len(sources) == 5:
            break
    return sources


def response_text(response: object) -> str:
    text = getattr(response, "text", None)
    if text:
        return str(text).strip()
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return ""
    parts = getattr(getattr(candidates[0], "content", None), "parts", None) or []
    return "\n".join(str(part.text) for part in parts if getattr(part, "text", None)).strip()


def research_claims(learnings_dir: Path, max_searches: int, model: str) -> dict:
    load_dotenv(PROJECT_ROOT / ".env")
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("Google grounding is required. Set GOOGLE_API_KEY in .env before generating a briefing.")
    try:
        from google import genai
        from google.genai import types
    except ImportError as error:
        raise RuntimeError("google-genai is required. Install requirements.txt before generating a briefing.") from error

    candidates = claim_candidates(learnings_dir)
    # Google Search grounding is currently exposed through the Gemini v1beta API.
    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(api_version="v1beta", timeout=20_000),
    )
    evidence: list[dict] = []
    search_count = 0
    for index, candidate in enumerate(candidates):
        if search_count >= max_searches:
            break
        query = (
            "Research this technology claim using Google Search. Prefer official product pages, release notes, "
            "documentation, GitHub repositories, papers, or credible independent reporting. Identify the exact "
            "company, product, model, version, availability, and evidence status. Do not cite or link YouTube.\n\n"
            f"Claim: {candidate['claim']}"
        )
        search_count += 1
        print(f"Grounding claim {search_count}/{min(len(candidates), max_searches)}...", flush=True)
        record = {"claim_id": f"claim-{index + 1:03d}", **candidate, "search_query": query}
        try:
            response = client.models.generate_content(
                model=model,
                contents=query,
                config=types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())]),
            )
            sources = grounding_sources(response)
            record.update(
                {
                    "grounded_summary": response_text(response),
                    "sources": sources,
                    "status": "web-evidenced" if sources else "no-public-evidence-found",
                }
            )
        except Exception as error:
            record.update({"grounded_summary": "", "sources": [], "status": "research-failed", "error": str(error)})
        evidence.append(record)

    if not any(item["status"] == "web-evidenced" for item in evidence):
        raise RuntimeError("No claim could be grounded with public web evidence; no public briefing will be rendered.")

    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "provider": "Gemini Google Search grounding",
        "model": model,
        "hard_search_limit": DEFAULT_MAX_SEARCHES,
        "max_searches": max_searches,
        "searches_used": search_count,
        "candidate_claims_found": len(candidates),
        "claims": evidence,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--learnings-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-searches", type=int, default=DEFAULT_REGULAR_SEARCHES)
    parser.add_argument("--model", default=os.environ.get("KNOW_TODAY_GROUNDING_MODEL", DEFAULT_MODEL))
    args = parser.parse_args()
    if not args.learnings_dir.is_dir():
        raise ValueError(f"Learning directory does not exist: {args.learnings_dir}")
    if not 1 <= args.max_searches <= DEFAULT_MAX_SEARCHES:
        raise ValueError(f"--max-searches must be between 1 and {DEFAULT_MAX_SEARCHES}.")
    result = research_claims(args.learnings_dir, args.max_searches, args.model)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Grounded {result['searches_used']} claim searches; evidence manifest: {args.output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"Could not complete grounded briefing research: {error}", file=sys.stderr)
        raise SystemExit(1)
