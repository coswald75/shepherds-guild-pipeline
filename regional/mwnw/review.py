"""Review packet for Chris (nothing goes to a church until he approves).
output/mwnw/<week>/review/index.html + the PDFs, clips and email drafts beside it, so the folder can
be zipped, opened locally, or put on a preview URL. One card per church: status, title, preacher
(and how we know), source, livestream cut times with first/last sentence and a playable clip (local
MP3 + the YouTube link that starts at the cut), church page, PDF, and the email draft."""
from __future__ import annotations
import html, json, os, shutil
from datetime import datetime
from pathlib import Path
from . import config
from .util import load_all, week_dir, week_slug, CT
from .report_pdf import page_url, dashboard_url
from .send import build_drafts

E = lambda s: html.escape(str(s or ""))  # noqa: E731
PREVIEW = os.environ.get("MWNW_PREVIEW_BASE", "")   # e.g. https://sg-midwest-sermon-steward.<acct>.workers.dev


def _site(url: str) -> str:
    return url.replace(config.SITE, PREVIEW) if PREVIEW else url


def build_review(week: str) -> Path:
    build_drafts(week)
    out = week_dir(week) / "review"; out.mkdir(exist_ok=True); (out / "files").mkdir(exist_ok=True)
    states = load_all(week); cards = []; n_ready = 0
    for ch in config.CHURCHES:
        k = ch["key"]; c = states[k]; ready = c.get("status") == "READY"; n_ready += ready
        src = c.get("source") or {}; meta = c.get("meta") or {}; cut = c.get("cut") or {}
        rows = [("Sermon", f"<b>{E(c.get('title'))}</b>" if c.get("title") else "—"),
                ("Preacher", E(c.get("preacher") or meta.get("preacher") or "—") + (f' <span class="tag warn">{E(meta.get("preacher_basis"))}</span>' if "VERIFY" in (meta.get("preacher_basis") or "") else "")
                 + (' <span class="tag">guest</span>' if meta.get("guest") else ""))]
        if src.get("kind") == "youtube":
            rows.append(("Source", f'YouTube livestream, sermon cut out: <a href="{E(src.get("url"))}">{E(src.get("title"))}</a>'))
        elif src.get("kind") == "pipeline":
            rows.append(("Source", "Providence weekly pipeline (iMac); not re-processed"))
        elif src:
            rows.append(("Source", f'{E(src.get("kind"))}: <a href="{E(src.get("audio_url"))}">audio</a>' + (f' · <a href="{E(src.get("page_url"))}">page</a>' if src.get("page_url") else "")))
        if cut:
            s0 = int(cut["start_ms"] // 1000)
            clip_html = ""
            if cut.get("clip") and Path(cut["clip"]).exists():
                dst = out / "files" / Path(cut["clip"]).name; shutil.copy(cut["clip"], dst)
                clip_html = f'<audio controls preload="none" src="files/{E(dst.name)}"></audio><br>'
            rows.append(("Cut", f'{E(cut.get("start"))} → {E(cut.get("end"))} of the livestream ({E(cut.get("minutes"))} min) · '
                                f'<a href="https://www.youtube.com/watch?v={E(src.get("yt_id"))}&t={s0}s">play from the cut on YouTube</a>'
                                f'<br>{clip_html}<span class="q">First: “{E(cut.get("first_sentence"))}”</span><br>'
                                f'<span class="q">Last: “{E(cut.get("last_sentence"))}”</span>'
                                f'<br><span class="hint">Check the start: in the Sep 27 test the starts ranged from 41 s early to 68 s late; ends were within 3 s.</span>'))
        elif c.get("first_sentence"):
            rows.append(("Transcript", f'<span class="q">First: “{E(c.get("first_sentence"))}”</span><br><span class="q">Last: “{E(c.get("last_sentence"))}”</span>'))
        if c.get("slug"):
            rows.append(("Church page", f'<a href="{E(_site(page_url(ch, c["slug"])))}">{E(page_url(ch, c["slug"]).replace(config.SITE, ""))}</a>'))
        if c.get("pdf") and Path(c["pdf"]).exists():
            dst = out / "files" / Path(c["pdf"]).name; shutil.copy(c["pdf"], dst)
            rows.append(("PDF", f'<a href="files/{E(dst.name)}">{E(dst.name)}</a>'))
        dr = week_dir(week) / k / "email_draft.html"
        if dr.exists():
            shutil.copy(dr, out / "files" / f"{k}-email.html")
            r = config.RECIPIENTS[k]
            rows.append(("Email draft", f'<a href="files/{k}-email.html">open draft</a> · to {E(", ".join(r["to"]))} '
                                        f'<span class="tag warn">best guess</span> <span class="hint">{E(r["basis"])}</span>'))
        if not ready:
            rows.append(("Why missing", f'<span class="miss">{E(c.get("reason") or "not found yet")}</span>'))
        body = "".join(f"<tr><th>{a}</th><td>{b}</td></tr>" for a, b in rows)
        cards.append(f'<section class="card"><h2>{E(ch["church"])} <span class="city">{E(ch["city"])}, {E(ch["state"])}</span>'
                     f'<span class="st {"ok" if ready else "no"}">{"READY" if ready else "MISSING"}</span></h2><table>{body}</table>'
                     f'<label class="ap"><input type="checkbox" data-k="{k}"> Approve {E(ch["city"])}</label></section>')
    page = f"""<!doctype html><html><head><meta charset="utf-8"><meta name="robots" content="noindex,nofollow">
<title>MWNW review packet · {week_slug(week)}</title><style>
body{{font-family:Inter,system-ui,-apple-system,Segoe UI,sans-serif;background:#f6f3ee;color:#1a1a2e;margin:0;padding:24px}}
.wrap{{max-width:980px;margin:0 auto}} h1{{font-family:Georgia,serif;margin:0 0 4px}} .sub{{color:#6f6f80;margin-bottom:18px}}
.card{{background:#fff;border:1px solid #e4e0d8;border-radius:10px;padding:14px 18px;margin:0 0 14px}}
.card h2{{font-family:Georgia,serif;font-size:20px;margin:0 0 8px;display:flex;gap:10px;align-items:center}} .city{{color:#6f6f80;font-size:14px;font-family:Inter,sans-serif}}
.st{{margin-left:auto;font-size:12px;font-weight:700;padding:3px 10px;border-radius:20px;font-family:Inter,sans-serif}} .ok{{background:#d8efe2;color:#1d6b40}} .no{{background:#f8dcdc;color:#9b1c1c}}
table{{border-collapse:collapse;width:100%;font-size:14px}} th{{text-align:left;vertical-align:top;color:#6f6f80;font-weight:600;width:120px;padding:5px 8px 5px 0}} td{{padding:5px 0}}
a{{color:#2d5a4a}} .q{{font-family:Georgia,serif;font-style:italic}} .hint{{color:#8a8a99;font-size:12px}} .miss{{color:#9b1c1c}}
.tag{{font-size:11px;background:#efeae1;border-radius:10px;padding:1px 7px}} .warn{{background:#fff3cd;color:#7a5a00}} audio{{width:100%;max-width:520px;margin:6px 0}}
.ap{{display:block;margin-top:8px;font-size:14px;font-weight:600}} .box{{background:#fff;border:1px solid #e4e0d8;border-radius:10px;padding:12px 18px;margin-bottom:16px;font-size:14px}}
code{{background:#efeae1;padding:1px 5px;border-radius:4px}}</style></head><body><div class="wrap">
<h1>Sovereign Grace Midwest/Northwest · review packet</h1>
<div class="sub">Sunday {week} · built {datetime.now(CT):%a %b %-d, %-I:%M %p} CT · {n_ready}/{len(config.CHURCHES)} READY ·
dashboard (after publish): <a href="{E(_site(dashboard_url(week)))}">{E(dashboard_url(week).replace(config.SITE, ""))}</a></div>
<div class="box"><b>Nothing has been sent.</b> Tick the churches you approve, then copy the line below back to us. Recipients are best guesses
from each church's website. Paragraph 1 of every email is yours to write (permission and opt-out).<br>
<code id="ap">{{"approved": []}}</code></div>
{''.join(cards)}
<script>document.querySelectorAll('input[data-k]').forEach(b=>b.addEventListener('change',()=>{{
document.getElementById('ap').textContent=JSON.stringify({{approved:[...document.querySelectorAll('input[data-k]:checked')].map(x=>x.dataset.k)}})}}));</script>
</div></body></html>"""
    (out / "index.html").write_text(page)
    return out / "index.html"
