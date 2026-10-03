"""MWNW launch CLI.   python -m regional.mwnw <command> [--week YYYY-MM-DD]

  tick      poller entry point (launchd, every 15 min). Inside the week's window (Sun 11:00 CT to
            Tue 08:00 CT) it starts ONE separate process per church that isn't READY yet. Each church
            ingests on its own as soon as its sermon shows up; nobody waits for anybody.
  church K  process one church now (what tick spawns). --dry: stop before any paid call / DB write.
  status    READY / MISSING table with reasons (Monday-night check). --alert emails it to Chris.
  review    build the review packet (HTML) for Chris.
  drafts    build each church's email draft (HTML) - nothing is sent.
  send      send the drafts through Resend. REFUSES unless --approve AND Chris's approval file exists
            AND no placeholder recipients/wording remain. Default is a dry run that prints what it would do.
"""
from __future__ import annotations
import argparse, os, subprocess, sys
from datetime import datetime, timedelta, date
from .util import CT, REPO, default_week, log, week_dir, State, run_label
from . import config


def in_window(week: str, now=None) -> bool:
    now = now or datetime.now(CT); d = date.fromisoformat(week)
    start = datetime(d.year, d.month, d.day, 11, 0, tzinfo=CT)
    return start <= now <= start + timedelta(days=1, hours=21)   # Tue 08:00 CT


def tick(week: str, force=False):
    if not force and not in_window(week):
        log.info(f"outside the {week} window; nothing to do"); return
    logs = REPO / "logs"; logs.mkdir(exist_ok=True)
    for c in config.CHURCHES:
        st = State(week, c["key"]).data
        if st.get("status") == "READY": continue
        if st.get("attempts", 0) >= int(os.environ.get("MWNW_MAX_ATTEMPTS", "200")): continue
        out = open(logs / f"mwnw-{week}-{c['key']}.log", "a")
        subprocess.Popen([sys.executable, "-m", "regional.mwnw", "church", c["key"], "--week", week], cwd=REPO,
                         stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
        log.info(f"started {c['key']}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="regional.mwnw", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["tick", "church", "status", "review", "drafts", "send"])
    ap.add_argument("key", nargs="?")
    ap.add_argument("--week", default=None)
    ap.add_argument("--run", choices=["sunday", "monday"], default=None)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--alert", action="store_true")
    ap.add_argument("--approve", action="store_true")
    ap.add_argument("--only", default=None, help="comma-separated church keys (send)")
    a = ap.parse_args(argv)
    week = a.week or default_week()
    if a.cmd == "tick": return tick(week, a.force)
    if a.cmd == "church":
        from .process import run_one
        c = run_one(week, a.key, a.run, dry=a.dry); print(c.get("status"), c.get("reason") or "")
        return
    if a.cmd == "status":
        from .status import status
        return status(week, alert_chris=a.alert)
    if a.cmd == "review":
        from .review import build_review
        print(build_review(week)); return
    if a.cmd == "drafts":
        from .send import build_drafts
        for p in build_drafts(week): print(p)
        return
    if a.cmd == "send":
        from .send import send
        return send(week, approve=a.approve, only=a.only.split(",") if a.only else None)


if __name__ == "__main__":
    main()
