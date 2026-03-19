"""
Generate an HTML page listing all citations/quotations for a preacher,
organized by citation function type.

Usage:
  python generate_citations_page.py --preacher "Sinclair Ferguson"
  python generate_citations_page.py --preacher-id 90d60110-5f6b-4197-9c7d-21f72b3244a0
  python generate_citations_page.py --all          # generate for every preacher
"""

import os, sys, json, argparse, html
from supabase import create_client

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://twbunmbzyqcqzgffdrib.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
if not SUPABASE_KEY:
    from dotenv import load_dotenv
    load_dotenv(override=True)
    SUPABASE_KEY = os.environ["SUPABASE_KEY"]

sb = create_client(SUPABASE_URL, SUPABASE_KEY)
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "site")

FUNCTION_LABELS = {
    "authority":    ("Authority", "Cited to establish theological credibility or doctrinal weight"),
    "illustration": ("Illustration", "Cited to clarify or illuminate a point through example"),
    "devotional":   ("Devotional", "Cited to stir worship, affection, or spiritual reflection"),
    "opponent":     ("Opponent", "Cited as a foil — a position the preacher is arguing against"),
    "provocation":  ("Provocation", "Cited to challenge, unsettle, or press the hearer toward action"),
}
FUNCTION_ORDER = ["authority", "illustration", "devotional", "provocation", "opponent"]

CSS = """
:root {
  --ink: #1a1714; --parchment: #f7f3ee; --cream: #ede8e0;
  --warm-gray: #9e9688; --gold: #c4a265; --gold-dim: #a8894f;
  --gold-bright: #dbb978; --burgundy: #6b2d3e; --forest: #2d4a3e;
  --slate: #4a4640;
}
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'DM Sans',system-ui,sans-serif; background:var(--parchment); color:var(--ink); line-height:1.7; -webkit-font-smoothing:antialiased; }

.nav { position:sticky; top:0; z-index:100; background:rgba(247,243,238,0.94); backdrop-filter:blur(16px); border-bottom:1px solid rgba(196,162,101,0.15); padding:0 30px; }
.nav-inner { max-width:1160px; margin:0 auto; display:flex; align-items:center; justify-content:space-between; height:56px; }
.nav-brand { font-size:0.72rem; font-weight:600; letter-spacing:0.12em; text-transform:uppercase; color:var(--ink); text-decoration:none; }
.nav-brand span { color:var(--gold); }
.nav-links a { font-size:0.7rem; font-weight:500; letter-spacing:0.06em; text-transform:uppercase; color:var(--slate); text-decoration:none; padding:6px 12px; }

.header { background:var(--ink); color:var(--parchment); padding:64px 30px 56px; }
.header-inner { max-width:1160px; margin:0 auto; }
.header-eyebrow { font-size:0.63rem; font-weight:500; letter-spacing:0.2em; text-transform:uppercase; color:var(--gold); margin-bottom:12px; }
.header-title { font-family:'Cormorant Garamond',serif; font-size:clamp(2rem,4vw,3.2rem); font-weight:300; line-height:1.1; margin-bottom:8px; }
.header-title em { font-style:italic; color:var(--gold-bright); }
.header-sub { font-size:0.9rem; color:rgba(247,243,238,0.5); }
.header-stats { display:flex; gap:32px; margin-top:24px; }
.header-stat-val { font-family:'Cormorant Garamond',serif; font-size:1.8rem; font-weight:600; color:var(--gold-bright); }
.header-stat-label { font-size:0.6rem; font-weight:500; letter-spacing:0.15em; text-transform:uppercase; color:rgba(247,243,238,0.35); }

.body { max-width:1160px; margin:0 auto; padding:0 30px 120px; }

.section { padding:56px 0 0; }
.section-label { font-size:0.63rem; font-weight:600; letter-spacing:0.3em; text-transform:uppercase; color:var(--gold); margin-bottom:6px; }
.section-title { font-family:'Cormorant Garamond',serif; font-size:1.6rem; font-weight:400; margin-bottom:4px; }
.section-desc { font-size:0.82rem; color:var(--warm-gray); margin-bottom:28px; }
.section-count { font-family:'JetBrains Mono',monospace; font-size:0.7rem; color:var(--warm-gray); margin-bottom:20px; }

.quote-card { background:white; border:1px solid rgba(196,162,101,0.12); border-radius:12px; padding:24px 28px; margin-bottom:14px; box-shadow:0 2px 12px rgba(26,23,20,0.04); }
.quote-text { font-size:0.92rem; line-height:1.8; color:var(--ink); margin-bottom:10px; font-style:italic; }
.quote-text::before { content:open-quote; font-family:'Cormorant Garamond',serif; font-size:1.4rem; color:var(--gold); margin-right:2px; }
.quote-text::after { content:close-quote; font-family:'Cormorant Garamond',serif; font-size:1.4rem; color:var(--gold); margin-left:2px; }
.quote-meta { display:flex; align-items:baseline; gap:12px; flex-wrap:wrap; }
.quote-author { font-size:0.82rem; font-weight:600; color:var(--ink); }
.quote-source { font-size:0.78rem; color:var(--warm-gray); font-style:italic; }
.quote-sermon { font-size:0.72rem; color:var(--gold-dim); margin-left:auto; }

.divider { width:100%; height:1px; background:rgba(196,162,101,0.15); margin-top:48px; }

.empty { font-size:0.88rem; color:var(--warm-gray); font-style:italic; padding:20px 0; }

@media(max-width:768px) {
  .header { padding:40px 20px 36px; }
  .body { padding:0 20px 80px; }
  .quote-meta { flex-direction:column; gap:4px; }
  .quote-sermon { margin-left:0; }
}
"""


