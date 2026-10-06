"""Site side of the launch (runs on the box, which has node + wrangler; the Studio has neither).

  python -m regional.mwnw.week pages     --week 2026-10-04 --site /path/to/sermon-steward
  python -m regional.mwnw.week quotes    --week 2026-10-04            (Haiku, ~$0.05; cached)
  python -m regional.mwnw.week dashboard --week 2026-10-04 --site ...
  python -m regional.mwnw.week all       --week 2026-10-04 --site ...   (pages, quotes, dashboard, week JSON, node build.mjs)

pages:     each READY church's sermon page at /SGchurch/<ChurchCity>/sermons/<slug>.html (unlisted,
           noindex via UNLISTED_ROOTS) + a small church index at /SGchurch/<ChurchCity>/, with the
           "Suggest a change" affordance. Providence keeps its own pipeline-deployed page.
quotes:    How We Said It lines (preacher's own words) and Gimme da quotes! (who he quoted), every
           line verified as an exact substring of the transcript.
dashboard: /SGchurch/MidwestNorthwest/<M-D-YY>/index.html in the live 9-27-26 design, with the three
           region markers that scripts/sg-region/build.mjs fills. Churches that are MISSING are left out.
"""
from __future__ import annotations
import argparse, collections, datetime, glob, html, json, os, re, shutil, subprocess
from pathlib import Path
from . import config
from .util import load_all, week_dir, week_slug, log, REPO
from .media import HAIKU, cl
from .titles import clean_title  # title rule: no scripture in sermon titles (ref shown on its own line)

REGION = f"/SGchurch/{config.REGION}"
TRY = "https://try.sermonsteward.com/mw"
FREE = "Free for Sovereign Grace Midwest/Northwest churches for at least the next year."
ORDER = ["prov", "cog", "ccc", "gl", "ercsf", "ercb", "star", "clf"]
# cog = Chaska only. Ricky / El Paso = cogep / CoGElPaso (SovereignGrace dashboard), never this key.
SHORT = {"prov": "Providence · Lenexa", "cog": "Cross of Grace · Chaska", "ccc": "Cornerstone · Burnsville", "gl": "Grace Life · Hastings",
         "ercsf": "Emmaus Rd · Sioux Falls", "ercb": "Emmaus Rd · Bozeman", "star": "Center Church · Star", "clf": "Covenant Life · Roseburg"}
h = lambda s: html.escape(str(s) if s is not None else "", quote=True)  # noqa: E731


def sb():
    from pipeline import get_supabase
    return get_supabase()


def page_path(ch, slug):
    return f"/ProvidenceLenexa/sermons/{slug}.html" if ch.get("public") else f"/SGchurch/{ch['dir']}/sermons/{slug}.html"


def ready(week):
    st = load_all(week)
    return [(config.BY_KEY[k], st[k]) for k in ORDER if st[k].get("status") == "READY"]


