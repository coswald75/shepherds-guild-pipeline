"""
Migrate biblical quotations from the `quotations` table to the `citations` table (tier 2).

The decomp model sometimes places biblical speech acts (Jesus, Paul, prophets, God)
into quotations instead of cross_references. This script identifies them and migrates.

Usage:
  python migrate_biblical_quotations.py --dry-run    # preview what would move
  python migrate_biblical_quotations.py --execute     # actually migrate
"""

import os, sys, re, json, argparse
from supabase import create_client
from dotenv import load_dotenv

load_dotenv(override=True)
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://twbunmbzyqcqzgffdrib.supabase.co")
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
sb = create_client(SUPABASE_URL, SUPABASE_KEY)

# ── Biblical speaker detection ──────────────────────────────────────────────
BIBLICAL_SPEAKERS = {
    "jesus", "jesus christ", "christ", "the lord jesus", "lord jesus",
    "paul", "apostle paul", "the apostle paul", "st. paul", "st paul",
    "peter", "apostle peter", "the apostle peter", "simon peter", "st. peter", "st peter",
    "moses", "david", "king david", "solomon", "king solomon",
    "isaiah", "jeremiah", "ezekiel", "daniel", "hosea", "joel", "amos",
    "obadiah", "jonah", "micah", "nahum", "habakkuk", "zephaniah",
    "haggai", "zechariah", "malachi",
    "god", "god the father", "the lord", "yahweh", "the almighty",
    "holy spirit", "the holy spirit",
    "john the baptist", "john the apostle",
    "james", "jude",  # only when source is biblical
    "simeon", "anna", "mary", "martha",
    "abraham", "jacob", "isaac", "joseph",
    "job", "ruth", "esther", "nehemiah", "ezra",
    "psalmist", "the psalmist", "a psalmist",
}

# Names that are ambiguous — only biblical if source looks biblical
AMBIGUOUS_SPEAKERS = {
    "james", "jude", "john", "simeon", "joseph", "mark", "luke", "matthew",
}

BIBLE_BOOKS = [
    "genesis", "exodus", "leviticus", "numbers", "deuteronomy",
    "joshua", "judges", "ruth", "1 samuel", "2 samuel",
    "1 kings", "2 kings", "1 chronicles", "2 chronicles",
    "ezra", "nehemiah", "esther", "job", "psalm", "psalms",
    "proverbs", "ecclesiastes", "song of solomon", "song of songs",
    "isaiah", "jeremiah", "lamentations", "ezekiel", "daniel",
    "hosea", "joel", "amos", "obadiah", "jonah", "micah",
    "nahum", "habakkuk", "zephaniah", "haggai", "zechariah", "malachi",
    "matthew", "mark", "luke", "john", "acts",
    "romans", "1 corinthians", "2 corinthians", "galatians",
    "ephesians", "philippians", "colossians",
    "1 thessalonians", "2 thessalonians",
    "1 timothy", "2 timothy", "titus", "philemon",
    "hebrews", "james", "1 peter", "2 peter",
    "1 john", "2 john", "3 john", "jude", "revelation",
]

# Patterns that indicate a biblical source
VERSE_RE = re.compile(r'\b\d+:\d+')
PARAPHRASE_RE = re.compile(r'paraphrase', re.IGNORECASE)


def is_biblical(quotation):
    """Determine if a quotation is actually a biblical citation."""
    attr = (quotation.get("attribution") or "").strip().lower()
    src = (quotation.get("source") or "").strip().lower()
    text = (quotation.get("text") or "").strip().lower()

    # Direct biblical speaker match (non-ambiguous)
    if attr in BIBLICAL_SPEAKERS and attr not in AMBIGUOUS_SPEAKERS:
        return True

    # Check if source references a Bible book
    source_is_biblical = any(book in src for book in BIBLE_BOOKS)
    source_has_verse_ref = bool(VERSE_RE.search(src))
    source_has_paraphrase = bool(PARAPHRASE_RE.search(src))

    # Ambiguous speaker + biblical source = biblical
    if attr in AMBIGUOUS_SPEAKERS and (source_is_biblical or source_has_verse_ref):
        return True

    # Known non-biblical human authors — even if their source mentions a Bible book
    # (e.g., C.S. Lewis "Reflections on the Psalms", Luther "exposition of Psalm 147")
    non_biblical_indicators = [
        "luther", "calvin", "owen", "spurgeon", "edwards", "wesley", "whitefield",
        "bunyan", "baxter", "flavel", "sibbes", "watson", "brooks", "packer",
        "stott", "lloyd-jones", "lloyd jones", "schaeffer", "lewis", "c.s. lewis",
        "chesterton", "tozer", "bonhoeffer", "keller", "carson", "don carson",
        "d.a. carson", "piper", "macarthur", "sproul", "r.c. sproul", "grudem",
        "mohler", "dever", "deyoung", "mahaney", "ferguson", "sinclair ferguson",
        "boice", "robinson", "haddon robinson", "baucham", "voddie",
        "augustine", "aquinas", "athanasius", "anselm", "irenaeus", "chrysostom",
        "origen", "tertullian", "cyprian", "ambrose", "jerome", "gregory",
        "bernard", "knox", "zwingli", "cranmer", "tyndale", "wycliffe",
        "warfield", "hodge", "machen", "murray", "ryle", "j.c. ryle",
        "pink", "a.w. pink", "a.w. tozer", "ravenhill", "chambers",
        "müller", "muller", "george muller", "george müller",
        "hymn", "hymnal", "unknown hymn", "hymnist", "hymnwriter",
        "tolkien", "dostoevsky", "kierkegaard", "pascal", "nietzsche",
        "plato", "aristotle", "seneca", "cicero",
        "kauflin", "bob kauflin", "newton", "john newton",
        "bridges", "jerry bridges", "helm", "david helm",
        "supreme court", "foucault", "marx", "freud", "darwin",
        "morgan", "g. campbell morgan", "campbell morgan",
    ]
    if any(nba in attr for nba in non_biblical_indicators):
        return False

    # Any speaker + clearly biblical source
    if source_is_biblical or source_has_verse_ref:
        # But exclude real human authors whose source just mentions a Bible book
        # e.g., "Don Carson | Commentary on the book of Matthew" is NOT biblical
        if any(w in src for w in ["commentary", "sermon", "letter", "preface",
                                    "exposition", "reflections", "lectures",
                                    "book by", "written by", "essay"]):
            return False
        return True

    # Source is a paraphrase of a biblical text — but only if speaker is biblical
    if source_has_paraphrase and any(book in src for book in BIBLE_BOOKS):
        return True

    # Attribution is a psalm reference like "Psalm 96"
    if re.match(r'^psalm\s*\d+', attr):
        return True

    return False


