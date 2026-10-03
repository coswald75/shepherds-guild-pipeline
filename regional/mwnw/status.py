"""Monday-night check: every church READY or MISSING, with the reason. --alert emails it to Chris."""
from __future__ import annotations
from datetime import datetime
from . import config
from .util import load_all, week_dir, alert, CT


def rows(week: str) -> list[dict]:
    st = load_all(week); out = []
    for ch in config.CHURCHES:
        c = st[ch["key"]]
        ready = c.get("status") == "READY"
        out.append(dict(key=ch["key"], church=f"{ch['church']} ({ch['city']}, {ch['state']})", status="READY" if ready else "MISSING",
                        title=c.get("title") or "", preacher=c.get("preacher") or (c.get("meta") or {}).get("preacher") or "",
                        source=(c.get("source") or {}).get("kind", ""),
                        reason="" if ready else (c.get("reason") or "not attempted yet (sermon not found in any source)"),
                        spend=c.get("spend_usd", 0)))
    return out


def status(week: str, alert_chris: bool = False) -> str:
    rs = rows(week)
    lines = [f"MWNW status for Sunday {week} at {datetime.now(CT):%a %b %-d %-I:%M %p} CT: "
             f"{sum(r['status'] == 'READY' for r in rs)}/{len(rs)} READY"]
    for r in rs:
        lines.append(f"  {r['status']:7}  {r['church']:48}  " + (f"{r['title']} — {r['preacher']} [{r['source']}]" if r["status"] == "READY" else r["reason"]))
    lines.append(f"  spend this week: ${sum(r['spend'] for r in rs):.2f}")
    text = "\n".join(lines)
    (week_dir(week) / "status.txt").write_text(text + "\n")
    print(text)
    if alert_chris:
        alert(f"Monday status {week}: {sum(r['status'] == 'READY' for r in rs)}/{len(rs)} READY", text)
    return text