# ── church pages ─────────────────────────────────────────────────────────────
def pages(week, site: Path):
    from sermon_page_renderer import queries as q, composer
    from sermon_page_renderer.template_engine import render_sermon_page
    try:
        import scripts.generate_og_card as _og
        _ls = _og.load_sermon
        _og.load_sermon = lambda sb_, sid_: {**_ls(sb_, sid_), "title": clean_title(_ls(sb_, sid_).get("title"))}  # title rule on share cards too
        generate_og_card = _og.generate_og_card
    except Exception:  # noqa: BLE001
        generate_og_card = None
    raw = q.get_sermon; dash = f"{REGION}/{week_slug(week)}/"; out = {}
    for ch, c in ready(week):
        if ch.get("public"): continue
        sid = c["sermon_id"]; base = f"SGchurch/{ch['dir']}"
        def fake(s, _ch=ch, _b=base):
            r = dict(raw(s)); r["title"] = clean_title(r.get("title")); p = dict(r.get("preachers") or {}); cc = dict(p.get("churches") or {})
            cc.update(url_slug=_b, domain="sermonsteward.com", brand_color=cc.get("brand_color") or "#2d5a4a"); p["churches"] = cc; r["preachers"] = p; return r
        q.get_sermon = fake
        try:
            card = generate_og_card(sid, sb=q.get_supabase()) if generate_og_card else None
        except Exception as e:  # noqa: BLE001
            card = None; log.warning(f"og card failed {ch['key']}: {e}")
        ctx = composer.compose(sid); ctx["suggest_change"] = True
        page = render_sermon_page(ctx); q.get_sermon = raw
        row = raw(sid); slug = row["slug"]; loc = f"{ch['city']}, {ch['state']}"
        src = c.get("source") or {}
        src_url = src.get("url") or src.get("page_url") or src.get("audio_url") or ch["site"]
        src_kind = {"youtube": "YouTube livestream (sermon portion)", "podcast": "Podcast feed", "gracelife": "Church website (MP3)"}.get(src.get("kind"), "Church website")
        page = re.sub(r'<a href="[^"]*" class="site-brand">.*?</a>', f'<a href="/{base}/" class="site-brand">{h(ch["church"])} · {h(ch["city"])}</a>', page, count=1, flags=re.S)
        page = re.sub(r'<nav class="site-nav ui">.*?</nav>', f'<nav class="site-nav ui"><a href="{dash}">SG Midwest/Northwest</a><a href="{h(ch["site"])}" rel="noopener">Church website</a></nav>', page, count=1, flags=re.S)
        page = re.sub(r'<div class="breadcrumb ui">.*?</div>', f'<div class="breadcrumb ui"><a href="{dash}">Sovereign Grace Midwest/Northwest</a> · <a href="/{base}/">{h(ch["church"])}, {h(loc)}</a></div>', page, count=1, flags=re.S)
        if not row.get("hosted_audio_url") and not row.get("audio_url"):
            page = re.sub(r'<div class="audio-player" id="audio">\s*<button class="play-button disabled".*?</span>\s*</div>',
                          f'<div class="audio-player" id="audio" style="justify-content:flex-start;gap:12px"><a class="ui" href="{h(src_url)}" rel="noopener" style="color:var(--accent);font-weight:600">Watch this sermon on the church\'s YouTube channel →</a></div>', page, count=1, flags=re.S)
        about = (f'<!-- ═══════════ About the church ═══════════ -->\n    <section class="page-section">\n      <div class="section-eyebrow ui">Where this was preached</div>\n'
                 f'      <h2 class="section-title-h2">About the church</h2>\n      <div class="church-card">\n        <div>\n'
                 f'          <div class="church-name">{h(ch["church"])}</div>\n          <div class="church-addr ui">{h(loc)} · Sovereign Grace Churches<br>\n'
                 f'            Sermon source: <a href="{h(src_url)}" rel="noopener" style="color:var(--accent);">{h(src_kind)}</a> · <a href="{dash}" style="color:var(--accent);">All Midwest/Northwest sermons</a>\n'
                 f'          </div>\n        </div>\n        <a href="{h(ch["site"])}" rel="noopener" class="visit-cta ui">Visit the church →</a>\n      </div>\n    </section>\n')
        page = re.sub(r'<!-- ═══════════ About the church ═══════════ -->.*?</details>\s*</section>\n', lambda m: about, page, count=1, flags=re.S)
        if '<meta name="robots"' not in page: page = page.replace("<head>", '<head>\n<meta name="robots" content="noindex, nofollow">', 1)
        dest = site / base / "sermons" / f"{slug}.html"; dest.parent.mkdir(parents=True, exist_ok=True); dest.write_text(page)
        if card and os.path.exists(str(card)): shutil.copy(str(card), dest.with_suffix(".png"))
        church_index(site, ch); out[ch["key"]] = f"/{base}/sermons/{slug}.html"; log.info(f"page {dest}")
    return out


