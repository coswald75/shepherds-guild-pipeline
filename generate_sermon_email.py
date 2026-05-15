"""
Render a sermon's weekly digest as an email-optimized HTML file.

The template at `templates/sermon_email.html.j2` is a separate artifact from
the web sermon page — narrower (600px), inline-style-only, table-based layout
for Outlook compatibility, and focused on the 6 member-facing artifacts plus
a "read the full page" CTA.

Usage:
  python generate_sermon_email.py <sermon_id>
  python generate_sermon_email.py <sermon_id> --output-dir custom/path/
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from sermon_page_renderer.composer import compose
from sermon_page_renderer.template_engine import make_env

load_dotenv(override=True)

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "emails"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("generate_sermon_email")


def render_email(sermon_id: str, output_dir: Optional[Path] = None) -> Path:
    """Compose context, render the email template, write to disk."""
    context = compose(sermon_id)
    if not context.get("artifacts"):
        raise ValueError(
            f"No sermon_artifacts rows for {sermon_id} — generate them first via "
            f"`python generate_artifacts.py generate {sermon_id}`."
        )

    env = make_env()
    template = env.get_template("sermon_email.html.j2")
    html = template.render(**context)

    output_dir = output_dir or DEFAULT_OUTPUT_DIR
    church_slug = (context.get("church") or {}).get("slug") or "unknown-church"
    sermon_slug = (context.get("sermon") or {}).get("slug") or sermon_id
    date_iso = (context.get("sermon") or {}).get("date_iso") or ""

    out_dir = output_dir / church_slug
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{sermon_slug}.html"
    out_path.write_text(html, encoding="utf-8")

    log.info(f"rendered email → {out_path}")
    log.info(f"  size: {len(html):,} chars")
    log.info(f"  subject suggestion: {context['sermon']['title']} — {context['church']['name']}")
    return out_path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("sermon_id")
    p.add_argument("--output-dir", type=Path, default=None)
    args = p.parse_args()

    try:
        render_email(args.sermon_id, args.output_dir)
    except ValueError as exc:
        log.error(str(exc))
        sys.exit(1)


if __name__ == "__main__":
    main()
