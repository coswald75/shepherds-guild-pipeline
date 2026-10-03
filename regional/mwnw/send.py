"""Per-church email drafts and the (locked) send step.

Mail goes through the pipeline's own path: Resend REST API with RESEND_API_KEY / RESEND_FROM
(as scripts/selfserve_ingest.py), PDF attached. NOT Gmail.

send() is a dry run unless ALL of these hold:
  1. --approve was passed on the command line;
  2. output/mwnw/<week>/APPROVED_BY_CHRIS.json exists and lists the church key (Chris's sign-off
     after reading the review packet; written by hand, never by this code);
  3. config.RECIPIENTS_ARE_BEST_GUESS is False (Chris has confirmed the addresses);
  4. the body has no placeholder left (P1 "[Chris writes opening paragraph ...]");
  5. the church is READY, its PDF exists, and every link in the email returns 200.
"""
from __future__ import annotations
import base64, html, json, os
from pathlib import Path
import requests
from . import config
from .util import week_dir, log, load_all, CT
from .report_pdf import page_url, dashboard_url

P2 = ("If you're curious how this works, or concerned about those notorious AI hallucinations, I'd invite you to look under the hood. "
      "The {glossary} explains every term the report uses and how we keep the AI tied to what was actually said in the sermon. "
      "You can also see how it handles preachers you already know, like a {spurgeon}, to judge the results for yourself.")
P3 = ("I'm sharing this because I think it can help us build one another up and grow a sense of camaraderie as we minister the gospel together. "
      "We'll also have access to each other's preaching, which I think could help in all kinds of ways. And to be upfront, I'm building this into "
      "a subscription business. If, after using it a while, you know other churches that would benefit, I'd really appreciate a referral. "
      "Just to be clear, this is a free service for you guys for at least the next year.")


def subject(c: dict) -> str:
    return f"Your sermon, stewarded: {c.get('title') or 'this Sunday'}"


def body_html(church: dict, c: dict, week: str, p1: str = config.P1_PLACEHOLDER) -> str:
    a = lambda href, text: f'<a href="{html.escape(href)}" style="color:#2d5a4a">{html.escape(text)}</a>'  # noqa: E731
    p2 = html.escape(P2).replace("{glossary}", a(config.GLOSSARY_URL, "glossary")).replace(
        "{spurgeon}", a(config.SPURGEON_URL, "Spurgeon sermon run through the same process"))
    links = (f'<p style="color:#6f6f80;font-size:14px">Your sermon page: {a(page_url(church, c["slug"]), page_url(church, c["slug"]))}<br>'
             f'This week across the region: {a(dashboard_url(week), dashboard_url(week))}<br>'
             f'The full report is attached as a PDF.</p>') if c.get("slug") else ""
    p1h = f'<p style="background:#fff3cd">{html.escape(p1)}</p>' if p1.startswith("[") else f"<p>{html.escape(p1)}</p>"
    return (f'<div style="font-family:Georgia,serif;font-size:16px;line-height:1.55;color:#1a1a2e;max-width:620px">'
            f'{p1h}<p>{p2}</p><p>{html.escape(P3)}</p>{links}<p>Grateful,<br>Chris</p></div>')


def build_drafts(week: str) -> list[Path]:
    out = []; states = load_all(week)
    for church in config.CHURCHES:
        c = states[church["key"]]; r = config.RECIPIENTS[church["key"]]
        d = week_dir(week) / church["key"]
        draft = {"to": r["to"], "to_is_best_guess": config.RECIPIENTS_ARE_BEST_GUESS, "pastor": r["pastor"], "basis": r["basis"],
                 "from": os.environ.get("RESEND_FROM", "(RESEND_FROM on the Studio)"), "subject": subject(c),
                 "attachment": c.get("pdf"), "status": c.get("status") or "MISSING", "html": body_html(church, c, week)}
        (d / "email_draft.json").write_text(json.dumps(draft, indent=1))
        (d / "email_draft.html").write_text(
            f'<p style="font-family:sans-serif;font-size:13px;color:#555">To: <b>{", ".join(r["to"])}</b> '
            f'<span style="background:#fff3cd">BEST GUESS: {html.escape(r["basis"])}</span><br>Subject: {html.escape(subject(c))}<br>'
            f'Attachment: {html.escape(Path(c["pdf"]).name) if c.get("pdf") else "(no PDF yet)"}</p><hr>{draft["html"]}')
        out.append(d / "email_draft.html")
    return out


def verify_links(urls: list[str]) -> dict:
    res = {}
    for u in urls:
        try: res[u] = requests.get(u, timeout=20, allow_redirects=True, headers={"User-Agent": config.UA}).status_code
        except Exception as e: res[u] = str(e)[:80]  # noqa: E701
    return res


def send(week: str, *, approve: bool = False, only: list[str] | None = None) -> None:
    build_drafts(week)
    appr_path = week_dir(week) / "APPROVED_BY_CHRIS.json"
    approved = set(json.loads(appr_path.read_text()).get("approved", [])) if appr_path.exists() else set()
    states = load_all(week)
    key, sender = os.environ.get("RESEND_API_KEY"), os.environ.get("RESEND_FROM")
    for church in config.CHURCHES:
        k = church["key"]
        if only and k not in only: continue
        c = states[k]; draft = json.loads((week_dir(week) / k / "email_draft.json").read_text())
        blockers = []
        if (week_dir(week) / k / "sent.json").exists(): blockers.append("already sent (sent.json exists)")
        if not approve: blockers.append("no --approve flag")
        if k not in approved: blockers.append(f"not in {appr_path.name}")
        if config.RECIPIENTS_ARE_BEST_GUESS: blockers.append("recipients are best guesses (Chris to confirm)")
        if config.P1_PLACEHOLDER in draft["html"] or "[Chris" in draft["html"]: blockers.append("P1 placeholder still in body")
        if c.get("status") != "READY" or not c.get("pdf") or not Path(c["pdf"]).exists(): blockers.append("church not READY / no PDF")
        if not (key and sender): blockers.append("RESEND_API_KEY/RESEND_FROM not set on this machine")
        if not blockers:
            bad = {u: s for u, s in verify_links([config.GLOSSARY_URL, config.SPURGEON_URL, page_url(church, c["slug"]), dashboard_url(week)]).items() if s != 200}
            if bad: blockers.append(f"links not 200: {bad}")
        if blockers:
            log.info(f"NOT SENDING {k} -> {draft['to']}: " + "; ".join(blockers)); continue
        pdf = Path(c["pdf"])
        r = requests.post("https://api.resend.com/emails", timeout=60,
                          headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                          json={"from": sender, "to": draft["to"], "subject": draft["subject"], "html": draft["html"],
                                "attachments": [{"filename": pdf.name, "content": base64.b64encode(pdf.read_bytes()).decode()}]})
        if r.status_code >= 300: log.error(f"{k}: Resend {r.status_code}: {r.text[:300]}"); continue
        st_path = week_dir(week) / k / "sent.json"
        st_path.write_text(json.dumps({"to": draft["to"], "id": r.json().get("id"), "at": __import__("datetime").datetime.now(CT).isoformat()}))
        log.info(f"SENT {k} -> {draft['to']} ({r.json().get('id')})")
