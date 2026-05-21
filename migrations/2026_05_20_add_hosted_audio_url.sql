-- Add hosted_audio_url to sermons.
-- audio_url stays as the original-host URL (provenance + fallback).
-- hosted_audio_url, when set, points to our R2 mirror at
-- sermons-cdn.sermonsteward.com and is a stable URL that does not expire.
-- Renderer prefers hosted_audio_url when populated.

ALTER TABLE sermons
  ADD COLUMN IF NOT EXISTS hosted_audio_url text;

COMMENT ON COLUMN sermons.hosted_audio_url IS
  'Cloudflare R2 mirror of audio_url. Stable URL at sermons-cdn.sermonsteward.com. NULL until backfill/mirror runs.';

-- Index to make backfill queries (hosted_audio_url IS NULL AND audio_url IS NOT NULL) cheap.
CREATE INDEX IF NOT EXISTS sermons_pending_hosted_audio_idx
  ON sermons (preacher_id)
  WHERE hosted_audio_url IS NULL AND audio_url IS NOT NULL;
