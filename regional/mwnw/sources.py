"""Find each church's sermon for a given Sunday. Network calls retry; nothing here spends money."""
from __future__ import annotations
import html as htmlmod, json, re, subprocess, xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin
from .util import CT, log, http_get, retry
from . import config

ITUNES = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]


def date_tokens(d: date) -> list[str]:
    m, dd, yy = d.month, d.day, d.strftime("%y")
    mon = MONTHS[m - 1]
    return [f"{m}-{dd}-{yy}", f"{m:02d}-{dd:02d}-{yy}", f"{m}/{dd}/{yy}", f"{m}.{dd}.{yy}", f"{m}-{dd}-{d.year}",
            f"{m}/{dd}/{d.year}", d.isoformat(), f"{d.year}{m:02d}{dd:02d}", f"{mon} {dd}", f"{mon[:3]} {dd}",
            f"{mon} {dd}th", f"{mon} {dd}st", f"{mon} {dd}nd", f"{mon} {dd}rd"]


def has_date(text: str, d: date) -> bool:
    t = (text or "").lower()
    for tok in date_tokens(d):
        for m in re.finditer(re.escape(tok), t):
            # don't let "10-4-26" match inside "10-4-260" / "Oct 4" inside "Oct 40"
            after = t[m.end():m.end() + 1]
            before = t[m.start() - 1:m.start()] if m.start() else ""
            if not after.isdigit() and not before.isdigit():
                return True
    return False


def sunday_window(week: str, before_h=12, after_days=4):
    d = date.fromisoformat(week)
    start = datetime(d.year, d.month, d.day, tzinfo=CT) - timedelta(hours=before_h)
    return d, start, start + timedelta(hours=before_h) + timedelta(days=after_days)


# ── podcast ──────────────────────────────────────────────────────────────────
def podcast(church: dict, week: str) -> dict | None:
    d, lo, hi = sunday_window(week)
    xml = http_get(church["podcast"], timeout=45).content
    root = ET.fromstring(xml)
    best = None
    for it in root.iter("item"):
        enc = it.find("enclosure")
        if enc is None or not enc.get("url"): continue
        title = (it.findtext("title") or "").strip()
        url = enc.get("url")
        try: pub = parsedate_to_datetime(it.findtext("pubDate")).astimezone(CT)
        except Exception: pub = None
        by_name = has_date(title, d) or has_date(url, d)
        by_pub = pub is not None and lo <= pub <= hi
        # date-only pubDates (Providence, some PCO feeds) land at 00:00 UTC = Sat 7pm CT
        if pub is not None and pub.date() in (d, d - timedelta(days=1)) and pub.hour in (18, 19): by_pub = True
        if not (by_name or by_pub): continue
        # an explicit different date in the title means it's another Sunday's file
        other = re.search(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})\b", title + " " + url.rsplit("/", 1)[-1])
        if other and not by_name: continue
        score = (2 if by_name else 0) + (1 if by_pub else 0)
        cand = dict(kind="podcast", audio_url=url, title=title, published=pub.isoformat() if pub else None,
                    preacher=_feed_preacher(it, church),
                    description=re.sub(r"<[^>]+>", " ", it.findtext("description") or "")[:600],
                    page_url=(it.findtext("link") or "").strip() or None, score=score,
                    duration=(it.findtext(f"{ITUNES}duration") or "").strip() or None)
        if best is None or score > best["score"]: best = cand
    return best


def _feed_preacher(it, church) -> str | None:
    """itunes:author if it's a person (not the church name), else 'Passage | Name' in the description."""
    a = (it.findtext(f"{ITUNES}author") or "").strip()
    if a and church["church"].lower() not in a.lower() and "church" not in a.lower(): return a
    desc = re.sub(r"<[^>]+>", " ", it.findtext("description") or "")
    m = re.search(r"\|\s*([A-Z][a-z]+(?:\s+[A-Z][a-z.]+){1,2})\s*$", desc.strip())
    return m.group(1) if m else None


# ── YouTube livestream ───────────────────────────────────────────────────────
def _yt_rss(channel: str) -> list[dict]:
    xml = http_get(f"https://www.youtube.com/feeds/videos.xml?channel_id={channel}").content
    ns = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015", "m": "http://search.yahoo.com/mrss/"}
    out = []
    for e in ET.fromstring(xml).findall("a:entry", ns):
        out.append(dict(id=e.findtext("yt:videoId", namespaces=ns), title=e.findtext("a:title", namespaces=ns),
                        published=datetime.fromisoformat(e.findtext("a:published", namespaces=ns)).astimezone(CT)))
    return out


def _ytdlp(args: list[str], timeout=180) -> str:
    r = subprocess.run(["yt-dlp", "--no-warnings", "--retries", "5", "--extractor-retries", "3", *args],
                       capture_output=True, text=True, timeout=timeout)
    if r.returncode:
        raise RuntimeError(f"yt-dlp failed: {r.stderr.strip()[-400:]}")
    return r.stdout


