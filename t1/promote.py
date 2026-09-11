"""Promote a T1 sermon to T2 deep decompose.

POC stub: does not call Anthropic. Writes a receipt and prints the existing
production command so a later paid/product-backed run can pick it up.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def t2_command(source_path: str, preacher: str, dry_run: bool = True) -> str:
    cmd = f'python pipeline.py decompose "{source_path}" --preacher "{preacher}"'
    if dry_run:
        cmd += " --dry-run"
    return cmd


def promote_record(
    t1_sermon: dict[str, Any],
    *,
    dry_run: bool = True,
) -> dict[str, Any]:
    source = t1_sermon.get("source_path") or ""
    preacher = t1_sermon.get("preacher") or "Unknown"
    return {
        "status": "stub",
        "tier_from": "T1",
        "tier_to": "T2",
        "sermon_id": t1_sermon.get("sermon_id"),
        "title": t1_sermon.get("title"),
        "preacher": preacher,
        "source_path": source,
        "command": t2_command(source, preacher, dry_run=dry_run),
        "todo": (
            "Call the existing production decompose path when this sermon is "
            "promoted / product-backed. Do not invent a second decompose client."
        ),
        "notes": [
            "weekly_ingest.py and pipeline.py are unchanged.",
            "Pass --dry-run first to review Sonnet JSON before embed+ingest.",
            "Drop --dry-run to embed (Voyage) and write to Supabase.",
        ],
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def write_promote_receipt(record: dict[str, Any], dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return dest
