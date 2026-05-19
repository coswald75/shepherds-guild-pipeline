"""Deploy adapters for the sermon page renderer."""

from .base import DeployAdapter, DeployResult
from .cloudflare_pages import CloudflarePagesAdapter

__all__ = ["DeployAdapter", "DeployResult", "CloudflarePagesAdapter"]
