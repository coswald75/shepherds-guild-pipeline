"""Cloudflare Pages deploy adapter — V1 stub."""

from __future__ import annotations

from pathlib import Path

from .base import DeployResult


class CloudflarePagesAdapter:
    def deploy(self, html_path: Path, canonical_url: str, config: dict) -> DeployResult:
        raise NotImplementedError(
            "Cloudflare Pages adapter not yet implemented. V1 ships file output only."
        )
