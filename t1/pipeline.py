"""Orchestrate T1 structure: acquire → chunk → index. No Anthropic."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from t1.acquire import AcquiredSermon, acquire_path, slugify
from t1.chunker import Chapter, chunk_sermon
from t1.cost import estimate_t1_cost
from t1.index import build_keyword_index, chapter_terms, maybe_embed_chapters
from t1.promote import t2_command
from t1.style import discern_style, ministry_profile, style_catalog_row


@dataclass
class T1Result:
    sermon: AcquiredSermon
    chapters: list[Chapter]
    payload: dict[str, Any]
    dest: Path


def structure_sermon(
    acquired: AcquiredSermon,
    *,
    embed: bool = False,
    style: bool = True,
) -> tuple[list[Chapter], dict[str, Any]]:
    chapters = chunk_sermon(acquired)
    vectors, embed_apis, embed_skip = maybe_embed_chapters(chapters, embed)
    cost = estimate_t1_cost(
        has_source_text=bool(acquired.text),
        embed=bool(vectors),
        char_count=len(acquired.text),
        chapter_count=len(chapters),
        audio_duration_sec=acquired.duration_sec,
        style=style,
    )
    if embed and not vectors:
        cost["notes"].append(embed_skip or "embeddings skipped")
    cost["apis_called"] = list(cost["apis_called"]) + embed_apis
    style_payload = None
    if style:
        style_payload = discern_style(
            acquired.text,
            title=acquired.title,
            primary_text=acquired.primary_text,
        )
        cost["notes"].append("Style heuristics local — $0 vs chunk-only T1.")

    chapter_payloads: list[dict[str, Any]] = []
    for i, ch in enumerate(chapters):
        item = ch.to_dict()
        item["terms"] = chapter_terms(ch)
        if vectors and i < len(vectors):
            item["embedding"] = vectors[i]
        chapter_payloads.append(item)

    payload = {
        "tier": "T1",
        "sermon_id": acquired.sermon_id,
        "slug": slugify(f"{acquired.preacher}-{acquired.title}"),
        "title": acquired.title,
        "preacher": acquired.preacher,
        "primary_text": acquired.primary_text,
        "source_path": acquired.source_path,
        "source_kind": acquired.source_kind,
        "audio_url": acquired.audio_url,
        "duration_sec": acquired.duration_sec,
        "text": acquired.text,
        "char_count": len(acquired.text),
        "word_count": len(acquired.text.split()),
        "chapters": chapter_payloads,
        "index": {
            "kind": "voyage" if vectors else "keyword",
            "chapter_count": len(chapter_payloads),
            "embedding_dims": len(vectors[0]) if vectors else None,
        },
        "style": style_payload,
        "cost": cost,
        "promote": {
            "status": "not_promoted",
            "command": t2_command(acquired.source_path, acquired.preacher),
        },
        "metadata": acquired.metadata,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "apis_forbidden": ["anthropic"],
    }
    return chapters, payload


def write_sermon_artifact(payload: dict[str, Any], output_dir: Path) -> Path:
    sermons_dir = output_dir / "sermons"
    sermons_dir.mkdir(parents=True, exist_ok=True)
    dest = sermons_dir / f"{payload['slug']}.json"
    dest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return dest


def write_corpus_index(payloads: list[dict[str, Any]], output_dir: Path) -> Path:
    slim = []
    for p in payloads:
        slim.append({
            "sermon_id": p["sermon_id"],
            "title": p["title"],
            "preacher": p["preacher"],
            "slug": p["slug"],
            "source_path": p["source_path"],
            "chapters": [
                {
                    "chapter_id": c["chapter_id"],
                    "title": c["title"],
                    "text": c["text"],
                    "char_start": c["char_start"],
                    "char_end": c["char_end"],
                    "start_ms": c.get("start_ms"),
                    "end_ms": c.get("end_ms"),
                    "source": c.get("source"),
                    "terms": c.get("terms") or [],
                }
                for c in p.get("chapters") or []
            ],
        })
    index = build_keyword_index(slim)
    index["sermons"] = [
        {
            "sermon_id": p["sermon_id"],
            "slug": p["slug"],
            "title": p["title"],
            "preacher": p["preacher"],
            "chapter_count": len(p.get("chapters") or []),
            "artifact": f"sermons/{p['slug']}.json",
            "style": style_catalog_row(p["style"]) if p.get("style") else None,
        }
        for p in payloads
    ]
    styled = [p["style"] for p in payloads if p.get("style")]
    if styled:
        index["ministry_profile"] = ministry_profile(styled)
    dest = output_dir / "index.json"
    dest.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    return dest


def ingest_paths(
    paths: list[Path],
    *,
    output_dir: Path,
    preacher: Optional[str] = None,
    embed: bool = False,
    style: bool = True,
) -> list[T1Result]:
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[T1Result] = []
    payloads: list[dict[str, Any]] = []
    for path in paths:
        acquired = acquire_path(path, preacher=preacher)
        chapters, payload = structure_sermon(acquired, embed=embed, style=style)
        dest = write_sermon_artifact(payload, output_dir)
        results.append(T1Result(acquired, chapters, payload, dest))
        payloads.append(payload)
    if payloads:
        write_corpus_index(payloads, output_dir)
        report = {
            "tier": "T1",
            "sermons": len(payloads),
            "output_dir": str(output_dir),
            "artifacts": [str(r.dest) for r in results],
            "index": str(output_dir / "index.json"),
            "t1_usd_total": round(
                sum((p.get("cost") or {}).get("usd_estimate") or 0 for p in payloads),
                6,
            ),
            "apis_called": sorted({
                api
                for p in payloads
                for api in ((p.get("cost") or {}).get("apis_called") or [])
            }),
            "anthropic_called": False,
            "style_enabled": style,
            "ministry_profile": ministry_profile(
                [p["style"] for p in payloads if p.get("style")]
            ) if style else None,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        (output_dir / "run_report.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
    return results
