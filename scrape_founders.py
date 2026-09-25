#!/usr/bin/env python3
"""
Shepherd's Guild — Founders Ministries Church Directory Scraper
===============================================================
Scrapes church.founders.org (WP Job Manager "employer" post type, exposed
at /church/<slug>/). Church URLs come from the site's own sitemaps, so no
pagination crawling is needed.

Fields captured per church:
  name, pastor_name, email, phone, website, state, city, affiliation,
  confessions, statements_of_faith, year_began, description, detail_url

Email addresses on this site are obfuscated client-side by the "Email Encoder
Bundle" WP plugin. The decode key ships inline with each page; decode_eeb()
reproduces it. See NOTES in the repo before running at scale.

Usage:
  python3 scrape_founders.py --limit 5            # smoke test
  python3 scrape_founders.py                      # full run (~1,450 pages)
  python3 scrape_founders.py --resume             # skip already-scraped
"""

import argparse, csv, json, logging, random, re, time, urllib.parse
from pathlib import Path

import requests
from bs4 import BeautifulSoup

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
SITEMAPS = ["https://church.founders.org/employer-sitemap.xml",
            "https://church.founders.org/employer-sitemap2.xml"]
DELAY_MIN, DELAY_MAX = 2.0, 4.0     # founders.org runs Wordfence; be polite
MAX_RETRIES = 3
PROGRESS = "founders_progress.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("founders")

session = requests.Session()
session.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})


def decode_eeb(html: str):
    """Decode Email Encoder Bundle obfuscated addresses embedded in the page."""
    out = []
    for ml, mi in re.findall(r'var ml="([^"]*)",\s*mi="([^"]*)"', html):
        try:
            o = "".join(ml[ord(c) - 48] for c in mi)
            addr = urllib.parse.unquote(o)
            if "@" in addr:
                out.append(addr)
        except (IndexError, ValueError):
            continue
    return out


def get(url):
    for attempt in range(MAX_RETRIES):
        try:
            r = session.get(url, timeout=30)
            if r.status_code == 200:
                return r.text
            if r.status_code in (429, 503):
                wait = 30 * (attempt + 1)
                log.warning("%s on %s — backing off %ss", r.status_code, url, wait)
                time.sleep(wait)
                continue
            log.warning("HTTP %s on %s", r.status_code, url)
            return None
        except requests.RequestException as e:
            log.warning("%s on %s (attempt %d)", e, url, attempt + 1)
            time.sleep(5 * (attempt + 1))
    return None


def church_urls():
    urls = []
    for sm in SITEMAPS:
        xml = get(sm)
        if xml:
            urls += [u for u in re.findall(r"<loc>([^<]+)</loc>", xml) if "/church/" in u]
        time.sleep(1)
    return sorted(set(urls))


def _meta_pairs(soup):
    """job-meta blocks: <h3 class=title>Label:</h3><div class=value>Value</div>"""
    out = {}
    for block in soup.select("div.job-meta"):
        t = block.select_one("h3.title")
        v = block.select_one("div.value")
        if t and v:
            out[t.get_text(strip=True).rstrip(":").strip()] = v.get_text(" ", strip=True)
    return out


def _content_sections(soup):
    """About Church + the h5-headed confessional fields in the main content column."""
    out = {}
    area = soup.select_one("div.list-content-candidate")
    if not area:
        return out
    for h in area.select("h3, h5"):
        label = h.get_text(strip=True).rstrip(":").strip()
        parts = []
        for sib in h.find_next_siblings():
            if sib.name in ("h3", "h5"):
                break
            txt = sib.get_text(" ", strip=True)
            if txt:
                parts.append(txt)
        out[label] = " ".join(parts).strip()
    return out


def parse(html_text, url):
    soup = BeautifulSoup(html_text, "html.parser")
    rec = {"detail_url": url, "slug": url.rstrip("/").split("/")[-1]}

    h1 = soup.find("h1")
    rec["name"] = h1.get_text(" ", strip=True) if h1 else ""

    meta = _meta_pairs(soup)
    sect = _content_sections(soup)

    rec["pastor_name"] = meta.get("Pastor Name", "")
    rec["year_began"] = meta.get("Year Church Began", "")

    tel = soup.select_one('a[href^="tel:"]')
    rec["phone"] = tel.get_text(strip=True) if tel else meta.get("Church Phone Number", "")

    emails = decode_eeb(html_text)
    rec["email"] = emails[0] if emails else ""

    loc = soup.select_one('a[href*="/church-location/"]')
    rec["state"] = loc.get_text(strip=True) if loc else meta.get("State / Country", "")
    rec["city"] = meta.get("City", "")

    site = soup.select_one("div.employer-website a[href]")
    rec["website"] = site["href"].strip() if site else ""

    rec["description"] = sect.get("About Church", "")[:1000]
    rec["affiliation"] = sect.get("Church Affiliation", "")
    rec["confessions"] = sect.get("Confessions We Affirm", "")
    rec["statements_of_faith"] = sect.get("Statements of Faith We Affirm", "")
    return rec


FIELDS = ["name", "pastor_name", "email", "phone", "website", "city", "state",
          "affiliation", "confessions", "statements_of_faith", "year_began",
          "description", "slug", "detail_url"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="only scrape N churches (smoke test)")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--out", default="founders_churches.csv")
    args = ap.parse_args()

    urls = church_urls()
    log.info("sitemap: %d church URLs", len(urls))

    done = {}
    if args.resume and Path(PROGRESS).exists():
        done = json.loads(Path(PROGRESS).read_text())
        log.info("resuming — %d already scraped", len(done))

    todo = [u for u in urls if u not in done]
    if args.limit:
        todo = todo[: args.limit]

    for i, u in enumerate(todo, 1):
        html = get(u)
        if html:
            try:
                done[u] = parse(html, u)
                log.info("[%d/%d] %s — pastor=%r email=%r", i, len(todo),
                         done[u]["name"][:40], done[u]["pastor_name"], done[u]["email"])
            except Exception as e:
                log.error("parse failed %s: %s", u, e)
        if i % 25 == 0:
            Path(PROGRESS).write_text(json.dumps(done))
        time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))

    Path(PROGRESS).write_text(json.dumps(done))
    with open(args.out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        for rec in done.values():
            w.writerow(rec)
    log.info("wrote %s (%d rows)", args.out, len(done))


if __name__ == "__main__":
    main()