def _yt_streams_tab(channel: str) -> list[str]:
    try:
        out = _ytdlp(["--flat-playlist", "--playlist-end", "5", "--print", "%(id)s",
                      f"https://www.youtube.com/channel/{channel}/streams"], timeout=120)
        return [x.strip() for x in out.splitlines() if x.strip()]
    except Exception as e:  # noqa: BLE001
        log.warning(f"streams tab lookup failed for {channel}: {str(e)[:200]}"); return []


@retry(tries=3, wait=20, what="yt-dlp metadata")
def yt_meta(video_id: str) -> dict:
    return json.loads(_ytdlp(["-j", "--skip-download", f"https://www.youtube.com/watch?v={video_id}"]))


def youtube(church: dict, week: str) -> dict | None:
    """The full-service livestream from that Sunday (CT date of the stream start)."""
    d, lo, hi = sunday_window(week, before_h=36, after_days=3)
    rss = []
    try: rss = _yt_rss(church["youtube"])
    except Exception as e: log.warning(f"{church['key']}: YouTube RSS failed: {e}")
    ids = [v["id"] for v in rss if lo <= v["published"] <= hi]
    for vid in _yt_streams_tab(church["youtube"]):
        if vid not in ids: ids.append(vid)
    rss_by = {v["id"]: v for v in rss}
    seen_live_now = None
    for vid in ids[:6]:
        try:
            m = yt_meta(vid)
        except Exception as e:  # noqa: BLE001
            log.warning(f"{church['key']}: metadata for {vid} failed: {str(e)[:200]}")
            continue
        ts = m.get("release_timestamp") or m.get("timestamp")
        when = datetime.fromtimestamp(ts, CT) if ts else None
        if not when or when.date() != d: continue
        status = m.get("live_status")
        if status in ("is_live", "is_upcoming", "post_live"):
            seen_live_now = f"stream {vid} is {status}; try later"; continue
        if (m.get("duration") or 0) < 35 * 60: continue
        return dict(kind="youtube", yt_id=vid, url=f"https://www.youtube.com/watch?v={vid}", title=m.get("title"),
                    published=when.isoformat(), duration=m.get("duration"), live_status=status,
                    description=(m.get("description") or "")[:1500])
    if seen_live_now: raise RuntimeError(seen_live_now)
    if ids and not rss_by: return None
    return None


# ── Grace Life (WordPress resource pages; the resource feed has no enclosures) ──
def gracelife(church: dict, week: str) -> dict | None:
    d, lo, hi = sunday_window(week)
    tok = f"{d.month}-{d.day}-{d.strftime('%y')}"
    listing = http_get(church["gracelife"]).text
    links = []
    for href in re.findall(r'href="(https://www\.gracelifene\.org/resource/[a-z0-9-]+/)"', listing):
        if href.endswith(("/feed/", "/resource/")) or "/page/" in href or href in links: continue
        links.append(href)
    for href in links[:8]:
        page = http_get(href).text
        mp3s = re.findall(r'https://[^"\'\s<>]+\.mp3', page)
        hit = next((u for u in mp3s if re.search(rf"(?<!\d){re.escape(tok)}(?!\d)", u)), None)
        if not hit: continue
        t = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S) or re.search(r"<title>(.*?)</title>", page, re.S)
        title = htmlmod.unescape(re.sub(r"<[^>]+>", "", t.group(1))).split("|")[0].split(" – ")[0].strip() if t else None
        name = re.match(r"([A-Za-z]+)-([A-Za-z]+)-\d", hit.rsplit("/", 1)[-1])
        return dict(kind="gracelife", audio_url=hit, title=title, page_url=href,
                    preacher=f"{name.group(1)} {name.group(2)}" if name else None)
    return None


# ── Providence: already processed by the iMac jobs; look it up, never re-process ──
def pipeline(church: dict, week: str) -> dict | None:
    from pipeline import get_supabase
    sb = get_supabase()
    pids = [p["id"] for p in sb.table("preachers").select("id").eq("church_id", church["church_id"]).execute().data]
    rows = sb.table("sermons").select("id,title,slug,date,preacher_id,preachers(name)").in_("preacher_id", pids)\
        .eq("date", week).execute().data
    if not rows: return None
    r = rows[0]
    return dict(kind="pipeline", sermon_id=r["id"], title=r["title"], slug=r["slug"],
                preacher=(r.get("preachers") or {}).get("name"))


FINDERS = {"podcast": podcast, "youtube": youtube, "gracelife": gracelife, "pipeline": pipeline}


def find(church: dict, week: str, run: str) -> tuple[dict | None, list[str]]:
    """Try the church's sources for this run in order. Returns (candidate, notes)."""
    notes = []
    for kind in church["sources"].get(run, []):
        try:
            c = FINDERS[kind](church, week)
        except Exception as e:  # noqa: BLE001
            notes.append(f"{kind}: error: {str(e)[:200]}"); continue
        if c: return c, notes + [f"{kind}: found"]
        notes.append(f"{kind}: nothing for {week} yet")
    if not church["sources"].get(run):
        notes.append(f"no sources scheduled for the {run} run")
    return None, notes
