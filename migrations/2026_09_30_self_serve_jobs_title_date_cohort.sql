-- Self-serve (try.sermonsteward.com) upload form: pastor-supplied sermon metadata
-- and regional cohort tagging.
--
-- Apply BEFORE deploying the updated sermon-steward-try Worker: the new Worker
-- inserts these columns, and PostgREST rejects inserts that name unknown columns.
-- Safe to re-run (IF NOT EXISTS).

ALTER TABLE self_serve_jobs
  ADD COLUMN IF NOT EXISTS sermon_title text,
  ADD COLUMN IF NOT EXISTS sermon_date  date,
  ADD COLUMN IF NOT EXISTS series_name  text,
  ADD COLUMN IF NOT EXISTS cohort       text;

COMMENT ON COLUMN self_serve_jobs.sermon_title IS
  'Sermon title typed on the upload form. Authoritative over the model''s reading.';
COMMENT ON COLUMN self_serve_jobs.sermon_date IS
  'Date preached, from the upload form. Used as sermons.date instead of the upload date.';
COMMENT ON COLUMN self_serve_jobs.series_name IS
  'Series name, only if the pastor entered one. NULL means no series (never model-inferred).';
COMMENT ON COLUMN self_serve_jobs.cohort IS
  'Regional free-cohort id (e.g. sg-mountain-west) from try.sermonsteward.com/<code>. NULL for the public page.';

CREATE INDEX IF NOT EXISTS self_serve_jobs_cohort_created_idx
  ON self_serve_jobs (cohort, created_at)
  WHERE cohort IS NOT NULL;
