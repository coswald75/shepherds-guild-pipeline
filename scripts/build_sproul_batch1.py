#!/usr/bin/env python3
"""
Assemble a deliberately-composed pilot batch of R.C. Sproul sermons.

Batch 1 is a quality-review batch, not a random sample: it is stratified so a
single read-through exercises the decomposition across the dimensions most
likely to break — transcript length extremes, multi-part series context,
topical vs expositional preaching, and the Luke run that is already in the
corpus and can therefore be compared against.

Sermons already ingested are excluded by (date, scripture) rather than title:
the v1 scraper recorded transcript section headings as titles, so titles in
Supabase do not match the titles Ligonier publishes.

Usage:
  python3 scripts/build_sproul_batch1.py --size 25
  python3 scripts/build_sproul_batch1.py --size 25 --write
"""

import re
import json
import shutil
import argparse
from pathlib import Path

SRC = Path("sermon-transcripts/rc-sproul")
DEST = Path("sermon-transcripts/rc-sproul-batch1")

BOOKS = [
    "genesis", "exodus", "psalm", "isaiah", "daniel", "matthew", "mark", "luke",
    "john", "acts", "romans", "corinthians", "galatians", "ephesians",
    "philippians", "colossians", "thessalonians", "timothy", "titus", "hebrews",
    "james", "peter", "jude", "revelation",
]


def load_corpus():
    out = []
    for f in sorted(SRC.glob("*.json")):
        if f.name == "_index.json":
            continue
        d = json.loads(f.read_text(encoding="utf-8"))
        if not d.get("transcript"):
            continue
        refs = d.get("bibleReferences") or []
        out.append({
            "path": f,
            "slug": d["id"],
            "title": d.get("title"),
            "date": d.get("date"),
            "ref": (refs[0]["text"] if refs else None),
            "chars": len(d["transcript"]),
        })
    return out


def norm_ref(ref):
    """'Luke 9:27–36' -> ('luke', '9:27-36') for comparison across dash styles."""
    if not ref:
        return None
    r = ref.replace("–", "-").replace("—", "-").lower().strip()
    m = re.match(r"([1-3]?\s*[a-z]+)\s+(.+)", r)
    return (m.group(1).replace(" ", ""), m.group(2).replace(" ", "")) if m else (r, "")


def pick(pool, taken, n, keyfn=None, reverse=False, label=""):
    cand = [s for s in pool if s["slug"] not in taken]
    if keyfn:
        cand = sorted(cand, key=keyfn, reverse=reverse)
    chosen = cand[:n]
    for s in chosen:
        taken.add(s["slug"])
        s["why"] = label
    return chosen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=25)
    ap.add_argument("--write", action="store_true", help="copy files into the batch folder")
    ap.add_argument("--ingested", default="scripts/sproul_ingested.json",
                    help="JSON list of {date, primary_text} already in Supabase")
    args = ap.parse_args()

    corpus = load_corpus()
    print(f"corpus with transcripts: {len(corpus)}")

    # Supabase stores compound references such as "Luke 22:1-6, 47-53" where the
    # page publishes only the primary range, so compare against the segment
    # before the first comma. Matching on book alone is too loose — it collides
    # with same-day Part 1 / Part 2 pairs that cover overlapping passages.
    ingested = set()
    p = Path(args.ingested)
    if p.exists():
        for row in json.loads(p.read_text(encoding="utf-8")):
            ref = row.get("primary_text") or ""
            ingested.add((row.get("date"), norm_ref(ref.split(",")[0])))

    fresh = [s for s in corpus
             if (s["date"], norm_ref(s["ref"])) not in ingested]
    print(f"already ingested: {len(corpus) - len(fresh)}   available: {len(fresh)}")

    taken, batch = set(), []
    n = args.size
    batch += pick(fresh, taken, 3, lambda s: s["chars"], True,  "longest transcript")
    batch += pick(fresh, taken, 3, lambda s: s["chars"], False, "shortest transcript")

    series = [s for s in fresh if re.search(r"part-\d", s["slug"])]
    batch += pick(series, taken, 4, lambda s: s["slug"], False, "multi-part series")

    topical = [s for s in fresh if not any(b in s["slug"] for b in BOOKS)]
    batch += pick(topical, taken, 4, lambda s: s["slug"], False, "topical (no book in slug)")

    luke = [s for s in fresh if s["ref"] and s["ref"].lower().startswith("luke")]
    batch += pick(luke, taken, 5, lambda s: s["date"] or "", False, "Luke — comparable to existing 43")

    remaining = n - len(batch)
    if remaining > 0:
        rest = sorted((s for s in fresh if s["slug"] not in taken),
                      key=lambda s: s["date"] or "")
        step = max(1, len(rest) // remaining)
        batch += pick([rest[i] for i in range(0, len(rest), step)][:remaining],
                      taken, remaining, None, False, "date-spread")

    batch = batch[:n]
    print(f"\nbatch 1 — {len(batch)} sermons\n")
    print(f"{'date':<12}{'chars':>7}  {'scripture':<22}{'title':<40}why")
    print("-" * 118)
    for s in sorted(batch, key=lambda s: (s["why"], s["date"] or "")):
        print(f"{s['date'] or '—':<12}{s['chars']:>7}  {(s['ref'] or '—'):<22}"
              f"{(s['title'] or '')[:38]:<40}{s['why']}")

    tot = sum(s["chars"] for s in batch)
    print(f"\ntotal {tot:,} chars | median {sorted(x['chars'] for x in batch)[len(batch)//2]:,}")

    if args.write:
        if DEST.exists():
            shutil.rmtree(DEST)
        DEST.mkdir(parents=True)
        for s in batch:
            shutil.copy2(s["path"], DEST / s["path"].name)
        (DEST / "_batch1_manifest.json").write_text(json.dumps(
            [{k: v for k, v in s.items() if k != "path"} for s in batch],
            indent=2), encoding="utf-8")
        print(f"\nwrote {len(batch)} files -> {DEST}")
    else:
        print("\n(dry run — pass --write to create the batch folder)")


if __name__ == "__main__":
    main()