def church_index(site: Path, ch: dict):
    """Small unlisted landing for /SGchurch/<ChurchCity>/: latest sermon first."""
    d = site / "SGchurch" / ch["dir"]; items = []
    for f in sorted((d / "sermons").glob("*.html"), key=lambda p: p.stem[-10:], reverse=True):
        t = re.search(r"<title>(.*?)</title>", f.read_text(), re.S)
        items.append((f.stem[-10:], (t.group(1).split("·")[0].split("|")[0].strip() if t else f.stem), f.name))
    lis = "".join(f'<li><a href="sermons/{h(n)}">{h(t)}</a> <span>{h(datetime.date.fromisoformat(dt).strftime("%B %-d, %Y")) if re.match(r"\d{4}-\d\d-\d\d", dt) else ""}</span></li>' for dt, t, n in items)
    (d / "index.html").write_text(f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow"><title>{h(ch.get('index_name') or ch['church'])} · {h(ch['city'])} · Sermon Steward</title>
<style>body{{margin:0;background:#fbf8f1;color:#1a1a1a;font-family:Inter,system-ui,sans-serif}} .w{{max-width:760px;margin:0 auto;padding:40px 24px}}
h1{{font-family:'Source Serif 4',Georgia,serif;font-size:2.2rem;margin:6px 0}} .k{{font-size:13px;font-weight:700;color:#c4452f;letter-spacing:.06em;text-transform:uppercase}}
ul{{list-style:none;padding:0}} li{{background:#fff;border:1px solid #e6e1d3;border-radius:12px;padding:14px 16px;margin:10px 0;display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}}
li a{{font-family:'Source Serif 4',Georgia,serif;font-size:1.2rem;color:#1a1a1a;font-weight:600}} li span{{color:#828282;font-size:14px}} a{{color:#c4452f}}</style></head>
<body><div class="w"><div class="k">Sovereign Grace Midwest/Northwest</div><h1>{h(ch.get('index_name') or ch['church'])}</h1><p>{h(ch['city'])}, {h(ch['state'])} · <a href="{h(ch['site'])}" rel="noopener">Church website</a> · <a href="{REGION}/">This week across the region</a></p>
<ul>{lis}</ul><p style="color:#828282;font-size:13px">Stewarded by Sermon Steward. Sermons belong to the church and preacher.</p></div></body></html>""")


# ── metrics (port of the Sep 27 metrics.py, parameterized by week) ───────────
OT = set("Genesis Exodus Leviticus Numbers Deuteronomy Joshua Judges Ruth Samuel Kings Chronicles Ezra Nehemiah Esther Job Psalm Psalms Proverbs Ecclesiastes Song Isaiah Jeremiah Lamentations Ezekiel Daniel Hosea Joel Amos Obadiah Jonah Micah Nahum Habakkuk Zephaniah Haggai Zechariah Malachi".split())
def book(ref):
    m = re.match(r"\s*((?:[123]\s*)?[A-Za-z]+(?:\s(?:of\s)?[A-Za-z]+)*?)\s*\d", ref or "")
    return (m.group(1).strip() if m else (ref or "").split(" ")[0]).replace("Psalms", "Psalm")


def metrics(week):
    S = sb(); rows = []
    for ch, c in ready(week):
        sid = c["sermon_id"]
        s = S.table("sermons").select("id,title,slug,date,primary_text,sermon_type,tone,hermeneutical_method,main_thesis,series_name,raw_transcript,audio_duration_seconds,preachers(name)").eq("id", sid).single().execute().data
        units = S.table("units").select("id,unit_index,rhetorical_function,content,illustration_type,application_specificity,doctrinal_loci").eq("sermon_id", sid).order("unit_index").execute().data
        uids = [u["id"] for u in units]; cits, bts, quots = [], [], []
        for i in range(0, len(uids), 50):
            chn = uids[i:i + 50]
            cits += S.table("citations").select("tier,reference").in_("unit_id", chn).execute().data
            bts += S.table("bt_moves").select("type").in_("unit_id", chn).execute().data
            quots += S.table("quotations").select("attribution").in_("unit_id", chn).execute().data
        tx = s.get("raw_transcript") or ""; words = len(re.findall(r"[A-Za-z0-9']+", tx))
        mins = c.get("sermon_minutes") or (round(s["audio_duration_seconds"] / 60, 1) if s.get("audio_duration_seconds") else None)
        uw = lambda u: len(re.findall(r"[A-Za-z0-9']+", u.get("content") or ""))  # noqa: E731
        tot = sum(uw(u) for u in units) or 1
        rf, rfw = collections.Counter(), collections.Counter()
        for u in units: rf[u["rhetorical_function"] or "other"] += 1; rfw[u["rhetorical_function"] or "other"] += uw(u)
        loci = collections.Counter(l for u in units for l in (u["doctrinal_loci"] or []))
        christ_units = sum(1 for u in units if "Christology" in (u["doctrinal_loci"] or []))
        ill = [u["illustration_type"] for u in units if u["illustration_type"]]
        app = [u["application_specificity"] for u in units if u["rhetorical_function"] == "application" or u["application_specificity"]]
        t2 = [x["reference"] for x in cits if x["tier"] == 2]; pt = s.get("primary_text") or ""; b = book(pt)
        rows.append(dict(key=ch["key"], church=ch["church"], city=ch["city"], state=ch["state"], preacher=(s.get("preachers") or {}).get("name"),
            site=ch["site"], path=page_path(ch, s["slug"]), sid=sid, title=clean_title(s["title"]), date=s["date"], primary_text=pt, book=b,
            testament="OT" if b.split()[-1:] and b.split()[-1] in OT else "NT", sermon_type=s.get("sermon_type"), tone=s.get("tone") or [],
            method=s.get("hermeneutical_method") or [], thesis=s.get("main_thesis"), minutes=mins, words=words, wpm=round(words / mins) if mins else None,
            units=len(units), rf_words={k: round(100 * v / tot, 1) for k, v in rfw.items()}, application_pct=round(100 * rfw.get("application", 0) / tot, 1),
            app_concrete=sum(1 for a in app if a == "concrete"), app_abstract=sum(1 for a in app if a == "abstract"),
            illustrations=len(ill), illustration_types=dict(collections.Counter(ill)), cross_refs=len(t2), cross_ref_books=len({book(r) for r in t2}),
            quotations=len(quots), quoted=sorted({q["attribution"] for q in quots if q.get("attribution")})[:6],
            bt_moves=len(bts), bt_types=dict(collections.Counter(x["type"] for x in bts)),
            christ_units_pct=round(100 * christ_units / max(1, len(units))), top_loci=loci.most_common()))
    (week_dir(week) / "metrics.json").write_text(json.dumps(rows, indent=1, default=str))
    return rows


# ── dashboard (port of build_dashboard.py, matched to the live 9-27-26 page) ─
FN = [("exposition", "Exposition", "#2d5a4a"), ("theological_claim", "Theological claim", "#6b8f71"), ("application", "Application", "#c4452f"),
      ("illustration", "Illustration", "#e0a43a"), ("introduction", "Intro / conclusion", "#8a7fb5"), ("conclusion", None, "#8a7fb5"),
      ("transition", "Transitions, asides, prayer", "#b9b2a3"), ("pastoral_aside", None, "#b9b2a3"), ("prayer", None, "#b9b2a3")]


def dashboard(week, R, site: Path, n_total=8):
    def mix(r):
        g = collections.OrderedDict()
        for k, lab, col in FN:
            key = lab or [l for kk, l, cc in FN if cc == col and l][0]
            g.setdefault(key, [0, col]); g[key][0] += r["rf_words"].get(k, 0)
        known = {k for k, _, _ in FN}; other = sum(v for k, v in r["rf_words"].items() if k not in known)
        if other: g["Transitions, asides, prayer"][0] += other
        return g
    def stacked(r, height=14):
        segs = "".join(f'<span title="{h(k)}: {v[0]:.0f}%" style="width:{v[0]}%;background:{v[1]}"></span>' for k, v in mix(r).items() if v[0] > 0)
        return f'<div class="stack" style="height:{height}px">{segs}</div>'
    short = lambda r: SHORT.get(r["key"], r["church"])  # noqa: E731
    def bars(metric, fmt=lambda v: f"{v}", unit="", note=""):
        vals = [r[metric] or 0 for r in R]; mx = max(vals) or 1; avg = sum(vals) / len(vals)
        rows = "".join(f'<div class="bar-row"><div class="bar-label">{h(short(r))}</div><div class="bar-track"><div class="bar" style="width:{100*(r[metric] or 0)/mx:.1f}%"></div><div class="avg" style="left:{100*avg/mx:.1f}%"></div></div><div class="bar-val">{h(fmt(r[metric]) if r[metric] is not None else "—")}{unit}</div></div>' for r in R)
        return f'<div class="bars">{rows}</div><div class="chart-note"><span class="avg-key"></span> regional average: {h(fmt(round(avg,1)))}{unit}. {note}</div>'
    loci_all = collections.Counter()
    for r in R:
        for l, n in r["top_loci"]: loci_all[l] += n
    TOPL = [l for l, _ in loci_all.most_common(7)]
    lc = lambda r, l: dict(r["top_loci"]).get(l, 0)  # noqa: E731
    mxl = max([lc(r, l) for r in R for l in TOPL] or [1]) or 1
    heat = "".join(f"<tr><th>{h(short(r))}</th>" + "".join(f'<td style="background:rgba(45,90,74,{0.08+0.82*lc(r,l)/mxl:.2f});color:{"#fff" if lc(r,l)/mxl>0.55 else "#1a1a1a"}">{lc(r,l) or ""}</td>' for l in TOPL) + "</tr>" for r in R)
    tot = lambda k: sum((r[k] or 0) for r in R)  # noqa: E731
    books = collections.Counter(r["testament"] for r in R)
    cards = ""
    for r in R:
        th = (r["thesis"] or "").strip()
        if len(th) > 210: th = th[:207].rsplit(" ", 1)[0] + "…"
        badge = '<span class="badge cust">On Sermon Steward</span>' if r["key"] == "prov" else ""
        cards += f'''<a class="card" href="{h(r['path'])}">
  <div class="card-top"><div class="church">{h(r['church'])}</div><div class="loc">{h(r['city'])}, {h(r['state'])}</div>{badge}</div>
  <h3>{h(r['title'])}</h3>
  <div class="meta">{h(r['primary_text'])} · {h(r['preacher'])}</div>
  <p class="thesis">{h(th)}</p>
  {stacked(r)}
  <div class="nums"><span><b>{h(r['minutes'])}</b> min</span><span><b>{r['units']}</b> segments</span><span><b>{r['cross_refs']}</b> cross-refs</span><span><b>{r['bt_moves']}</b> BT moves</span></div>
  <div class="go">Open the stewarded sermon →</div>
</a>'''
    legend = "".join(f'<span><i style="background:{c}"></i>{h(l)}</span>' for k, l, c in FN if l)
    mixrows = "".join(f'<div class="bar-row"><div class="bar-label">{h(short(r))}</div><div class="bar-track plain">{stacked(r,18)}</div><div class="bar-val">{r["application_pct"]:.0f}% app.</div></div>' for r in R)
    detail = "".join(f'''<tr><th><a href="{h(r['path'])}">{h(short(r))}</a></th><td>{h(r['primary_text'])}</td><td>{h(r['testament'])}</td><td>{h((r['sermon_type'] or '').title())}</td>
<td>{h(', '.join(m.replace('_','-') for m in r['method']))}</td><td>{h(', '.join(r['tone']))}</td><td>{r['illustrations']}{(' ('+h(', '.join(k.replace('_',' ') for k in r['illustration_types']))+')') if r['illustration_types'] else ''}</td>
<td>{r['app_concrete']} / {r['app_abstract']}</td><td>{r['quotations']}{(' — '+h(', '.join(r['quoted'][:3]))) if r['quoted'] else ''}</td><td>{h(', '.join(f"{k.replace('_',' ')} {v}" for k,v in r['bt_types'].items()))}</td></tr>''' for r in R)
    date_h = datetime.date.fromisoformat(week).strftime("%B %-d, %Y")
    missing = n_total - len(R)
    miss_note = f" {missing} church{'es' if missing > 1 else ''} had no sermon available in time and will be added when it is." if missing > 0 else ""
    css = Path(__file__).with_name("dashboard.css").read_text()
    page = f'''<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Sovereign Grace Midwest/Northwest · One Sunday, {len(R)} pulpits · Sermon Steward</title>
<meta name="description" content="Sovereign Grace Midwest/Northwest sermons from one Sunday, each stewarded by Sermon Steward.">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Source+Serif+4:ital,wght@0,400;0,600;1,400&display=swap" rel="stylesheet">
<style>
{css}</style></head><body>
<header><div class="wrap"><a class="wordmark" href="/">Sermon Steward<i>.</i></a>{"" if config.REGION == "SovereignGrace" else f'<a class="btn sm" href="{TRY}">Try it free: Bigfoot Region</a>'}</div></header>
<main class="wrap">
<section class="hero">
  <div class="tag">Sovereign Grace Midwest/Northwest · Sunday, {date_h}</div>
  <h1>One Sunday. <span>{len(R)} pulpits.</span> Every sermon stewarded.</h1>
  <p class="deck">The Sunday sermon from each church in the region, from Roseburg to Lenexa, run through Sermon Steward: transcript, structure, theology, Scripture use, and five resources for the congregation. Then laid side by side.{h(miss_note)}</p>
  <div class="price">{FREE}</div>
  <div class="stats">
    <div class="stat"><b>{len(R)}</b><span>sermons, one Sunday</span></div>
    <div class="stat"><b>{round(tot('minutes'))}</b><span>minutes of preaching</span></div>
    <div class="stat"><b>{tot('words'):,}</b><span>words transcribed</span></div>
    <div class="stat"><b>{tot('units')}</b><span>sermon segments analyzed</span></div>
    <div class="stat"><b>{tot('cross_refs')}</b><span>cross-references traced</span></div>
    <div class="stat"><b>{len(R)*5}</b><span>congregation resources</span></div>
  </div>
</section>
<!-- region:weeknav --><!-- /region:weeknav -->

<h2>The pulpits</h2>
<p class="sub">Each card opens that church's stewarded sermon page. <b>People</b> view: reading plan, discussion questions, family and couples guides, memory verse. <b>Preacher</b> view: outline, homiletic analysis, and the full transcript. The color bar shows how the sermon's words split across exposition, theology, application, and illustration.</p>
<div class="legend">{legend}</div>
<div class="grid"><!-- region:hwsi-tile --><!-- /region:hwsi-tile -->{cards}</div>

<h2>{"Sovereign Grace sermons side by side" if config.REGION == "SovereignGrace" else "The region side by side"}</h2>
<p class="sub">Every number below comes from the transcripts and from Sermon Steward's sermon breakdown, which splits each sermon into segments and tags each one. Derived figures are marked <b>(derived)</b>, and the method notes at the bottom explain each one.</p>

<div class="panel"><h3>The texts this Sunday</h3><p class="q">Main preaching text for each sermon. {books.get('OT',0)} Old Testament and {books.get('NT',0)} New Testament.</p>
<div class="texts">{''.join(f'<a class="txt {r["testament"].lower()}" href="{h(r["path"])}"><b>{h(r["primary_text"])}</b><span>{h(short(r))}</span></a>' for r in R)}</div></div>

<div class="panel"><h3>Where the words went</h3><p class="q">Share of each sermon's words by segment type (derived: words in segments with each tag ÷ all segment words).</p>
<div class="legend">{legend}</div>{mixrows}</div>

<div class="two">
 <div class="panel"><h3>Sermon length</h3><p class="q">Minutes from the first word of the sermon to the closing prayer (livestreams were cut to the sermon).</p>{bars('minutes', lambda v: f'{v:.0f}', ' min')}</div>
 <div class="panel"><h3>Pace</h3><p class="q">Words per minute (derived: transcript words ÷ minutes).</p>{bars('wpm', lambda v: f'{v:.0f}', '')}</div>
 <div class="panel"><h3>Application share</h3><p class="q">% of words in segments tagged <i>application</i> (derived).</p>{bars('application_pct', lambda v: f'{v:.0f}', '%')}</div>
 <div class="panel"><h3>Christology in the argument</h3><p class="q">% of segments whose doctrinal tags include Christology.</p>{bars('christ_units_pct', lambda v: f'{v:.0f}', '%')}</div>
 <div class="panel"><h3>Biblical-theological moves</h3><p class="q">Typology, fulfillment, narrative arc, and thematic threads the breakdown found tying the text to the whole Bible story.</p>{bars('bt_moves')}</div>
 <div class="panel"><h3>Cross-references</h3><p class="q">Other passages brought in beyond the main text.</p>{bars('cross_refs', note='')}</div>
 <div class="panel"><h3>Breadth of Scripture</h3><p class="q">Distinct books among those cross-references.</p>{bars('cross_ref_books')}</div>
 <!-- region:gdq-panel --><!-- /region:gdq-panel -->
</div>

<div class="panel"><h3>Doctrinal emphasis heatmap</h3><p class="q">Number of segments tagged with each of the region's most common doctrinal loci (darker = more segments; blank = none).</p>
<div class="scroll"><table class="heat"><thead><tr><th></th>{''.join(f'<th>{h(l)}</th>' for l in TOPL)}</tr></thead><tbody>{heat}</tbody></table></div></div>

<div class="panel"><h3>The homiletic ledger</h3><p class="q">Text, type, method, tone, illustrations, application (concrete / abstract), quotations, and biblical-theological moves for each sermon. {books.get('OT',0)} Old Testament texts, {books.get('NT',0)} New Testament texts.</p>
<div class="scroll"><table><thead><tr><th>Church</th><th>Text</th><th>Test.</th><th>Type</th><th>Method</th><th>Tone</th><th>Illustrations</th><th>Application conc./abs.</th><th>Quotations (as tagged)</th><th>BT moves</th></tr></thead><tbody>{detail}</tbody></table></div></div>

<section class="cta"><div><h2>Every Sunday, stewarded.</h2><p>Each church's sermon is transcribed, mapped, and turned into a report and five congregation resources, and the region's preaching shows up side by side here. {FREE}</p></div>
<div style="text-align:center"><a class="btn" href="/hall/glossary">How it works: the glossary</a></div></section>

<h2>How these numbers are made</h2>
<ul class="method">
<li><b>Sources.</b> Each church's own public sermon feed, website, or YouTube livestream for the Sunday shown. One sermon per church. No archives were imported. Providence's sermon comes from its regular Sermon Steward run.</li>
<li><b>Transcripts</b> are machine transcriptions (AssemblyAI). For full-service livestreams, only the sermon (first word to closing prayer) was kept. Podcast files are used as published and may include a short reading or closing line.</li>
<li><b>Segments and tags</b> come from Sermon Steward's breakdown model, which tags each segment by function (exposition, application, illustration…), doctrinal loci, Scripture citations, quotations, and biblical-theological moves. These are model readings, not hand counts.</li>
<li><b>Derived:</b> word shares, application share, and words per minute are simple arithmetic on the transcript and tags.</li>
<li><b>Sermon length</b> for livestreams is measured from the sermon's start and end timestamps. For podcast files it is the length of the published audio.</li>
</ul>
</main>
<footer><div class="wrap">Prepared by Sermon Steward for the pastors of Sovereign Grace Midwest/Northwest. Sermons belong to their churches and preachers. Each page links back to the church.</div></footer>
</body></html>'''
    dest = site / "SGchurch" / config.REGION / week_slug(week) / "index.html"; dest.parent.mkdir(parents=True, exist_ok=True); dest.write_text(page)
    log.info(f"dashboard {dest}"); return dest


# ── quotes (ports of mw_quotes/extract.py + external.py; every line verified verbatim) ──
FILLER = re.compile(r"(?:(?<=^)|(?<=[\s,.;!?]))(?:um+|uh+|erm)(?:[,.]\s*|\s+)", re.I)
def norm(s): return re.sub(r"\s+", " ", (s or "").replace("\u2019", "'").replace("\u2018", "'").replace("\u201c", '"').replace("\u201d", '"')).strip()


def _json_list(t):
    t = t[t.find("["):t.rfind("]") + 1] or "[]"
    try: return json.loads(t)
    except Exception: return []  # noqa: E701


def quotes(week, R, per=6):
    cache = week_dir(week) / "quotes.json"
    have = json.loads(cache.read_text()) if cache.exists() else {}
    S = sb()
    for r in R:
        if r["key"] in have: continue
        raw = norm(S.table("sermons").select("raw_transcript").eq("id", r["sid"]).single().execute().data["raw_transcript"])
        units = S.table("units").select("id,unit_index,rhetorical_function,content").eq("sermon_id", r["sid"]).order("unit_index").execute().data
        body = "\n\n".join(f"[unit {u['unit_index']} · {u['rhetorical_function']}]\n{u['content']}" for u in units)
        m = cl().messages.create(model=HAIKU, max_tokens=3000, messages=[{"role": "user", "content": f"""Below is the transcript of a sermon by {r['preacher']}, split into numbered units.
Pick the 9 most quotable lines THE PREACHER HIMSELF says: memorable, self-contained, theologically meaty or vivid lines a pastor would want to share. Each line is 1-3 consecutive sentences, ideally 12-60 words.
STRICT RULES:
- Copy each line EXACTLY, character for character, from the transcript text. Do not fix grammar, do not join non-adjacent sentences, do not paraphrase.
- Do NOT pick Scripture being read aloud, quotations of other authors, announcements, or prayers.
- Spread picks across the sermon. Order them by how strong they are, best first.
Return ONLY JSON: [{{"unit": <unit number>, "text": "<exact line>"}}, ...]

{body}"""}])
        lines = []
        for p in _json_list(m.content[0].text):
            q = norm(p.get("text"))
            if len(q) > 20 and q in raw and len(lines) < per:
                unit = next((u["unit_index"] for u in units if q in norm(u["content"])), None)
                clean = re.sub(r"\s+", " ", FILLER.sub("", q)).strip(); clean = clean[0].upper() + clean[1:]
                lines.append({"text": clean, "anchor": f"unit-{unit}" if unit is not None else "transcript", **({"filler_removed": True} if clean != q else {})})
        idx = {u["id"]: u["unit_index"] for u in units}
        led = S.table("quotations").select("unit_id,text,attribution,source").in_("unit_id", list(idx)).execute().data if idx else []
        cands = [{"text": q["text"], "author": q["attribution"], "work": q["source"]} for q in led]
        m2 = cl().messages.create(model=HAIKU, max_tokens=3000, messages=[{"role": "user", "content": f"""Below is a sermon transcript by {r['preacher']}, in numbered units.
List EVERY place the preacher quotes or recites words from a NON-BIBLICAL source: authors, theologians, pastors, hymns/songs, creeds/catechisms, historical figures, articles, films, etc.
Exclude Bible verses entirely. Exclude the preacher paraphrasing someone in his own words unless he is clearly reciting their words.
For each, copy the quoted words EXACTLY as they appear in the transcript, give the author and work ONLY if the preacher names them in the transcript (as said; else null; never guess), and "as_said": how he referred to the source if unnamed (e.g. "one commentator"), else null.
Return ONLY JSON: [{{"unit": <n>, "text": "<exact quoted words>", "author": <name or null>, "work": <title or null>, "as_said": <phrase or null>}}]  (return [] if none)

{body}"""}])
        cands += _json_list(m2.content[0].text)
        ext, seen = [], []
        for c in cands:
            q = norm(c.get("text")).strip(" \"'"); pos = raw.find(q)
            if pos < 0 or len(q) < 25: continue
            if any(q in s or s in q for s in seen): continue
            win = raw[max(0, pos - 700):pos + len(q) + 400].lower()
            def named(x):
                if not x or x in ("None", "Unattributed"): return False
                toks = [w for w in re.findall(r"[A-Za-z]{3,}", x) if w.lower() not in ("the", "and", "one", "apostle", "sermon", "article")]
                return bool(toks) and toks[-1].lower() in win
            au = c.get("author") if named(c.get("author")) else None
            wk = c.get("work") if (au and named(c.get("work"))) else None
            unit = next((u["unit_index"] for u in units if q in norm(u["content"])), None)
            seen.append(q)
            ext.append({"text": q, "author": au, "work": wk, "attributed": bool(au), "as_said": None if au else (c.get("as_said") or "someone he quoted"),
                        "anchor": f"unit-{unit}" if unit is not None else "transcript", "excerpt": False})
        have[r["key"]] = {"lines": lines, "external": ext[:8]}
        cache.write_text(json.dumps(have, indent=1, ensure_ascii=False)); log.info(f"quotes {r['key']}: {len(lines)} lines, {len(ext)} external")
    return have


def week_json(week, R, Q, site: Path):
    sermons = []
    for r in R:
        ch = config.BY_KEY[r["key"]]
        sermons.append({"key": r["key"], "church": r["church"], "city": r["city"], "state": r["state"], "preacher": r["preacher"], "title": r["title"], "ref": r.get("primary_text") or None,
                        "url": r["path"], "lines": Q.get(r["key"], {}).get("lines", []), "external": Q.get(r["key"], {}).get("external", []), "short": SHORT[r["key"]]})
    pool = [(s, l) for s in sermons for l in s["lines"] if 40 <= len(l["text"]) <= 120]
    feat = None
    if pool:
        listing = "\n".join(f"[{i}] {l['text']} ({s['preacher']})" for i, (s, l) in enumerate(pool))
        try:
            m = cl().messages.create(model=HAIKU, max_tokens=50, messages=[{"role": "user", "content": "Pick the single most shareable, gospel-rich line for a dashboard tile. Reply with just its number.\n\n" + listing}])
            i = int(re.search(r"\d+", m.content[0].text).group()); s, l = pool[i]
        except Exception: s, l = pool[0]  # noqa: E701
        feat = {"text": l["text"], "preacher": s["preacher"], "church": s["church"]}
    d = {"date": week, "region": REGION, "region_name": config.REGION_NAME, "feature": feat, "sermons": sermons}
    (week_dir(week) / "week.json").write_text(json.dumps(d, indent=1, ensure_ascii=False))
    dest = site / "scripts" / "sg-region" / "weeks" / f"{week}.json"
    dest.write_text(json.dumps({k: v for k, v in d.items()} | {"sermons": [{k: v for k, v in s.items() if k != "key"} for s in sermons]}, indent=2, ensure_ascii=False) + "\n")
    return dest


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("cmd", choices=["pages", "quotes", "dashboard", "all"])
    ap.add_argument("--week", required=True); ap.add_argument("--site", default=os.environ.get("SITE"))
    a = ap.parse_args(argv); site = Path(a.site) if a.site else None
    if a.cmd in ("pages", "all"): pages(a.week, site)
    if a.cmd in ("quotes", "dashboard", "all"):
        R = metrics(a.week)
        if a.cmd in ("quotes", "all"): Q = quotes(a.week, R)
        if a.cmd in ("dashboard", "all"): dashboard(a.week, R, site)
        if a.cmd == "all":
            week_json(a.week, R, Q, site)
            subprocess.run(["node", "scripts/sg-region/build.mjs"], cwd=site, check=True)


if __name__ == "__main__":
    main()
