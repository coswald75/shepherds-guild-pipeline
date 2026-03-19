"""
generate_triage_report.py
Shepherd's Guild — Rhetorical Function Triage Report Generator

Usage:
    python generate_triage_report.py \
        --batch_report batch_report_1772881496.json \
        --decomp_dir ./decomp_outputs/ \
        --output triage_report.json

Given a batch report and the directory of decomp output JSONs, this script:
1. Identifies all rhetorical_function null failures
2. Loads the corresponding decomp JSON for each failed sermon
3. Finds the failing unit (by unit_index from the error details)
4. Pulls the unit above and below as context
5. Assembles a compact triage bundle JSON ready for human review or Opus pass

Output schema per case:
{
    "case_id": "piper__0xQTnGX10_n7mDMi__unit_5",
    "preacher": "John Piper",
    "source_file": "0xQTnGX10_n7mDMi.json",
    "error_type": "rhetorical_function_null",
    "unit_index": 5,
    "context_before": { ...unit fields... },   # unit N-1, or null if first
    "failing_unit":  { ...unit fields... },    # unit N (rhetorical_function is null)
    "context_after": { ...unit fields... },    # unit N+1, or null if last
    "reviewer_decision": null,                 # filled in during review
    "reviewer_notes": null
}
"""

import json
import re
import os
import argparse
from pathlib import Path


# ── Error parsing ──────────────────────────────────────────────────────────────

def is_rhetorical_function_null(status: str) -> bool:
    return (
        "rhetorical_function" in status
        and "not-null" in status
    )


def extract_unit_index_from_error(status: str) -> int | None:
    """
    The DB error details string contains the failing row values in order.
    Column order in units table:
      id, sermon_id, unit_index, rhetorical_function, content, summary,
      key_claim, ...
    The unit_index is the third value — an integer after the second comma
    inside the parentheses.
    """
    match = re.search(r"Failing row contains \([^,]+,\s*[^,]+,\s*(\d+),", status)
    if match:
        return int(match.group(1))
    return None


# ── Unit retrieval ─────────────────────────────────────────────────────────────

UNIT_DISPLAY_FIELDS = [
    "unit_index",
    "rhetorical_function",
    "content",
    "summary",
    "key_claim",
    "doctrinal_loci",
    "people_referenced",
]


def slim_unit(unit: dict) -> dict:
    """Return only the fields useful for triage review — no embeddings, no bulk arrays."""
    return {k: unit.get(k) for k in UNIT_DISPLAY_FIELDS if k in unit or k == "rhetorical_function"}


def get_units_by_index(decomp: dict) -> dict:
    """Build a lookup dict of unit_index -> unit."""
    units = decomp.get("units", [])
    return {u["unit_index"]: u for u in units if "unit_index" in u}


# ── Main assembly ──────────────────────────────────────────────────────────────

def build_triage_case(
    preacher: str,
    source_file: str,
    failing_unit_index: int,
    decomp: dict,
) -> dict:
    by_index = get_units_by_index(decomp)

    failing_unit = by_index.get(failing_unit_index)
    context_before = by_index.get(failing_unit_index - 1)
    context_after = by_index.get(failing_unit_index + 1)

    case_id = f"{preacher.lower().replace(' ', '_')}__{Path(source_file).stem}__unit_{failing_unit_index}"

    return {
        "case_id": case_id,
        "preacher": preacher,
        "source_file": source_file,
        "error_type": "rhetorical_function_null",
        "unit_index": failing_unit_index,
        "context_before": slim_unit(context_before) if context_before else None,
        "failing_unit": slim_unit(failing_unit) if failing_unit else None,
        "context_after": slim_unit(context_after) if context_after else None,
        "reviewer_decision": None,
        "reviewer_notes": None,
    }


def generate_triage_report(
    batch_report_path: str,
    decomp_dir: str,
    output_path: str,
) -> None:
    with open(batch_report_path) as f:
        batch = json.load(f)

    preacher = batch.get("preacher", "Unknown")
    results = batch.get("results", [])
    decomp_dir = Path(decomp_dir)

    cases = []
    skipped = []

    for result in results:
        status = str(result.get("status", ""))
        if not is_rhetorical_function_null(status):
            continue

        source_file = result["file"]
        decomp_path = decomp_dir / source_file

        if not decomp_path.exists():
            skipped.append({
                "file": source_file,
                "reason": f"Decomp file not found at {decomp_path}"
            })
            continue

        with open(decomp_path) as f:
            try:
                decomp = json.load(f)
            except json.JSONDecodeError as e:
                skipped.append({"file": source_file, "reason": f"JSON parse error: {e}"})
                continue

        unit_index = extract_unit_index_from_error(status)
        if unit_index is None:
            skipped.append({"file": source_file, "reason": "Could not parse unit_index from error"})
            continue

        case = build_triage_case(preacher, source_file, unit_index, decomp)
        cases.append(case)

    report = {
        "meta": {
            "preacher": preacher,
            "batch_report": str(batch_report_path),
            "total_cases": len(cases),
            "skipped": skipped,
            "instructions": (
                "For each case, set reviewer_decision to one of: "
                "exposition | theological_claim | illustration | application | "
                "introduction | conclusion | transition | pastoral_aside | prayer. "
                "Add optional reviewer_notes if the case is instructive for prompt improvement."
            ),
        },
        "cases": cases,
    }

    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Triage report written to {output_path}")
    print(f"  Cases: {len(cases)}")
    if skipped:
        print(f"  Skipped: {len(skipped)}")
        for s in skipped:
            print(f"    - {s['file']}: {s['reason']}")


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate rhetorical_function triage report")
    parser.add_argument("--batch_report", required=True, help="Path to batch_report JSON")
    parser.add_argument("--decomp_dir", required=True, help="Directory containing decomp output JSONs")
    parser.add_argument("--output", required=True, help="Output path for triage report JSON")
    args = parser.parse_args()

    generate_triage_report(args.batch_report, args.decomp_dir, args.output)
