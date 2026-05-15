"""DeployAdapter interface. V2 will plug Cloudflare Pages / Vercel / Netlify behind this."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol


@dataclass
class DeployResult:
    status: str                # 'success' | 'error'
    deployed_at: Optional[str] # ISO-8601 timestamp
    url: Optional[str]
    error: Optional[str] = None


class DeployAdapter(Protocol):
    """All concrete adapters implement this — V1 has only `raise NotImplementedError` stubs."""

    def deploy(self, html_path: Path, canonical_url: str, config: dict) -> DeployResult:
        ...
