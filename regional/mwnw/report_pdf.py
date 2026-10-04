"""Regional sermon report PDF (the one emailed to each church's staff).

Built on scripts/generate_sermon_report.py (same analysis prompt, resource renderers, and
Playwright PDF step) with a regional cover and context. Differences from the pipeline report:
  + cover names the region and the week; at-a-glance strip (minutes, primary text, Scripture refs)
  + main-thesis box; "lines worth repeating" (the preacher's own words, from How We Said It)
  + links: this sermon's page, the regional dashboard for the week
  + footer pointing to replies and "Suggest a change" (permission/opt-out live in the email, P1)
  - no pricing (MWNW churches are free for at least a year)
  - the sample article in the pastor's voice is OFF by default (config.INCLUDE_SAMPLE_ARTICLE)
The model analysis is cached in output/mwnw/<week>/<key>/analysis.json so re-rendering is free."""
from __future__ import annotations
import json
from datetime import date, datetime
from pathlib import Path
from jinja2 import Template
from . import config
from .util import week_dir, week_slug, log

import generate_sermon_report as gsr  # scripts/ is on sys.path (util)


def page_url(church: dict, slug: str) -> str:
    if church.get("public"): return f"{config.SITE}/ProvidenceLenexa/sermons/{slug}"
    return f"{config.SITE}/SGchurch/{church['dir']}/sermons/{slug}"


def church_url(church: dict) -> str:
    return f"{config.SITE}/SGchurch/{church['dir']}/"


def dashboard_url(week: str) -> str:
    return f"{config.SITE}/SGchurch/{config.REGION}/{week_slug(week)}/"


def _own_lines(week: str, church: dict) -> list[str]:
    """Up to 3 of the preacher's own lines, if the week's How We Said It data exists."""
    p = week_dir(week) / "week.json"
    if not p.exists(): return []
    for s in json.loads(p.read_text()).get("sermons", []):
        if s.get("key") == church["key"]: return [l["text"] for l in s.get("lines", [])][:3]
    return []


def _glance(sb, sid: str) -> dict:
    units = sb.table("units").select("id").eq("sermon_id", sid).execute().data or []
    ids = [u["id"] for u in units]; refs = 0
    for i in range(0, len(ids), 50):
        refs += len(sb.table("citations").select("id").in_("unit_id", ids[i:i + 50]).execute().data or [])
    row = sb.table("sermons").select("audio_duration_seconds").eq("id", sid).single().execute().data
    return {"units": len(ids), "refs": refs, "minutes": round((row.get("audio_duration_seconds") or 0) / 60)}


TEMPLATE = Template(open(Path(__file__).with_name("report_template.html")).read())


def build(week: str, church: dict, sid: str, *, dry: bool = False, sample_article: bool | None = None) -> Path:
    sample_article = config.INCLUDE_SAMPLE_ARTICLE if sample_article is None else sample_article
    d = week_dir(week) / church["key"]; d.mkdir(exist_ok=True)
    sb = gsr._supabase()
    sermon = gsr.load_sermon(sb, sid); units = gsr.load_units(sb, sid)
    artifacts = gsr.load_artifacts(sb, sid); decomp = gsr.load_decomposed(sid)
    preacher = (sermon.get("preachers") or {}).get("name") or "—"
    facts = gsr.build_facts(sermon, units, decomp)
    cache = d / "analysis.json"
    if cache.exists(): analysis = json.loads(cache.read_text())
    else:
        analysis = gsr.generate_analysis(gsr._anthropic(), gsr.DEFAULT_MODEL, facts); cache.write_text(json.dumps(analysis, indent=1))
    sample = None
    if sample_article:
        sc = d / "sample_article.json"
        if sc.exists(): sample = json.loads(sc.read_text())
        else:
            sample = gsr.generate_sample_article(gsr._anthropic(), gsr.DEFAULT_MODEL, facts, gsr.load_voice(sermon.get("preacher_id")),
                                                 analysis["article_pitches"][0], preacher)
            sc.write_text(json.dumps(sample, indent=1))
    resources = [{"label": gsr.ARTIFACT_LABELS.get(t, t), "html": gsr.render_resource(t, artifacts.get(t, {}))}
                 for t in gsr.ARTIFACT_ORDER if t in artifacts]
    html = TEMPLATE.render(
        sermon=sermon, preacher=preacher, church=church, region=config.REGION_NAME,
        week_h=date.fromisoformat(week).strftime("%B %-d, %Y"), date_h=gsr.fmt_date(sermon.get("date")),
        thesis=sermon.get("main_thesis") or (decomp or {}).get("main_thesis"), glance=_glance(sb, sid),
        analysis=analysis, lines=_own_lines(week, church),
        sample=sample, sample_html=gsr.md_to_html(sample.get("body_markdown", "")) if sample else "",
        resources=resources, page_url=page_url(church, sermon["slug"]), dashboard_url=dashboard_url(week),
        generated=datetime.now().strftime("%B %-d, %Y"),
    )
    out = d / f"{church['dir']}-{sermon['slug']}.pdf"
    (d / "report.html").write_text(html)
    gsr.html_to_pdf(html, out)
    log.info(f"{church['key']}: PDF {out}")
    return out
