#!/usr/bin/env python3
"""Build an OpenPeon (CESP v1.0) sound pack from YouTube clips listed in pack.yaml."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import yaml

ROOT = Path(__file__).resolve().parent
CACHE_AUDIO = ROOT / ".cache" / "audio"
SOUNDS_DIR = ROOT / "sounds"
PACK_YAML = ROOT / "pack.yaml"
MANIFEST = ROOT / "openpeon.json"

CESP_VERSION = "1.0"
PER_FILE_MAX = 1 * 1024 * 1024
TOTAL_MAX = 50 * 1024 * 1024

CORE_CATEGORIES = {
    "session.start",
    "task.acknowledge",
    "task.complete",
    "task.error",
    "input.required",
    "resource.limit",
}
EXTENDED_CATEGORIES = {"user.spam", "session.end", "task.progress"}
ALLOWED_CATEGORIES = CORE_CATEGORIES | EXTENDED_CATEGORIES

FILENAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def die(msg: str) -> "None":
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def check_tools() -> None:
    for tool in ("yt-dlp", "ffmpeg"):
        if shutil.which(tool) is None:
            die(f"{tool} not found on PATH. Install with: brew install {tool}")


def video_id(url: str) -> str:
    parsed = urlparse(url)
    if parsed.hostname in ("youtu.be",):
        return parsed.path.lstrip("/")
    qs = parse_qs(parsed.query)
    if "v" in qs:
        return qs["v"][0]
    die(f"cannot extract video id from URL: {url}")


def download_audio(url: str, cookies_from_browser: str | None) -> Path:
    vid = video_id(url)
    out = CACHE_AUDIO / f"{vid}.mp3"
    if out.exists():
        print(f"  cached: {out.relative_to(ROOT)}")
        return out
    CACHE_AUDIO.mkdir(parents=True, exist_ok=True)
    print(f"  downloading {url} -> {out.relative_to(ROOT)}")
    cmd = [
        "yt-dlp",
        "-x",
        "--audio-format", "mp3",
        "--audio-quality", "0",
        "-o", str(CACHE_AUDIO / "%(id)s.%(ext)s"),
    ]
    if cookies_from_browser:
        cmd += ["--cookies-from-browser", cookies_from_browser]
    cmd.append(url)
    subprocess.run(cmd, check=True)
    if not out.exists():
        die(f"yt-dlp completed but {out} is missing")
    return out


def cut_clip(source: Path, start: str, end: str, dest: Path) -> None:
    if dest.exists():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-loglevel", "error",
            "-y",
            "-ss", str(start),
            "-to", str(end),
            "-i", str(source),
            "-c:a", "libmp3lame",
            "-b:a", "128k",
            str(dest),
        ],
        check=True,
    )


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def validate_clip(clip: dict, idx: int, url: str) -> None:
    for key in ("start", "end", "category", "file", "label"):
        if key not in clip:
            die(f"clip #{idx} for {url} missing '{key}': {clip!r}")
    if clip["category"] not in ALLOWED_CATEGORIES:
        die(
            f"clip #{idx} for {url} has unknown category {clip['category']!r}. "
            f"Allowed: {sorted(ALLOWED_CATEGORIES)}"
        )
    if not FILENAME_RE.match(clip["file"]):
        die(
            f"clip #{idx} for {url} has invalid filename {clip['file']!r}. "
            "Use letters, numbers, dots, hyphens, underscores only."
        )


def build(download_only: bool) -> None:
    check_tools()
    if not PACK_YAML.exists():
        die(f"{PACK_YAML} not found")
    config = yaml.safe_load(PACK_YAML.read_text())

    pack = config.get("pack") or {}
    videos = config.get("videos") or []
    cookies_from_browser = config.get("cookies_from_browser")

    # Download phase: one fetch per unique URL.
    print("downloading audio...")
    sources: dict[str, Path] = {}
    for video in videos:
        url = video["url"]
        if url not in sources:
            sources[url] = download_audio(url, cookies_from_browser)

    if download_only:
        print("download-only: skipping clip cutting and manifest write.")
        return

    # Cut phase.
    print("cutting clips...")
    SOUNDS_DIR.mkdir(exist_ok=True)
    by_category: dict[str, list[dict]] = defaultdict(list)
    seen_files: set[str] = set()

    for video in videos:
        url = video["url"]
        source = sources[url]
        for idx, clip in enumerate(video.get("clips") or []):
            validate_clip(clip, idx, url)
            if clip["file"] in seen_files:
                die(f"duplicate filename: {clip['file']}")
            seen_files.add(clip["file"])

            dest = SOUNDS_DIR / clip["file"]
            cut_clip(source, clip["start"], clip["end"], dest)

            size = dest.stat().st_size
            if size > PER_FILE_MAX:
                die(
                    f"{dest.relative_to(ROOT)} is {size} bytes (> 1 MB). "
                    "Shorten the clip or lower bitrate."
                )

            by_category[clip["category"]].append(
                {
                    "file": f"sounds/{clip['file']}",
                    "label": clip["label"],
                    "sha256": sha256(dest),
                }
            )
            print(f"  {clip['category']:18s} {dest.relative_to(ROOT)}  ({size // 1024} KB)")

    total = sum(p.stat().st_size for p in SOUNDS_DIR.glob("*") if p.is_file())
    if total > TOTAL_MAX:
        die(f"sounds/ is {total} bytes (> 50 MB total)")

    # Manifest.
    manifest = {
        "cesp_version": CESP_VERSION,
        "name": pack.get("name"),
        "display_name": pack.get("display_name"),
        "version": pack.get("version"),
        "description": pack.get("description"),
        "author": pack.get("author"),
        "license": pack.get("license"),
        "language": pack.get("language"),
        "categories": {
            cat: {"sounds": sorted(by_category[cat], key=lambda s: s["file"])}
            for cat in sorted(by_category)
        },
    }
    manifest = {k: v for k, v in manifest.items() if v is not None}

    MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    print(f"\nwrote {MANIFEST.relative_to(ROOT)}")
    print(f"total: {len(seen_files)} clips, {total // 1024} KB")
    missing_core = CORE_CATEGORIES - set(by_category)
    if missing_core:
        print(f"note: core categories with no clips: {sorted(missing_core)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--download-only",
        action="store_true",
        help="Download audio for every URL in pack.yaml, then stop.",
    )
    args = parser.parse_args()
    build(download_only=args.download_only)


if __name__ == "__main__":
    main()
