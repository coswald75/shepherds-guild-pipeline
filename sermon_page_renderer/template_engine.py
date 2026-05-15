"""
Jinja2 environment setup for the sermon page renderer.

Kept tiny so the CLI, the integration test, and `pipeline_batch.py --render`
all share the same environment configuration.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from jinja2 import (
    ChainableUndefined,
    Environment,
    FileSystemLoader,
    StrictUndefined,
    select_autoescape,
)

# Repo-root templates/ directory. The CLI may override this via `make_env(path=...)`.
DEFAULT_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"


def make_env(template_dir: Optional[Path] = None, *, strict: bool = False) -> Environment:
    """
    Build the Jinja2 environment. `strict=True` raises on undefined variables —
    useful for tests; the default leaves undefined values as empty strings so
    a partial sermon row still renders something.
    """
    return Environment(
        loader=FileSystemLoader(str(template_dir or DEFAULT_TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "j2", "html.j2"]),
        undefined=StrictUndefined if strict else ChainableUndefined,
        trim_blocks=False,
        lstrip_blocks=False,
        keep_trailing_newline=True,
    )


def render_sermon_page(context: dict, template_name: str = "sermon_page.html.j2") -> str:
    """Render the sermon page template against the composer context dict."""
    env = make_env()
    template = env.get_template(template_name)
    return template.render(**context)
