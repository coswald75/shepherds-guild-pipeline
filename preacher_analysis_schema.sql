-- ============================================================================
-- Shepherd's Guild — Preacher Analysis Table
-- Stores computed stats + AI-generated prose for the dashboard
-- Run this migration against your Supabase project
-- ============================================================================

-- The analysis table: one row per preacher, updated each pipeline run
CREATE TABLE IF NOT EXISTS preacher_analysis (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    preacher_id     UUID NOT NULL REFERENCES preachers(id) ON DELETE CASCADE,

    -- ── Raw computed stats (from SQL aggregation) ──
    -- Stored as JSONB so the shape can evolve without migrations
    stats           JSONB NOT NULL DEFAULT '{}',
    -- Expected shape:
    -- {
    --   "sermon_count": 34,
    --   "total_units": 1212,
    --   "theological_fingerprint": {
    --     "Christology": 298, "Sanctification": 288, ...
    --   },
    --   "rhetorical_register": {
    --     "logos": 79, "pathos": 22, "ethos": 14, ...
    --   },
    --   "homiletical_method": {
    --     "exposition": 381, "theological_claim": 336, ...
    --   },
    --   "illustration_density": 3.1,
    --   "illustration_types": {
    --     "personal_story": 29, "cultural_reference": 23, ...
    --   },
    --   "application_per_sermon": 4.1,
    --   "application_specificity": {
    --     "abstract": 45, "concrete": 62, "mixed": 34
    --   },
    --   "top_quoted_authors": [
    --     {"author": "C.S. Lewis", "count": 9}, ...
    --   ],
    --   "quotation_count": 92
    -- }

    -- ── Exemplar comparison results ──
    exemplar_matches JSONB NOT NULL DEFAULT '[]',
    -- Expected shape:
    -- [
    --   {
    --     "preacher_name": "Tim Keller",
    --     "preacher_id": "uuid",
    --     "match_pct": 74,
    --     "rank": "Primary Match",
    --     "reasons": [
    --       "Christology as organizing center",
    --       "Cultural illustration density", ...
    --     ]
    --   }, ...
    -- ]

    -- ── AI-generated prose sections ──
    -- Each section stored separately so the dashboard can render them independently
    hall_distinction    JSONB NOT NULL DEFAULT '{}',
    -- { "label": "Logos-dominant", "text": "Nearly 8 in 10...", "stat_n": "79%", "stat_label": "Logos register\nacross all units" }

    growth_intro        JSONB NOT NULL DEFAULT '{}',
    -- { "label": "What This Means...", "text": "The Keller-Carson axis..." }

    growth_areas        JSONB NOT NULL DEFAULT '[]',
    -- [
    --   {
    --     "number": "01",
    --     "label": "Illustration Density",
    --     "title_html": "Room to illustrate <em>more.</em>",
    --     "diagnosis": "At 3.1 illustrations...",
    --     "metric_current": "3.1",
    --     "metric_current_label": "Chris",
    --     "metric_target": "4.8",
    --     "metric_target_label": "Keller",
    --     "metric_caption": "Illus. per sermon\nHall avg: 4.2",
    --     "recommendation": "In each sermon's prep..."
    --   }, ...
    -- ]

    latent_book         JSONB NOT NULL DEFAULT '{}',
    -- {
    --   "confidence": "High",
    --   "title": "The Psalms of the Broken:",
    --   "subtitle": "Suffering, Lament, and the God Who Stays",
    --   "body": "Across your Psalms series alone...",
    --   "evidence_signals": [
    --     {"label": "Thematic concentration in corpus", "pct": 81}, ...
    --   ],
    --   "evidence_cards": [
    --     {"type": "Doctrinal Spine", "text": "...", "source": "..."}, ...
    --   ],
    --   "secondary": {
    --     "confidence": "Moderate",
    --     "title_html": "A theology of <em>sanctification in the ordinary.</em>",
    --     "diagnosis": "Your Ephesians and 1 John sermons...",
    --     "metric_current": "13", "metric_current_label": "Sermons",
    --     "metric_target": "8", "metric_target_label": "Sermons",
    --     "metric_caption": "Ephesians + 1 John\ncombined series",
    --     "next_step": "Your corpus would need..."
    --   }
    -- }

    -- ── Quotes (extracted from quotations table) ──
    quotes              JSONB NOT NULL DEFAULT '[]',
    -- [{"text": "...", "attr": "C.S. Lewis", "source": "..."}, ...]

    -- ── Metadata ──
    generated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    generation_model    TEXT NOT NULL DEFAULT 'claude-sonnet-4-5-20250929',
    generation_version  TEXT NOT NULL DEFAULT '1.0',

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- One analysis per preacher (upsert-friendly)
    CONSTRAINT unique_preacher_analysis UNIQUE (preacher_id)
);

CREATE INDEX IF NOT EXISTS idx_preacher_analysis_preacher ON preacher_analysis(preacher_id);

-- ============================================================================
-- Enable this table via Supabase REST API (PostgREST)
-- If you have RLS enabled, you'll need a policy. For now, basic access:
-- ============================================================================
-- ALTER TABLE preacher_analysis ENABLE ROW LEVEL SECURITY;
-- CREATE POLICY "Preachers can read their own analysis"
--     ON preacher_analysis FOR SELECT
--     USING (preacher_id = auth.uid());