def get_preacher(name=None, pid=None):
    if pid:
        r = sb.table("preachers").select("id,name").eq("id", pid).execute()
    else:
        r = sb.table("preachers").select("id,name").ilike("name", f"%{name}%").execute()
    if not r.data:
        print(f"Preacher not found: {name or pid}")
        sys.exit(1)
    return r.data[0]


def get_quotes(preacher_id):
    """Get all quotations for sermons belonging to this preacher."""
    sermons = sb.table("sermons").select("id,title").eq("preacher_id", preacher_id).execute().data
    sermon_map = {s["id"]: s["title"] for s in sermons}

    all_quotes = []
    for sid in sermon_map:
        rows = sb.table("sermon_quotations").select("*").eq("sermon_id", sid).execute().data
        for row in rows:
            row["_sermon_title"] = sermon_map[sid]
        all_quotes.extend(rows)
    return all_quotes


def build_html(preacher_name, quotes):
    # Group by function
    grouped = {}
    for q in quotes:
        fn = q.get("function") or "uncategorized"
        grouped.setdefault(fn, []).append(q)

    # Stats
    total = len(quotes)
    unique_authors = len(set(q.get("attribution", "Unknown") for q in quotes))

    sections_html = ""
    for fn in FUNCTION_ORDER + [k for k in grouped if k not in FUNCTION_ORDER]:
        if fn not in grouped:
            continue
        items = grouped[fn]
        label, desc = FUNCTION_LABELS.get(fn, (fn.title(), ""))

        cards = ""
        # Sort by author then sermon
        items.sort(key=lambda q: (q.get("attribution", "").lower(), q.get("_sermon_title", "")))
        for q in items:
            text = html.escape(q.get("text", ""))
            author = html.escape(q.get("attribution", "Unknown"))
            source = html.escape(q.get("source", "") or "")
            sermon = html.escape(q.get("_sermon_title", ""))
            source_html = f'<span class="quote-source">{source}</span>' if source else ""
            cards += f"""
      <div class="quote-card">
        <div class="quote-text">{text}</div>
        <div class="quote-meta">
          <span class="quote-author">{author}</span>
          {source_html}
          <span class="quote-sermon">{sermon}</span>
        </div>
      </div>"""

        sections_html += f"""
    <div class="section">
      <div class="section-label">{html.escape(label)}</div>
      <div class="section-title">{html.escape(label)} Citations</div>
      <div class="section-desc">{html.escape(desc)}</div>
      <div class="section-count">{len(items)} citation{"s" if len(items)!=1 else ""}</div>
      {cards}
      <div class="divider"></div>
    </div>"""

    slug = preacher_name.lower().split()[-1]

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(preacher_name)} — Citations · Shepherd's Guild</title>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,300;0,400;0,500;0,600;1,400&family=DM+Sans:wght@300;400;500;600;700&family=JetBrains+Mono:wght@300;400;500&display=swap" rel="stylesheet">
<style>{CSS}</style>
</head>
<body>

<nav class="nav">
  <div class="nav-inner">
    <a href="index.html" class="nav-brand">SHEPHERD'S <span>GUILD</span></a>
    <div class="nav-links">
      <a href="index.html">The Hall</a>
      <a href="preacher-{html.escape(slug)}.html">← Back to Profile</a>
    </div>
  </div>
</nav>

<div class="header">
  <div class="header-inner">
    <div class="header-eyebrow">CITATION INDEX</div>
    <h1 class="header-title">{html.escape(preacher_name)} — <em>Every Citation</em></h1>
    <p class="header-sub">All quotations and citations extracted from the decomposed corpus, organized by rhetorical function.</p>
    <div class="header-stats">
      <div><div class="header-stat-val">{total}</div><div class="header-stat-label">TOTAL CITATIONS</div></div>
      <div><div class="header-stat-val">{unique_authors}</div><div class="header-stat-label">UNIQUE SOURCES</div></div>
      <div><div class="header-stat-val">{len(grouped)}</div><div class="header-stat-label">CATEGORIES</div></div>
    </div>
  </div>
</div>

<div class="body">
  {sections_html}
</div>

</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(description="Generate citation listing page for a preacher")
    parser.add_argument("--preacher", type=str, help="Preacher name (partial match)")
    parser.add_argument("--preacher-id", type=str, help="Preacher UUID")
    parser.add_argument("--all", action="store_true", help="Generate for all preachers")
    parser.add_argument("--out-dir", type=str, default=OUT_DIR, help="Output directory")
    args = parser.parse_args()

    if args.all:
        preachers = sb.table("preachers").select("id,name").execute().data
    elif args.preacher_id:
        preachers = [get_preacher(pid=args.preacher_id)]
    elif args.preacher:
        preachers = [get_preacher(name=args.preacher)]
    else:
        parser.print_help()
        sys.exit(1)

    for p in preachers:
        pid, name = p["id"], p["name"]
        print(f"Generating citations for {name}...")
        quotes = get_quotes(pid)
        if not quotes:
            print(f"  No citations found, skipping.")
            continue

        page_html = build_html(name, quotes)
        slug = name.lower().split()[-1]
        out_path = os.path.join(args.out_dir, f"citations-{slug}.html")
        with open(out_path, "w") as f:
            f.write(page_html)
        print(f"  {len(quotes)} citations → {out_path}")


if __name__ == "__main__":
    main()
