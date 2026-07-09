#!/usr/bin/env python3
"""
build_podcast_feeds.py — generate an Apple/Spotify-compatible podcast RSS feed
per church, so a church's sermons show up in Apple Podcasts, Spotify, etc.

Writes `<SS_REPO>/<ChurchDir>/podcast.xml`. Eleventy passthrough-copies it and
`wrangler deploy` publishes it at e.g.
    https://sermonsteward.com/ProvidenceLenexa/podcast.xml

We have audio URLs + abstracts already. The one thing podcast <enclosure> tags
want that we don't store is the file size in bytes — so on the first run we HEAD
each audio file to get it and cache it back to sermons.audio_size_bytes (fast
thereafter). Duration (itunes:duration) is optional and omitted for now.

Usage:
    python3 scripts/build_podcast_feeds.py                 # all configured churches
    python3 scripts/build_podcast_feeds.py --church cross-of-grace-church
    python3 scripts/build_podcast_feeds.py --no-fetch-sizes   # skip HEADs (length=0)

Env: SUPABASE_URL / SUPABASE_KEY.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from xml.sax.saxutils import escape

import requests
from dotenv import load_dotenv
from supabase import create_client

REPO = Path(__file__).resolve().parent.parent
load_dotenv(REPO / ".env")
SS_REPO = Path("/Users/dad/shepherds-guild/sermon-steward")
SITE = "https://sermonsteward.com"

# Per-church podcast config. `dir` matches the deploy CHURCH_DIR mapping.
# image / owner_email are placeholders until real values are supplied (Apple
# requires cover art + an owner email to accept a submission).
PODCASTS = {
    "providence-community-church": {
        "dir": "ProvidenceLenexa",
        "title": "Providence Community Church — Sermons",
        "author": "Providence Community Church",
        "description": "Weekly sermons from Providence Community Church in Lenexa, Kansas.",
        "owner_name": "Providence Community Church",
        "owner_email": "chris@sermonsteward.com",
        "image": f"{SITE}/podcast-cover-default.png",
    },
    "cross-of-grace-church": {
        "dir": "CoGElPaso",
        "title": "Cross of Grace Church — Sermons",
        "author": "Cross of Grace Church",
        "description": "Weekly sermons from Cross of Grace Church in El Paso, Texas.",
        "owner_name": "Cross of Grace Church",
        "owner_email": "chris@sermonsteward.com",
        "image": f"{SITE}/podcast-cover-default.png",
    },
}


def supabase():
    url = os.environ["SUPABASE_URL"]
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ["SUPABASE_KEY"]
    return create_client(url, key)


def rfc822(date_str: str) -> str:
    # We only have a date; anchor each episode at noon UTC for a stable pubDate.
    dt = datetime.fromisoformat(date_str).replace(hour=12, tzinfo=timezone.utc)
    return format_datetime(dt)


def head_size(url: str) -> int:
    try:
        r = requests.head(url, timeout=15, allow_redirects=True)
        n = int(r.headers.get("content-length", 0))
        return n if n > 0 else 0
    except Exception:
        return 0


def build_feed(sb, church_slug: str, cfg: dict, fetch_sizes: bool, out_root: Path) -> Path:
    # Resolve church_id from slug, then its preachers.
    church = sb.table("churches").select("id,name").eq("slug", church_slug).single().execute().data
    preacher_rows = sb.table("preachers").select("id,name").eq("church_id", church["id"]).execute().data or []
    pid_name = {p["id"]: p["name"] for p in preacher_rows}
    pids = list(pid_name.keys())

    rows = (sb.table("sermons")
            .select("id,title,slug,date,abstract,hosted_audio_url,audio_size_bytes,preacher_id,primary_text")
            .in_("preacher_id", pids)
            .not_.is_("hosted_audio_url", "null")
            .not_.is_("date", "null")
            .not_.is_("slug", "null")
            .order("date", desc=True)
            .execute().data or [])

    ch_link = f"{SITE}/{cfg['dir']}/sermons/"
    items = []
    for s in rows:
        size = s.get("audio_size_bytes")
        if not size and fetch_sizes:
            size = head_size(s["hosted_audio_url"])
            if size:
                sb.table("sermons").update({"audio_size_bytes": size}).eq("id", s["id"]).execute()
        size = size or 0
        preacher = pid_name.get(s["preacher_id"], cfg["author"])
        desc = (s.get("abstract") or "").strip() or s.get("title") or ""
        page = f"{SITE}/{cfg['dir']}/sermons/{s['slug']}"
        subtitle = s.get("primary_text") or ""
        items.append(f"""    <item>
      <title>{escape(s.get('title') or 'Sermon')}</title>
      <itunes:author>{escape(preacher)}</itunes:author>
      <itunes:subtitle>{escape(subtitle)}</itunes:subtitle>
      <description>{escape(desc)}</description>
      <itunes:summary>{escape(desc)}</itunes:summary>
      <pubDate>{rfc822(s['date'])}</pubDate>
      <enclosure url="{escape(s['hosted_audio_url'])}" length="{size}" type="audio/mpeg"/>
      <guid isPermaLink="false">{s['id']}</guid>
      <link>{escape(page)}</link>
      <itunes:explicit>false</itunes:explicit>
    </item>""")

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" xmlns:content="http://purl.org/rss/1.0/modules/content/">
  <channel>
    <title>{escape(cfg['title'])}</title>
    <link>{escape(ch_link)}</link>
    <language>en-us</language>
    <copyright>&#169; {datetime.now(timezone.utc).year} {escape(cfg['author'])}</copyright>
    <description>{escape(cfg['description'])}</description>
    <itunes:summary>{escape(cfg['description'])}</itunes:summary>
    <itunes:author>{escape(cfg['author'])}</itunes:author>
    <itunes:type>episodic</itunes:type>
    <itunes:owner>
      <itunes:name>{escape(cfg['owner_name'])}</itunes:name>
      <itunes:email>{escape(cfg['owner_email'])}</itunes:email>
    </itunes:owner>
    <itunes:image href="{escape(cfg['image'])}"/>
    <itunes:category text="Religion &amp; Spirituality">
      <itunes:category text="Christianity"/>
    </itunes:category>
    <itunes:explicit>false</itunes:explicit>
    <atom:link xmlns:atom="http://www.w3.org/2005/Atom" href="{SITE}/{cfg['dir']}/podcast.xml" rel="self" type="application/rss+xml"/>
{chr(10).join(items)}
  </channel>
</rss>
"""
    out = out_root / cfg["dir"] / "podcast.xml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(xml, encoding="utf-8")
    print(f"wrote {out}  ({len(items)} episodes)")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--church", help="church slug (default: all configured)")
    ap.add_argument("--no-fetch-sizes", action="store_true", help="skip HEAD requests for file sizes")
    ap.add_argument("--out-dir", help="override output root (default: the sermon-steward repo)")
    args = ap.parse_args()
    sb = supabase()
    out_root = Path(args.out_dir) if args.out_dir else SS_REPO
    slugs = [args.church] if args.church else list(PODCASTS.keys())
    for slug in slugs:
        cfg = PODCASTS.get(slug)
        if not cfg:
            print(f"no podcast config for {slug}; skipping"); continue
        build_feed(sb, slug, cfg, fetch_sizes=not args.no_fetch_sizes, out_root=out_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
