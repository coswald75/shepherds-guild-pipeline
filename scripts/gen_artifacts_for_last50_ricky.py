"""One-off: generate the 6 artifacts for each of Ricky's last 50 sermons
that doesn't already have a full bundle."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv

load_dotenv(REPO_ROOT / ".env", override=True)

from sermon_page_renderer import queries as q  # noqa: E402

RICKY_ID = "ccb9e59c-bd20-414a-bd6b-25b117b8144c"


def get_last_50_needing_artifacts() -> list[str]:
    sb = q.get_supabase()
    # 50 most recent eligible Ricky sermons
    rows = (
        sb.table("sermons")
        .select("id, date, title")
        .eq("preacher_id", RICKY_ID)
        .not_.is_("main_thesis", "null")
        .not_.is_("date", "null")
        .not_.is_("slug", "null")
        .order("date", desc=True)
        .limit(50)
        .execute()
        .data
        or []
    )
    ids = [r["id"] for r in rows]

    # Find which already have a full 6-artifact bundle
    artifacts = (
        sb.table("sermon_artifacts")
        .select("sermon_id, artifact_type")
        .in_("sermon_id", ids)
        .execute()
        .data
        or []
    )
    bundle: dict[str, set[str]] = {}
    for a in artifacts:
        bundle.setdefault(a["sermon_id"], set()).add(a["artifact_type"])
    needs = [r for r in rows if len(bundle.get(r["id"], set())) < 6]
    print(f"50 candidates; {len(needs)} need artifact generation")
    return needs


def main() -> int:
    needs = get_last_50_needing_artifacts()
    t0 = time.time()
    fails = []
    for i, row in enumerate(needs, 1):
        sid = row["id"]
        print(
            f"\n[{i}/{len(needs)}] {row['date']}  {(row.get('title') or '')[:60]}",
            flush=True,
        )
        r = subprocess.run(
            ["python3", str(REPO_ROOT / "generate_artifacts.py"),
             "generate", sid, "--skip-existing"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            print(f"  FAILED: {r.stderr[-300:]}", flush=True)
            fails.append((sid, r.stderr[-200:]))
        else:
            # last few lines of stdout for visibility
            tail = r.stdout.strip().splitlines()[-3:]
            for line in tail:
                print(f"    {line}", flush=True)
        print(f"  elapsed: {time.time()-t0:.0f}s", flush=True)

    print(f"\nDONE in {time.time()-t0:.0f}s. {len(needs) - len(fails)} ok, {len(fails)} failed.")
    if fails:
        for sid, msg in fails:
            print(f"  {sid}: {msg}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