def derive_reference(quotation):
    """Try to derive a Bible reference from the quotation metadata."""
    src = (quotation.get("source") or "").strip()
    attr = (quotation.get("attribution") or "").strip()

    # If source has a verse reference, use it
    if src and VERSE_RE.search(src):
        # Clean up parenthetical notes
        ref = re.sub(r'\(paraphrase\)', '', src, flags=re.IGNORECASE).strip()
        return ref

    # If source is a Bible book name
    if src:
        return src

    # If attribution is a psalm
    if re.match(r'^Psalm\s*\d+', attr, re.IGNORECASE):
        return attr

    # Fallback: use attribution + source
    parts = [p for p in [attr, src] if p]
    return " — ".join(parts) if parts else "Unknown reference"


def derive_supports_claim(quotation):
    """Generate a supports_claim from the quotation text."""
    text = (quotation.get("text") or "")[:120]
    fn = quotation.get("function") or "authority"
    return f"Biblical speech used as {fn}: \"{text}...\""


def fetch_all_quotations():
    """Fetch all quotations, paginating as needed."""
    all_rows = []
    offset = 0
    batch = 1000
    while True:
        rows = sb.table("quotations").select("*").range(offset, offset + batch - 1).execute().data
        all_rows.extend(rows)
        if len(rows) < batch:
            break
        offset += batch
    return all_rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Preview without making changes")
    parser.add_argument("--execute", action="store_true", help="Actually migrate")
    args = parser.parse_args()

    if not args.dry_run and not args.execute:
        parser.print_help()
        sys.exit(1)

    print("Fetching all quotations...")
    quotations = fetch_all_quotations()
    print(f"Total quotations: {len(quotations)}")

    biblical = []
    non_biblical = []
    for q in quotations:
        if is_biblical(q):
            biblical.append(q)
        else:
            non_biblical.append(q)

    print(f"Biblical (to migrate): {len(biblical)}")
    print(f"Non-biblical (keep): {len(non_biblical)}")
    print()

    if args.dry_run:
        print("=== DRY RUN — would migrate these: ===")
        for q in biblical:
            ref = derive_reference(q)
            print(f"  {q['attribution']} | {q['source']} → citation ref: {ref}")
        print(f"\n{len(biblical)} quotations would be migrated to citations tier 2.")
        print(f"{len(non_biblical)} quotations would remain.")
        return

    if args.execute:
        print("Migrating...")
        migrated = 0
        errors = 0
        for q in biblical:
            try:
                # Map quotation function to citation function
                qfn = q.get("function") or "authority"
                citation_fn_map = {
                    "authority": "authority",
                    "illustration": "echo",
                    "devotional": "echo",
                    "provocation": "contrast",
                    "opponent": "contrast",
                }
                citation_fn = citation_fn_map.get(qfn, "authority")

                # Insert into citations as tier 2
                sb.table("citations").insert({
                    "unit_id": q["unit_id"],
                    "tier": 2,
                    "reference": derive_reference(q),
                    "mode": None,
                    "function": citation_fn,
                    "supports_claim": q.get("text", "")[:200],
                }).execute()

                # Delete from quotations
                sb.table("quotations").delete().eq("id", q["id"]).execute()
                migrated += 1

                if migrated % 50 == 0:
                    print(f"  ...migrated {migrated}/{len(biblical)}")

            except Exception as e:
                print(f"  ERROR on {q['id']}: {e}")
                errors += 1

        print(f"\nDone. Migrated: {migrated}, Errors: {errors}")


if __name__ == "__main__":
    main()
