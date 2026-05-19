"""
Render the Sermon Scraps page for a given sermon.

Reads the sermon_artifacts row of type='sermon_scraps' from Supabase,
renders templates/sermon_scraps.html.j2, writes to:

  output/sermon-pages/<url_slug>/sermons/<sermon-slug>/scraps.html

Served on Cloudflare at: /<url_slug>/sermons/<sermon-slug>/scraps

Usage:
    python3 scripts/generate_sermon_scraps_page.py <sermon_id>
"""

from __future__ import annotations

import logging
import os
import sys
import urllib.request
import urllib.error
from datetime import date as _date, datetime
from pathlib import Path
from urllib.parse import urlparse

log = logging.getLogger("sermon_scraps")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv

load_dotenv(REPO_ROOT / ".env", override=True)

from jinja2 import Environment, FileSystemLoader, select_autoescape  # noqa: E402
from supabase import create_client  # noqa: E402

TEMPLATES_DIR = REPO_ROOT / "templates"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "sermon-pages"

# Trusted hosts we'll validate URLs against. URLs to other hosts are
# always dropped — protects against fabricated URLs slipping through.
TRUSTED_HOSTS = {
    "www.ccel.org", "ccel.org",
    "www.monergism.com", "monergism.com",
    "www.gutenberg.org", "gutenberg.org",
    "archive.org",
    "plato.stanford.edu",
}


def _validate_link(url: str, timeout: float = 6.0) -> bool:
    """HEAD-check a URL. Returns True only if host is trusted AND it 200s.

    Tries GET (Range-limited) as a fallback when HEAD is unsupported."""
    try:
        host = urlparse(url).hostname
    except Exception:
        return False
    if not host or host not in TRUSTED_HOSTS:
        return False
    try:
        req = urllib.request.Request(
            url, method="HEAD",
            headers={"User-Agent": "Mozilla/5.0 (sermon-steward link-validator)"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 400
    except urllib.error.HTTPError as exc:
        # Some servers reject HEAD; try a small GET.
        if exc.code in (405, 501):
            try:
                req = urllib.request.Request(
                    url, method="GET",
                    headers={
                        "User-Agent": "Mozilla/5.0 (sermon-steward link-validator)",
                        "Range": "bytes=0-512",
                    },
                )
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return 200 <= resp.status < 400
            except Exception:
                return False
        return False
    except Exception:
        return False


def _clean_bibliography(scraps: dict, sb) -> bool:
    """Walk bibliography links, validate each, blank any that fail.

    Writes the cleaned bibliography back to the sermon_artifacts row so
    subsequent renders skip the re-check. Returns True if any link
    was changed (for logging)."""
    biblio = scraps.get("bibliography") or []
    if not biblio:
        return False
    changed = False
    kept_links = 0
    dropped_links = 0
    for entry in biblio:
        link = entry.get("link")
        if not link:
            continue
        if _validate_link(link):
            kept_links += 1
            continue
        # Drop the link; rely on publisher_note (or leave plain text).
        log.warning(f"  dropped fabricated/dead URL: {link} for {entry.get('title')!r}")
        entry["link"] = None
        # Ensure a publisher_note exists so the entry still renders something.
        if not entry.get("publisher_note"):
            entry["publisher_note"] = "Available in print"
        changed = True
        dropped_links += 1
    log.info(f"  bibliography: kept {kept_links} links, dropped {dropped_links}")
    return changed

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _long_date(date_str: str | None) -> str | None:
    if not date_str:
        return None
    try:
        d = _date.fromisoformat(date_str)
    except ValueError:
        return None
    return f"{_MONTHS[d.month - 1]} {d.day}, {d.year}"


def main() -> int:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <sermon_id>", file=sys.stderr)
        return 2
    sermon_id = sys.argv[1]

    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

    # Pull sermon + preacher + church
    sermon = (
        sb.table("sermons")
        .select(
            "id, title, slug, date, primary_text, "
            "preachers(name, churches(name, slug, url_slug, domain))"
        )
        .eq("id", sermon_id)
        .single()
        .execute()
        .data
    )
    if not sermon:
        print(f"sermon not found: {sermon_id}", file=sys.stderr)
        return 1

    preacher = sermon.get("preachers") or {}
    church = preacher.get("churches") or {}
    url_slug = church.get("url_slug") or church.get("slug") or "unknown-church"
    sermon_slug = sermon.get("slug")
    if not sermon_slug:
        print(f"sermon has no slug: {sermon_id}", file=sys.stderr)
        return 1

    # Pull the scraps artifact body
    rows = (
        sb.table("sermon_artifacts")
        .select("body, status, generation_model, updated_at")
        .eq("sermon_id", sermon_id)
        .eq("artifact_type", "sermon_scraps")
        .limit(1)
        .execute()
        .data
    )
    if not rows:
        print(f"no sermon_scraps artifact for sermon {sermon_id}", file=sys.stderr)
        return 1
    scraps = rows[0].get("body") or {}

    # Validate bibliography URLs (drop fabricated/dead ones) and persist
    # the cleaned state back to Supabase so subsequent renders skip the
    # network round-trips.
    changed = _clean_bibliography(scraps, sb)
    if changed:
        sb.table("sermon_artifacts").update({"body": scraps}).eq(
            "sermon_id", sermon_id
        ).eq("artifact_type", "sermon_scraps").execute()
        log.info("  persisted cleaned bibliography back to sermon_artifacts")

    domain = church.get("domain") or "sermonsteward.com"
    sermon_url = f"/{url_slug}/sermons/{sermon_slug}"
    canonical_url = f"https://{domain}{sermon_url}/scraps"

    # Build render context
    context = {
        "sermon": {
            "title": sermon.get("title"),
            "primary_text": sermon.get("primary_text"),
            "date_iso": sermon.get("date"),
            "date_long": _long_date(sermon.get("date")),
            "slug": sermon_slug,
        },
        "preacher": {
            "name": preacher.get("name"),
        },
        "church": {
            "name": church.get("name"),
            "url_slug": url_slug,
            "domain": domain,
        },
        "scraps": scraps,
        "sermon_url": sermon_url,
        "canonical_url": canonical_url,
    }

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("sermon_scraps.html.j2")
    html = template.render(**context)

    out_dir = DEFAULT_OUTPUT_DIR / url_slug / "sermons" / sermon_slug
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "scraps.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
