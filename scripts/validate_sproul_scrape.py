#!/usr/bin/env python3
"""Sanity-check the re-scraped R.C. Sproul corpus before it feeds a batch."""
import json, re
from pathlib import Path
from collections import Counter

SRC = Path("sermon-transcripts/rc-sproul")
NOTX = SRC / "_no_transcript"
DEATH = "2017-12-14"   # Sproul died; any later date is a scrape artifact

def load(d):
    for f in sorted(d.glob("*.json")):
        if f.name.startswith("_"):
            continue
        yield f, json.loads(f.read_text(encoding="utf-8"))

def main():
    tx  = list(load(SRC))
    ntx = list(load(NOTX)) if NOTX.exists() else []
    all_ = tx + ntx
    print(f"with transcript : {len(tx)}")
    print(f"no transcript   : {len(ntx)}")
    print(f"total           : {len(all_)}\n")

    fails = []
    v1 = [f.name for f, d in all_ if d.get("schemaVersion") != 2]
    if v1: fails.append(f"{len(v1)} records still on v1 schema: {v1[:3]}")

    nodate = [d["id"] for _, d in all_ if not d.get("date")]
    future = [(d["id"], d["date"]) for _, d in all_ if d.get("date") and d["date"] > DEATH]
    if future: fails.append(f"{len(future)} dated after Sproul's death: {future[:3]}")

    uniq = Counter(d.get("date") for _, d in all_ if d.get("date"))
    if uniq and uniq.most_common(1)[0][1] > 15:
        fails.append(f"suspicious date clustering: {uniq.most_common(3)}")

    untitled = [d["id"] for _, d in all_ if not d.get("titleResolved")]
    noref    = [d["id"] for _, d in all_ if not d.get("bibleReferences")]
    noaudio  = [d["id"] for _, d in all_ if not d.get("audioUrl")]
    dupes    = [s for s, c in Counter(d["id"] for _, d in all_).items() if c > 1]
    if dupes: fails.append(f"duplicate slugs: {dupes[:5]}")

    # transcripts should be plain text now, not HTML
    html = [d["id"] for _, d in tx if re.search(r"<p[ >]|<div", d.get("transcript") or "")]
    if html: fails.append(f"{len(html)} transcripts still contain HTML: {html[:3]}")

    print(f"date missing        : {len(nodate)}")
    print(f"date after 2017-12  : {len(future)}")
    print(f"title unresolved    : {len(untitled)}")
    print(f"no scripture ref    : {len(noref)}")
    print(f"no audio url        : {len(noaudio)}")
    if uniq:
        yrs = Counter(d["date"][:4] for _, d in all_ if d.get("date"))
        print(f"date range          : {min(uniq)} … {max(uniq)}")
        print(f"years               : {dict(sorted(yrs.items()))}")

    lens = sorted(len(d["transcript"]) for _, d in tx)
    if lens:
        print(f"transcript chars    : min {lens[0]:,} median {lens[len(lens)//2]:,} max {lens[-1]:,}")

    print()
    if fails:
        print("FAIL")
        for f in fails: print("  ✗", f)
        return 1
    print("PASS — corpus looks clean")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
