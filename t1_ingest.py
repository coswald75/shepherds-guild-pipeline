#!/usr/bin/env python3
"""
t1_ingest.py — opt-in cheap T1 structure path (POC).

Does NOT replace weekly_ingest.py or pipeline.py. Production weekly/paid
ingest is unchanged. This entrypoint never imports those modules and never
calls Anthropic.

Usage:
    python t1_ingest.py batch fixtures/t1
    python t1_ingest.py ingest fixtures/t1/heading-blessing.txt
    python t1_ingest.py search "justification" --index t1_output/index.json
    python t1_ingest.py styles --index t1_output/index.json
    python t1_ingest.py promote t1_output/sermons/<slug>.json
    python t1_ingest.py cost

Environment:
    None required for the default path (local chunk + keyword index).
    VOYAGE_API_KEY — optional, only with --embed
    ASSEMBLYAI_API_KEY — not used here (T0 STT stays on the existing scraper)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Guard: this CLI must stay cheap. Importing pipeline.py would pull Anthropic.
for _forbidden in ("pipeline", "pipeline_batch", "weekly_ingest", "anthropic"):
    if _forbidden in sys.modules:
        raise RuntimeError(f"t1_ingest must not load {_forbidden}")

from t1.acquire import iter_sermon_files
from t1.cost import T1_COST_MODEL, estimate_t1_cost, estimate_t2_cost
from t1.index import search_index
from t1.pipeline import ingest_paths
from t1.promote import promote_record, write_promote_receipt
from t1.style import label_set_doc

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT = REPO_ROOT / "t1_output"
DEFAULT_FIXTURES = REPO_ROOT / "fixtures" / "t1"


def cmd_ingest(args: argparse.Namespace) -> int:
    path = Path(args.path)
    if not path.exists():
        print(f"not found: {path}", file=sys.stderr)
        return 2
    results = ingest_paths(
        [path],
        output_dir=Path(args.output),
        preacher=args.preacher,
        embed=args.embed,
        style=not args.no_style,
    )
    _print_results(results, Path(args.output))
    return 0


def cmd_batch(args: argparse.Namespace) -> int:
    folder = Path(args.folder)
    if not folder.exists():
        print(f"not found: {folder}", file=sys.stderr)
        return 2
    files = iter_sermon_files(folder)
    if args.limit:
        files = files[: args.limit]
    if not files:
        print(f"no .txt/.md/.json sermons in {folder}", file=sys.stderr)
        return 2
    results = ingest_paths(
        files,
        output_dir=Path(args.output),
        preacher=args.preacher,
        embed=args.embed,
        style=not args.no_style,
    )
    _print_results(results, Path(args.output))
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    index_path = Path(args.index)
    if not index_path.exists():
        print(f"index not found: {index_path} — run batch first", file=sys.stderr)
        return 2
    index = json.loads(index_path.read_text(encoding="utf-8"))
    hits = search_index(index, args.query, limit=args.limit)
    if not hits:
        print("no hits")
        return 0
    for i, hit in enumerate(hits, start=1):
        print(
            f"{i}. {hit['title']} / {hit['chapter_title']} "
            f"({hit['sermon_id']} {hit['chapter_id']}) "
            f"score={hit['score']:.4f} terms={','.join(hit['matched_terms'])}"
        )
    return 0


def cmd_promote(args: argparse.Namespace) -> int:
    src = Path(args.t1_json)
    if not src.exists():
        print(f"not found: {src}", file=sys.stderr)
        return 2
    payload = json.loads(src.read_text(encoding="utf-8"))
    record = promote_record(payload, dry_run=not args.execute)
    dest = Path(args.output) / "promote" / f"{payload.get('slug') or payload.get('sermon_id')}.promote.json"
    write_promote_receipt(record, dest)
    print("T1 → T2 promote is a stub (no Anthropic call).")
    print(f"receipt: {dest}")
    print(f"next:    {record['command']}")
    if args.execute:
        print(
            "(--execute only writes the receipt in this POC; "
            "run the printed pipeline.py command when you are ready to spend.)"
        )
    return 0


def cmd_styles(args: argparse.Namespace) -> int:
    index_path = Path(args.index)
    if not index_path.exists():
        print(f"index not found: {index_path} — run batch first", file=sys.stderr)
        return 2
    index = json.loads(index_path.read_text(encoding="utf-8"))
    profile = index.get("ministry_profile") or {}
    print("ministry profile (provisional; not Coach):")
    print(json.dumps(profile.get("majority") or {}, indent=2))
    print("living_likeness_score:", profile.get("living_likeness_score"))
    print()
    for row in index.get("sermons") or []:
        style = row.get("style") or {}
        print(f"  {row.get('slug')}: {style.get('summary') or '(no style)'}")
    if args.show_labels:
        print()
        print(json.dumps(label_set_doc(), indent=2))
    return 0


def cmd_cost(_: argparse.Namespace) -> int:
    print(json.dumps({
        "model": T1_COST_MODEL,
        "style_labels": label_set_doc(),
        "example_t1_text_only": estimate_t1_cost(
            has_source_text=True, embed=False, char_count=18000, chapter_count=8
        ),
        "example_t1_text_plus_voyage": estimate_t1_cost(
            has_source_text=True, embed=True, char_count=18000, chapter_count=8
        ),
        "example_t2": estimate_t2_cost(),
    }, indent=2))
    return 0


def _print_results(results, output_dir: Path) -> None:
    print(f"T1 structured {len(results)} sermon(s) → {output_dir}")
    for r in results:
        sources = sorted({c.source for c in r.chapters})
        cost = (r.payload.get("cost") or {}).get("usd_estimate")
        style_bit = ""
        if r.payload.get("style"):
            style_bit = f" | {r.payload['style'].get('summary')}"
        print(
            f"  {r.payload['slug']}: {len(r.chapters)} chapters "
            f"({', '.join(sources)}) ${cost}{style_bit} → {r.dest.name}"
        )
    report = output_dir / "run_report.json"
    if report.exists():
        print(f"report: {report}")
        print(f"index:  {output_dir / 'index.json'}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="T1 cheap sermon structure (opt-in POC; does not call Anthropic)"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_in = sub.add_parser("ingest", help="Structure a single sermon file")
    p_in.add_argument("path", type=Path)
    p_in.add_argument("--preacher", default=None)
    p_in.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    p_in.add_argument("--embed", action="store_true",
                      help="Optional Voyage embeddings (requires VOYAGE_API_KEY)")
    p_in.add_argument("--no-style", action="store_true",
                      help="Skip preaching-style heuristics (chunk + index only)")
    p_in.set_defaults(func=cmd_ingest)

    p_batch = sub.add_parser("batch", help="Structure every sermon in a folder")
    p_batch.add_argument("folder", type=Path, nargs="?", default=DEFAULT_FIXTURES)
    p_batch.add_argument("--preacher", default=None)
    p_batch.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    p_batch.add_argument("--limit", type=int, default=0)
    p_batch.add_argument("--embed", action="store_true")
    p_batch.add_argument("--no-style", action="store_true")
    p_batch.set_defaults(func=cmd_batch)

    p_styles = sub.add_parser(
        "styles",
        help="Print provisional style labels / ministry profile from a T1 index",
    )
    p_styles.add_argument("--index", type=Path, default=DEFAULT_OUTPUT / "index.json")
    p_styles.add_argument("--show-labels", action="store_true")
    p_styles.set_defaults(func=cmd_styles)

    p_search = sub.add_parser("search", help="Keyword search a T1 index")
    p_search.add_argument("query")
    p_search.add_argument("--index", type=Path, default=DEFAULT_OUTPUT / "index.json")
    p_search.add_argument("--limit", type=int, default=8)
    p_search.set_defaults(func=cmd_search)

    p_prom = sub.add_parser("promote", help="Stub: print T2 decompose command")
    p_prom.add_argument("t1_json", type=Path)
    p_prom.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    p_prom.add_argument("--execute", action="store_true",
                        help="POC still only writes a receipt; does not call T2")
    p_prom.set_defaults(func=cmd_promote)

    p_cost = sub.add_parser("cost", help="Print the T1 vs T2 cost model")
    p_cost.set_defaults(func=cmd_cost)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
