"""
Shepherd's Guild — Batch Failure Repair Script
================================================

Repairs malformed JSON from failed batch decompositions.

Handles three failure modes:
  1. Unescaped quotes inside string values (most common)
  2. Markdown wrapper instead of raw JSON
  3. Bare unquoted values in arrays

Usage:
  # Dry run — show what would be repaired, don't write files
  python3 repair_batch_failures.py --output-dir ./output

  # Repair and write fixed JSON files
  python3 repair_batch_failures.py --output-dir ./output --write

  # Then re-run the process step (dry-run first to verify)
  python3 pipeline_batch.py process <batch_id> --canonical --dry-run

Requirements:
  pip install json-repair
"""

import os
import sys
import json
import argparse
import logging
from pathlib import Path

try:
    from json_repair import repair_json
except ImportError:
    print("Missing dependency: json-repair")
    print("Install with: pip install json-repair")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("repair")


def strip_markdown_wrapper(text: str) -> str:
    """Strip markdown headers and code fences to extract raw JSON."""
    stripped = text.strip()

    # If it already starts with {, no wrapping to remove
    if stripped.startswith("{"):
        return stripped

    # Find the first { — everything before it is markdown preamble
    first_brace = stripped.find("{")
    if first_brace < 0:
        return stripped  # No JSON object found at all

    stripped = stripped[first_brace:]

    # Find the last } — everything after it is trailing markdown
    last_brace = stripped.rfind("}")
    if last_brace < 0:
        return stripped

    stripped = stripped[:last_brace + 1]
    return stripped


def validate_decomposition(data: dict) -> list[str]:
    """Basic structural validation of a repaired decomposition."""
    warnings = []

    if not isinstance(data, dict):
        warnings.append("Root is not a dict")
        return warnings

    # Check required top-level fields
    for field in ["title", "primary_text", "units"]:
        if field not in data:
            warnings.append(f"Missing top-level field: {field}")

    units = data.get("units", [])
    if not isinstance(units, list):
        warnings.append("'units' is not a list")
    elif len(units) == 0:
        warnings.append("'units' is empty")
    else:
        for i, unit in enumerate(units):
            if not isinstance(unit, dict):
                warnings.append(f"Unit {i} is not a dict")
                continue
            if "content" not in unit:
                warnings.append(f"Unit {i} missing 'content'")
            if "rhetorical_function" not in unit:
                warnings.append(f"Unit {i} missing 'rhetorical_function'")

    return warnings


def repair_file(filepath: Path, write: bool = False) -> dict:
    """
    Attempt to repair a single debug_raw file.
    Returns a status dict.
    """
    raw = filepath.read_text(encoding="utf-8")

    # Phase 1: Strip markdown wrapper if present
    cleaned = strip_markdown_wrapper(raw)

    # Phase 2: Attempt standard JSON parse first
    try:
        data = json.loads(cleaned)
        return {
            "file": filepath.name,
            "status": "already_valid",
            "units": len(data.get("units", [])),
            "warnings": validate_decomposition(data),
        }
    except json.JSONDecodeError:
        pass

    # Phase 3: Use json_repair
    try:
        data = repair_json(cleaned, return_objects=True)
    except Exception as e:
        return {
            "file": filepath.name,
            "status": f"repair_failed: {e}",
            "units": 0,
            "warnings": [],
        }

    if not isinstance(data, dict):
        return {
            "file": filepath.name,
            "status": f"repair_produced_{type(data).__name__}_not_dict",
            "units": 0,
            "warnings": [],
        }

    # Phase 4: Validate the repaired output
    warnings = validate_decomposition(data)

    # Phase 5: Verify the repaired JSON round-trips cleanly
    try:
        roundtrip = json.dumps(data, ensure_ascii=False, indent=2)
        json.loads(roundtrip)  # Confirm it parses back
    except (json.JSONDecodeError, TypeError) as e:
        return {
            "file": filepath.name,
            "status": f"roundtrip_failed: {e}",
            "units": len(data.get("units", [])),
            "warnings": warnings,
        }

    units = data.get("units", [])
    status = "repaired"

    # Phase 6: Write the repaired file if requested
    if write:
        # Write as _decomposed.json matching the pipeline's naming convention
        # debug_raw_<custom_id>.txt → <custom_id>_decomposed.json
        stem = filepath.stem  # debug_raw_<custom_id>
        custom_id = stem.replace("debug_raw_", "", 1)
        output_path = filepath.parent / f"{custom_id}_decomposed.json"

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        log.info(f"Wrote: {output_path.name}")
        status = f"repaired_and_written → {output_path.name}"

    return {
        "file": filepath.name,
        "status": status,
        "units": len(units),
        "title": data.get("title", "(no title)"),
        "warnings": warnings,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Repair failed batch decomposition JSON files"
    )
    parser.add_argument(
        "--output-dir", type=Path, required=True,
        help="Path to the pipeline output directory containing debug_raw_*.txt files"
    )
    parser.add_argument(
        "--write", action="store_true",
        help="Write repaired JSON files (without this flag, dry-run only)"
    )
    args = parser.parse_args()

    output_dir = args.output_dir
    if not output_dir.is_dir():
        log.error(f"Not a directory: {output_dir}")
        sys.exit(1)

    debug_files = sorted(output_dir.glob("debug_raw_*.txt"))
    if not debug_files:
        log.info(f"No debug_raw_*.txt files found in {output_dir}")
        sys.exit(0)

    log.info(f"Found {len(debug_files)} failed decomposition files to repair")
    if not args.write:
        log.info("DRY RUN — use --write to save repaired files\n")

    repaired = 0
    failed = 0
    already_valid = 0

    for filepath in debug_files:
        result = repair_file(filepath, write=args.write)

        if result["status"] == "already_valid":
            log.info(f"  OK (already valid): {result['file']} — {result['units']} units")
            already_valid += 1
        elif result["status"].startswith("repaired"):
            icon = "✓" if args.write else "→"
            log.info(
                f"  {icon} {result['file']} — {result['units']} units — "
                f"\"{result.get('title', '?')}\""
            )
            if result["warnings"]:
                for w in result["warnings"]:
                    log.warning(f"      ⚠ {w}")
            repaired += 1
        else:
            log.error(f"  ✗ {result['file']}: {result['status']}")
            failed += 1

    log.info(f"\n{'='*60}")
    log.info(f"REPAIR SUMMARY")
    log.info(f"{'='*60}")
    log.info(f"Already valid:  {already_valid}")
    log.info(f"Repaired:       {repaired}")
    log.info(f"Failed:         {failed}")
    log.info(f"Total:          {len(debug_files)}")

    if repaired > 0 and not args.write:
        log.info(f"\nRe-run with --write to save repaired files.")


if __name__ == "__main__":
    main()
