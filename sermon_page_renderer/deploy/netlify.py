"""Netlify deploy adapter — V1 stub."""

from __future__ import annotations

from pathlib import Path

from .base import DeployResult


class NetlifyAdapter:
    def deploy(self, html_path: Path, canonical_url: str, config: dict) -> DeployResult:
        raise NotImplementedError(
            "Netlify adapter not yet implemented. V1 ships file output only."
        )
