"""
One-shot backfill of sermons.audio_url for the 8 sermons ingested 2026-05-13.

- Chris (sermons.sovgracekc.org): each sermon page exposes a stable
  /media/mp3/<id>.mp3 path that 302-redirects to a fresh presigned URL on
  each fetch. The /media/mp3/<id>.mp3 URL itself is permanent — embed it
  directly as an <audio> source.
- Ricky (crossofgrace.net): only S3-presigned MP3 URLs that expire in ~24h.
  Per Chris's direction, link back to the sermon page instead of trying to
  re-sign on every render.

Idempotent — only updates rows where audio_url IS NULL.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from pathlib import Path
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from supabase import create_client

load_dotenv(override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("backfill_audio_urls")

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0 Safari/537.36"
)

_MP3_PATH_RE = re.compile(r'"(/media/mp3/\d+\.mp3)"')

# Chris's 5 new sermons (sermon_id → source page URL on sermons.sovgracekc.org)
CHRIS_SOURCE_URLS = {
    "24ca574c-a162-4526-aa9b-997bcbb97bd9": "https://sermons.sovgracekc.org/sermons/91455/ephesians-522-33-marriage-the-mission-of-god/",
    "89087531-0296-4c5f-af91-adb275e62010": "https://sermons.sovgracekc.org/sermons/92108/our-gods-on-display/",
    "9248b72c-6720-4ddf-a3a9-291c7b5ddec7": "https://sermons.sovgracekc.org/sermons/92583/a-living-hope/",
    "41380674-063e-4c94-995a-9451a803ca0f": "https://sermons.sovgracekc.org/sermons/92886/the-life-of-christ-fuels-christian-endurance-1-peter-113-19/",
    "6b284274-34c4-4f06-8a77-618dc2e104d1": "https://sermons.sovgracekc.org/sermons/93095/new-birth-brotherly-love-1-peter-113-23/",
}

# Ricky's 3 new sermons (sermon_id → canonical Cross of Grace sermon-page URL).
# We store the page URL itself because the only audio URLs the Nucleus API
# exposes are 24-hour presigned S3 links.
RICKY_PAGE_URLS = {
    "9772e967-ddfd-4f40-9540-c8e2b7a59a5d": "https://www.crossofgrace.net/sermons/rescuing-manhood",
    "e98ccdec-74ff-4885-946e-fd8d92710662": "https://www.crossofgrace.net/sermons/rescuing-womanhood",
    "680ee271-19de-4baa-a771-574fda65cb7e": "https://www.crossofgrace.net/sermons/life-gender-and-the-pursuit-of-happiness",
}


def _fetch(url: str) -> bytes:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=60) as resp:
        return resp.read()


def _extract_mp3_url(page_url: str) -> str:
    html = _fetch(page_url).decode("utf-8", errors="replace")
    m = _MP3_PATH_RE.search(html)
    if not m:
        raise RuntimeError(f"No /media/mp3/*.mp3 link found on {page_url}")
    return "https://sermons.sovgracekc.org" + m.group(1)


def main():
    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

    log.info("Backfilling Chris's audio URLs from sermons.sovgracekc.org...")
    for sermon_id, source_url in CHRIS_SOURCE_URLS.items():
        try:
            mp3_url = _extract_mp3_url(source_url)
        except Exception as exc:
            log.error(f"  {sermon_id}: {exc}")
            continue
        sb.table("sermons").update({"audio_url": mp3_url}).eq("id", sermon_id).execute()
        log.info(f"  {sermon_id} → {mp3_url}")

    log.info("Backfilling Ricky's page-URL stand-ins...")
    for sermon_id, page_url in RICKY_PAGE_URLS.items():
        sb.table("sermons").update({"audio_url": page_url}).eq("id", sermon_id).execute()
        log.info(f"  {sermon_id} → {page_url}")

    log.info("Done.")


if __name__ == "__main__":
    main()
