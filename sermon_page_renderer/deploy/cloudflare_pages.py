"""
Cloudflare Pages deploy adapter.

The deploy mechanism is "push HTML into the GitHub repo Cloudflare watches" —
Cloudflare auto-deploys on push to main. Per-file `deploy()` satisfies the
DeployAdapter protocol; for batched re-renders (template changes, weekly
ingest of N sermons), use `stage()` repeatedly then `commit_and_push()` once
so one revision lands instead of N.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from .base import DeployResult

log = logging.getLogger("sermon_page_renderer.deploy.cloudflare_pages")


class CloudflarePagesAdapter:
    def __init__(self, repo_path: Path, branch: str = "main"):
        self.repo_path = Path(repo_path).resolve()
        self.branch = branch
        if not (self.repo_path / ".git").exists():
            raise ValueError(f"Not a git repo: {self.repo_path}")
        self._staged: list[Path] = []

    def stage(self, html_path: Path, url_path: str) -> Path:
        """
        Copy an already-rendered HTML file into the deploy repo at the
        URL-mirrored location. Idempotent — overwrites if content changed,
        no-ops if identical.

        url_path: the public URL path, e.g.
          '/ProvidenceLenexa/sermons/growing-in-christ-2026-02-22'
        lands at:
          <repo>/ProvidenceLenexa/sermons/growing-in-christ-2026-02-22.html
        """
        rel = url_path.lstrip("/")
        dest = self.repo_path / f"{rel}.html"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(html_path, dest)
        self._staged.append(dest)
        return dest

    def commit_and_push(
        self,
        message: str,
        *,
        push: bool = True,
    ) -> DeployResult:
        """git add + commit + push everything staged so far. No-op if nothing changed."""
        if not self._staged:
            return DeployResult(
                status="success",
                deployed_at=_now_iso(),
                url=None,
                error="nothing staged",
            )

        rel_paths = [str(p.relative_to(self.repo_path)) for p in self._staged]
        try:
            self._git("add", *rel_paths)
            # If nothing's actually different, git diff --cached returns 0 → skip commit.
            diff = self._git(
                "diff", "--cached", "--quiet", check=False, capture_output=True
            )
            if diff.returncode == 0:
                log.info("commit_and_push: no changes after staging — skipping")
                self._staged.clear()
                return DeployResult(
                    status="success",
                    deployed_at=_now_iso(),
                    url=None,
                    error="no diff",
                )
            self._git("commit", "-m", message)
            if push:
                self._git("push", "origin", self.branch)
        except subprocess.CalledProcessError as exc:
            return DeployResult(
                status="error",
                deployed_at=_now_iso(),
                url=None,
                error=f"{exc.cmd}: rc={exc.returncode} stderr={exc.stderr!r}",
            )
        finally:
            self._staged.clear()

        return DeployResult(
            status="success",
            deployed_at=_now_iso(),
            url=None,
        )

    def deploy(
        self, html_path: Path, canonical_url: str, config: dict
    ) -> DeployResult:
        """Protocol-compliant single-file deploy: stage, commit, push."""
        url_path = urlparse(canonical_url).path
        self.stage(html_path, url_path)
        result = self.commit_and_push(f"Deploy {url_path}")
        if result.status == "success" and result.error not in (
            "nothing staged",
            "no diff",
        ):
            result.url = canonical_url
        return result

    def _git(
        self, *args: str, check: bool = True, capture_output: bool = True
    ) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args],
            cwd=self.repo_path,
            check=check,
            capture_output=capture_output,
            text=True,
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
