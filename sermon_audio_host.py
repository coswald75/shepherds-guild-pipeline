"""
sermon_audio_host.py
─────────────────────────────────────────────────────────────────────────────
Mirror customer sermon audio to Cloudflare R2 for stable URLs.

Why: customer hosts (Nucleus, YASH, etc.) often serve audio via signed S3
URLs that expire (Cross of Grace: ~24h after fetch). Mirroring to R2 gives:
  • Stable URLs that never expire
  • Zero egress cost (R2 perk)
  • Real switching cost — the catalog lives on us

The R2 bucket is bound to sermons-cdn.sermonsteward.com via a Cloudflare
custom domain, so the public URL is just f"{R2_PUBLIC_BASE}/{key}".

Soft-fails on missing R2 creds — callers can keep going with audio_url as-is.

Env (set in .env):
  R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET, R2_PUBLIC_BASE
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import logging
import os
from typing import Optional
from urllib.request import Request, urlopen

log = logging.getLogger("sermon_audio_host")

USER_AGENT = "sermon-steward audio-mirror/1.0"
HTTP_TIMEOUT = 120


def _client():
    """boto3 S3 client pointed at R2, or None if creds missing."""
    account = os.getenv("R2_ACCOUNT_ID")
    akey = os.getenv("R2_ACCESS_KEY_ID")
    asecret = os.getenv("R2_SECRET_ACCESS_KEY")
    if not (account and akey and asecret):
        return None
    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        log.warning("boto3 not installed; run: pip install boto3")
        return None
    return boto3.client(
        "s3",
        endpoint_url=f"https://{account}.r2.cloudflarestorage.com",
        aws_access_key_id=akey,
        aws_secret_access_key=asecret,
        region_name="auto",
        config=Config(s3={"addressing_style": "path"}, signature_version="s3v4"),
    )


def is_configured() -> bool:
    return bool(
        os.getenv("R2_ACCOUNT_ID")
        and os.getenv("R2_ACCESS_KEY_ID")
        and os.getenv("R2_SECRET_ACCESS_KEY")
        and os.getenv("R2_BUCKET")
        and os.getenv("R2_PUBLIC_BASE")
    )


def public_url(key: str) -> str:
    base = (os.getenv("R2_PUBLIC_BASE") or "").rstrip("/")
    return f"{base}/{key}"


def already_mirrored(key: str) -> bool:
    c = _client()
    bucket = os.getenv("R2_BUCKET")
    if not (c and bucket):
        return False
    try:
        c.head_object(Bucket=bucket, Key=key)
        return True
    except Exception:
        return False


def mirror_sermon(
    *,
    source_url: str,
    church_slug: str,
    sermon_slug: str,
    force: bool = False,
) -> Optional[str]:
    """
    Download source_url → upload to R2 at <church_slug>/<sermon_slug>.mp3.
    Returns the stable public URL on success, None on failure or no-op.

    Idempotent: if the key already exists, returns the URL without re-uploading.
    Pass force=True to re-upload (e.g., source file changed).
    """
    if not is_configured():
        log.debug("R2 not configured; skipping mirror")
        return None

    # Guard: if source is already our R2 URL, there's nothing to do.
    base = (os.getenv("R2_PUBLIC_BASE") or "").rstrip("/")
    if base and source_url.startswith(base + "/"):
        return source_url

    c = _client()
    bucket = os.getenv("R2_BUCKET")
    key = f"{church_slug}/{sermon_slug}.mp3"

    if not force and already_mirrored(key):
        log.info(f"  [r2] already mirrored → {key}")
        return public_url(key)

    req = Request(source_url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            content_type = (resp.headers.get("Content-Type") or "audio/mpeg").lower()
            content_length = resp.headers.get("Content-Length")

            # Guard: refuse to mirror non-audio content. Hosts that return
            # signed S3 URLs sometimes serve HTML error pages or page URLs
            # masquerading as media — those would otherwise be stored in R2
            # as fake .mp3 files. Accept audio/* and application/octet-stream
            # (some hosts mislabel MP3s as binary), reject everything else.
            ok_prefixes = ("audio/", "application/octet-stream")
            if not any(content_type.startswith(p) for p in ok_prefixes):
                log.warning(
                    f"  [r2] refusing non-audio source for {key}: "
                    f"Content-Type={content_type!r}"
                )
                return None

            c.upload_fileobj(
                resp,
                bucket,
                key,
                ExtraArgs={
                    "ContentType": content_type,
                    "CacheControl": "public, max-age=31536000, immutable",
                },
            )
    except Exception as e:
        log.warning(f"  [r2] mirror failed for {key}: {e}")
        return None

    url = public_url(key)
    size_note = (
        f" ({int(content_length)/1_000_000:.1f} MB)"
        if content_length and content_length.isdigit()
        else ""
    )
    log.info(f"  [r2] mirrored{size_note} → {url}")
    return url
