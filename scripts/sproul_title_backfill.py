#!/usr/bin/env python3
"""
Compare the R.C. Sproul sermon rows in Supabase against the re-scraped corpus
and report (or apply) metadata corrections.

The v1 scraper derived titles from a "## heading" inside the transcript body or
from the slug, so some rows carry a section heading rather than the title
Ligonier publishes. Dates and scripture references were already correct, so
this is a metadata-only update — no re-decomposition.

Usage:
  python3 scripts/sproul_title_backfill.py            # dry run
  python3 scripts/sproul_title_backfill.py --write    # apply
"""
import os, re, json, glob, argparse
from pathlib import Path

def norm_ref(ref):
    if not ref:
        return None
    r = ref.replace("–", "-").replace("—", "-").lower().strip()
    m = re.match(r"([1-3]?\s*[a-z]+)\s+(.+)", r)
    return (m.group(1).replace(" ", ""), m.group(2).replace(" ", "")) if m else (r, "")

def load_corpus():
    idx = {}
    for f in glob.glob("sermon-transcripts/rc-sproul/*.json"):
        if f.endswith("_index.json"):
            continue
        d = json.load(open(f, encoding="utf-8"))
        refs = d.get("bibleReferences") or []
        key = (d.get("date"), norm_ref(refs[0]["text"] if refs else None))
        idx[key] = d
    return idx

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--db", default="scripts/sproul_db_rows.json")
    args = ap.parse_args()

    corpus = load_corpus()
    rows = json.loads(Path(args.db).read_text(encoding="utf-8"))

    matched, unmatched, changes = 0, [], []
    for r in rows:
        key = (r["date"], norm_ref((r.get("primary_text") or "").split(",")[0]))
        d = corpus.get(key)
        if not d:
            unmatched.append(r)
            continue
        matched += 1
        diff = {}
        # Ligonier occasionally ships a doubled space in a title
        # ("The Parable  of the Barren Fig"); collapse runs of whitespace but
        # keep their wording verbatim otherwise.
        new_title = re.sub(r"\s+", " ", d["title"]).strip() if d.get("title") else None
        if new_title and new_title != r["title"]:
            diff["title"] = (r["title"], new_title)
        if d.get("sourceUrl"):
            diff.setdefault("_slug", (None, d["id"]))
        if diff.get("title"):
            changes.append((r["id"], d["id"], diff))

    print(f"db rows: {len(rows)}   matched to corpus: {matched}   unmatched: {len(unmatched)}")
    for r in unmatched:
        print("   UNMATCHED:", r["date"], r["primary_text"], "|", r["title"])

    print(f"\ntitle corrections needed: {len(changes)}\n")
    for sid, slug, diff in changes:
        old, new = diff["title"]
        print(f"  {slug}")
        print(f"     old: {old!r}")
        print(f"     new: {new!r}")

    if not args.write:
        print("\n(dry run — pass --write to apply)")
        return

    from dotenv import load_dotenv
    load_dotenv(".env")
    from supabase import create_client
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    for sid, slug, diff in changes:
        sb.table("sermons").update({"title": diff["title"][1]}).eq("id", sid).execute()
        print(f"  updated {slug} -> {diff['title'][1]!r}")
    print(f"\napplied {len(changes)} title updates")

if __name__ == "__main__":
    main()
