-- ============================================================================
-- Shepherd's Guild — Supabase Schema v3
-- Sermon Decomposition Pipeline + RAG Infrastructure
-- March 2026
-- ============================================================================
-- 
-- Designed to serve:
--   • PASTORALRAG — structured retrieval + semantic search
--   • Forge / MIRRORVOX — homiletical benchmarking + archetype analysis
--   • Guild Hall — canonical preacher reference library
--   • TRAININGDATA — labeled sermon corpora (future)
--   • BookGuide — illustration/quote extraction for publishing
--
-- Key design decisions:
--   • Fully normalized: sermons → units → citations/quotations/bt_moves
--   • pgvector embeddings on units for semantic search
--   • Multi-tenant via preacher → church scoping
--   • Canonical (Guild Hall) and customer preachers in same tables
--   • Row Level Security ready (not enabled here — add per deployment)
-- ============================================================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";

-- ============================================================================
-- CHURCHES
-- Multi-tenant root. Every customer pastor belongs to a church.
-- Canonical/Guild Hall preachers have church_id = NULL.
-- ============================================================================
CREATE TABLE churches (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================================
-- PREACHERS
-- Both customer pastors and canonical Guild Hall preachers.
-- is_canonical = true for reference library preachers.
-- is_public controls whether their corpus is queryable by other pastors
-- (the "dark until licensed" flag).
-- ============================================================================
CREATE TABLE preachers (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    church_id       UUID REFERENCES churches(id) ON DELETE SET NULL,
    name            TEXT NOT NULL,
    is_canonical    BOOLEAN NOT NULL DEFAULT false,
    is_public       BOOLEAN NOT NULL DEFAULT false,
    bio             TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_preachers_church ON preachers(church_id);
CREATE INDEX idx_preachers_canonical ON preachers(is_canonical) WHERE is_canonical = true;

-- ============================================================================
-- SERMONS
-- One row per sermon. All sermon-level fields from Decomposition Spec v3.
-- Arrays stored as native Postgres arrays or JSONB where appropriate.
-- ============================================================================
CREATE TABLE sermons (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    preacher_id         UUID NOT NULL REFERENCES preachers(id) ON DELETE CASCADE,
    
    -- Core metadata
    title               TEXT NOT NULL,
    date                DATE,
    primary_text        TEXT,
    sermon_type         TEXT CHECK (sermon_type IN (
                            'expository', 'topical', 'textual', 'narrative', 'polemic'
                        )),
    series_name         TEXT,
    series_position     TEXT,
    
    -- Analytical fields
    abstract            TEXT,
    main_thesis         TEXT,
    target_audience_cues TEXT,
    tone                TEXT[] CHECK (tone <@ ARRAY[
                            'pastoral', 'prophetic', 'didactic', 'celebratory',
                            'lament', 'polemic', 'evangelistic'
                        ]::TEXT[]),
    hermeneutical_method TEXT[] CHECK (hermeneutical_method <@ ARRAY[
                            'grammatical_historical', 'redemptive_historical',
                            'canonical', 'applicatory', 'polemic'
                        ]::TEXT[]),
    
    -- Raw source
    raw_transcript      TEXT,
    
    -- Pipeline metadata
    spec_version        TEXT NOT NULL DEFAULT 'v3',
    decomposed_at       TIMESTAMPTZ,
    decomposition_model TEXT,
    input_tokens        INTEGER,
    output_tokens       INTEGER,
    processing_cost_usd NUMERIC(8, 4),
    
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_sermons_preacher ON sermons(preacher_id);
CREATE INDEX idx_sermons_primary_text ON sermons(primary_text);
CREATE INDEX idx_sermons_sermon_type ON sermons(sermon_type);
CREATE INDEX idx_sermons_date ON sermons(date);
CREATE INDEX idx_sermons_series ON sermons(series_name);

-- ============================================================================
-- UNITS
-- One row per functional unit. The core analytical atom.
-- This is where most queries land — both structured and semantic.
-- ============================================================================
CREATE TABLE units (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    sermon_id               UUID NOT NULL REFERENCES sermons(id) ON DELETE CASCADE,
    unit_index              INTEGER NOT NULL,
    
    -- Core fields
    rhetorical_function     TEXT NOT NULL CHECK (rhetorical_function IN (
                                'exposition', 'theological_claim', 'illustration',
                                'application', 'introduction', 'conclusion',
                                'transition', 'pastoral_aside', 'prayer'
                            )),
    content                 TEXT NOT NULL,
    summary                 TEXT,
    key_claim               TEXT,
    
    -- v3 additions
    illustration_type       TEXT CHECK (illustration_type IN (
                                'personal_story', 'historical_example', 'analogy',
                                'hypothetical', 'cultural_reference'
                            )),
    application_specificity TEXT CHECK (application_specificity IN (
                                'abstract', 'concrete', 'mixed'
                            )),
    rhetorical_register     TEXT[] CHECK (rhetorical_register <@ ARRAY[
                                'logos', 'pathos', 'ethos', 'narrative', 'doxological'
                            ]::TEXT[]),
    
    -- Theological metadata
    doctrinal_loci          TEXT[] CHECK (doctrinal_loci <@ ARRAY[
                                'Theology Proper', 'Christology', 'Pneumatology',
                                'Soteriology', 'Hamartiology', 'Anthropology',
                                'Ecclesiology', 'Eschatology', 'Bibliology',
                                'Sanctification', 'Providence / Sovereignty',
                                'Covenant Theology', 'Ethics / Moral Theology',
                                'Doxology / Worship', 'Spiritual Warfare',
                                'Pastoral Theology'
                            ]::TEXT[]),
    people_referenced       TEXT[],
    sermon_series_context   TEXT,
    
    -- Semantic search (Voyage 3.5, 1024 dimensions default)
    embedding               vector(1024),
    
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Ensure unit ordering within a sermon
ALTER TABLE units ADD CONSTRAINT unique_sermon_unit_index UNIQUE (sermon_id, unit_index);

-- Structured query indexes
CREATE INDEX idx_units_sermon ON units(sermon_id);
CREATE INDEX idx_units_rhetorical_function ON units(rhetorical_function);
CREATE INDEX idx_units_illustration_type ON units(illustration_type) WHERE illustration_type IS NOT NULL;
CREATE INDEX idx_units_application_specificity ON units(application_specificity) WHERE application_specificity IS NOT NULL;
CREATE INDEX idx_units_doctrinal_loci ON units USING GIN(doctrinal_loci);
CREATE INDEX idx_units_rhetorical_register ON units USING GIN(rhetorical_register);
CREATE INDEX idx_units_people ON units USING GIN(people_referenced);

-- Semantic search index (IVFFlat — rebuild after loading data)
-- For < 10,000 rows, use exact search (no index needed).
-- When units exceed ~10k rows, create with:
-- CREATE INDEX idx_units_embedding ON units USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- ============================================================================
-- CITATIONS
-- All three tiers of scripture citations in one table.
-- tier = 1 (primary text), 2 (cross-reference)
-- ============================================================================
CREATE TABLE citations (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    unit_id         UUID NOT NULL REFERENCES units(id) ON DELETE CASCADE,
    tier            SMALLINT NOT NULL CHECK (tier IN (1, 2)),
    
    reference       TEXT NOT NULL,
    
    -- Tier 1 fields
    mode            TEXT CHECK (mode IN (
                        'full_reading', 'partial_reading', 'reference_in_passing'
                    )),
    
    -- Tier 2 fields
    function        TEXT CHECK (function IN (
                        'authority', 'contrast', 'echo', 'fulfillment',
                        'parallel', 'corrective'
                    )),
    supports_claim  TEXT,
    
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_citations_unit ON citations(unit_id);
CREATE INDEX idx_citations_reference ON citations(reference);
CREATE INDEX idx_citations_tier ON citations(tier);
CREATE INDEX idx_citations_function ON citations(function) WHERE function IS NOT NULL;

-- ============================================================================
-- QUOTATIONS
-- Human-author quotations (Tier 3 in the spec).
-- Separate table because the fields are entirely different from citations.
-- ============================================================================
CREATE TABLE quotations (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    unit_id         UUID NOT NULL REFERENCES units(id) ON DELETE CASCADE,
    
    text            TEXT NOT NULL,
    attribution     TEXT NOT NULL,
    source          TEXT,
    function        TEXT CHECK (function IN (
                        'authority', 'illustration', 'provocation',
                        'devotional', 'opponent'
                    )),
    
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_quotations_unit ON quotations(unit_id);
CREATE INDEX idx_quotations_attribution ON quotations(attribution);
CREATE INDEX idx_quotations_function ON quotations(function);

-- ============================================================================
-- BIBLICAL-THEOLOGICAL MOVES
-- ============================================================================
CREATE TABLE bt_moves (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    unit_id         UUID NOT NULL REFERENCES units(id) ON DELETE CASCADE,
    
    type            TEXT NOT NULL CHECK (type IN (
                        'typology', 'fulfillment', 'progressive_revelation',
                        'narrative_arc', 'intertextual_echo', 'contrast',
                        'thematic_thread'
                    )),
    source_text     TEXT,
    target_text     TEXT,
    pastor_framing  TEXT,
    
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_bt_moves_unit ON bt_moves(unit_id);
CREATE INDEX idx_bt_moves_type ON bt_moves(type);

-- ============================================================================
-- SERMON-LEVEL ROLLED-UP ARRAYS
-- The spec includes all_quotations and all_cross_references at the sermon
-- level with unit_index references. These are derivable from the normalized
-- tables via JOINs, so we do NOT store them redundantly. Instead, we provide
-- views for convenience.
-- ============================================================================

CREATE VIEW sermon_quotations AS
SELECT
    s.id AS sermon_id,
    s.title AS sermon_title,
    u.unit_index,
    q.text,
    q.attribution,
    q.source,
    q.function
FROM sermons s
JOIN units u ON u.sermon_id = s.id
JOIN quotations q ON q.unit_id = u.id
ORDER BY s.id, u.unit_index;

CREATE VIEW sermon_cross_references AS
SELECT
    s.id AS sermon_id,
    s.title AS sermon_title,
    u.unit_index,
    c.reference,
    c.function,
    c.supports_claim
FROM sermons s
JOIN units u ON u.sermon_id = s.id
JOIN citations c ON c.unit_id = u.id
WHERE c.tier = 2
ORDER BY s.id, u.unit_index;

-- ============================================================================
-- HELPER VIEWS FOR COMMON QUERIES
-- ============================================================================

-- All illustrations with their sermon context
CREATE VIEW illustrations AS
SELECT
    u.id AS unit_id,
    u.sermon_id,
    s.preacher_id,
    p.name AS preacher_name,
    s.title AS sermon_title,
    s.date AS sermon_date,
    u.unit_index,
    u.content,
    u.summary,
    u.illustration_type,
    u.doctrinal_loci,
    u.people_referenced
FROM units u
JOIN sermons s ON s.id = u.sermon_id
JOIN preachers p ON p.id = s.preacher_id
WHERE u.rhetorical_function = 'illustration';

-- All application units with specificity
CREATE VIEW applications AS
SELECT
    u.id AS unit_id,
    u.sermon_id,
    s.preacher_id,
    p.name AS preacher_name,
    s.title AS sermon_title,
    s.date AS sermon_date,
    u.unit_index,
    u.content,
    u.summary,
    u.key_claim,
    u.application_specificity,
    u.doctrinal_loci
FROM units u
JOIN sermons s ON s.id = u.sermon_id
JOIN preachers p ON p.id = s.preacher_id
WHERE u.rhetorical_function = 'application';

-- Preacher profile stats (for Forge / archetype analysis)
CREATE VIEW preacher_profile_stats AS
SELECT
    p.id AS preacher_id,
    p.name AS preacher_name,
    p.is_canonical,
    COUNT(DISTINCT s.id) AS sermon_count,
    COUNT(u.id) AS total_units,
    ROUND(COUNT(u.id)::NUMERIC / NULLIF(COUNT(DISTINCT s.id), 0), 1) AS avg_units_per_sermon,
    
    -- Rhetorical function distribution
    ROUND(100.0 * COUNT(*) FILTER (WHERE u.rhetorical_function = 'exposition') / NULLIF(COUNT(*), 0), 1) AS pct_exposition,
    ROUND(100.0 * COUNT(*) FILTER (WHERE u.rhetorical_function = 'theological_claim') / NULLIF(COUNT(*), 0), 1) AS pct_theological_claim,
    ROUND(100.0 * COUNT(*) FILTER (WHERE u.rhetorical_function = 'illustration') / NULLIF(COUNT(*), 0), 1) AS pct_illustration,
    ROUND(100.0 * COUNT(*) FILTER (WHERE u.rhetorical_function = 'application') / NULLIF(COUNT(*), 0), 1) AS pct_application,
    ROUND(100.0 * COUNT(*) FILTER (WHERE u.rhetorical_function = 'pastoral_aside') / NULLIF(COUNT(*), 0), 1) AS pct_pastoral_aside,
    
    -- Illustration type distribution (of illustration units only)
    COUNT(*) FILTER (WHERE u.illustration_type = 'personal_story') AS illustration_personal_story,
    COUNT(*) FILTER (WHERE u.illustration_type = 'historical_example') AS illustration_historical_example,
    COUNT(*) FILTER (WHERE u.illustration_type = 'analogy') AS illustration_analogy,
    COUNT(*) FILTER (WHERE u.illustration_type = 'hypothetical') AS illustration_hypothetical,
    COUNT(*) FILTER (WHERE u.illustration_type = 'cultural_reference') AS illustration_cultural_reference,
    
    -- Application specificity distribution
    COUNT(*) FILTER (WHERE u.application_specificity = 'abstract') AS application_abstract,
    COUNT(*) FILTER (WHERE u.application_specificity = 'concrete') AS application_concrete,
    COUNT(*) FILTER (WHERE u.application_specificity = 'mixed') AS application_mixed,
    
    -- Cross-reference density
    ROUND(
        (SELECT COUNT(*)::NUMERIC FROM citations c2 
         JOIN units u2 ON u2.id = c2.unit_id 
         JOIN sermons s2 ON s2.id = u2.sermon_id 
         WHERE s2.preacher_id = p.id AND c2.tier = 2)
        / NULLIF(COUNT(DISTINCT s.id), 0), 1
    ) AS avg_cross_refs_per_sermon,
    
    -- BT move density
    ROUND(
        (SELECT COUNT(*)::NUMERIC FROM bt_moves bm 
         JOIN units u3 ON u3.id = bm.unit_id 
         JOIN sermons s3 ON s3.id = u3.sermon_id 
         WHERE s3.preacher_id = p.id)
        / NULLIF(COUNT(DISTINCT s.id), 0), 1
    ) AS avg_bt_moves_per_sermon,
    
    -- Quotation density
    ROUND(
        (SELECT COUNT(*)::NUMERIC FROM quotations q2 
         JOIN units u4 ON u4.id = q2.unit_id 
         JOIN sermons s4 ON s4.id = u4.sermon_id 
         WHERE s4.preacher_id = p.id)
        / NULLIF(COUNT(DISTINCT s.id), 0), 1
    ) AS avg_quotations_per_sermon

FROM preachers p
LEFT JOIN sermons s ON s.id IS NOT NULL AND s.preacher_id = p.id
LEFT JOIN units u ON u.sermon_id = s.id
GROUP BY p.id, p.name, p.is_canonical;

-- ============================================================================
-- EXAMPLE QUERIES (for reference — not executed)
-- ============================================================================

-- PASTORALRAG: "Find my illustrations about fatherhood"
-- SELECT u.content, u.summary, u.illustration_type, s.title, s.date
-- FROM units u
-- JOIN sermons s ON s.id = u.sermon_id
-- WHERE s.preacher_id = :pastor_id
--   AND u.rhetorical_function = 'illustration'
-- ORDER BY u.embedding <=> :query_embedding
-- LIMIT 10;

-- PASTORALRAG: "Any Spurgeon quotes in my sermons?"
-- SELECT q.text, q.source, q.function, s.title, s.date, u.unit_index
-- FROM quotations q
-- JOIN units u ON u.id = q.unit_id
-- JOIN sermons s ON s.id = u.sermon_id
-- WHERE s.preacher_id = :pastor_id
--   AND q.attribution ILIKE '%spurgeon%';

-- PASTORALRAG: "Everything I've preached on Romans 8"
-- SELECT DISTINCT s.id, s.title, s.date, s.abstract
-- FROM sermons s
-- LEFT JOIN units u ON u.sermon_id = s.id
-- LEFT JOIN citations c ON c.unit_id = u.id
-- WHERE s.preacher_id = :pastor_id
--   AND (s.primary_text ILIKE '%Romans 8%' OR c.reference ILIKE '%Romans 8%');

-- GUILD HALL RAG: "What would Spurgeon say about suffering?"
-- SELECT u.content, u.summary, u.key_claim, s.title
-- FROM units u
-- JOIN sermons s ON s.id = u.sermon_id
-- JOIN preachers p ON p.id = s.preacher_id
-- WHERE p.name = 'Charles Spurgeon'
--   AND p.is_public = true
--   AND 'Soteriology' = ANY(u.doctrinal_loci)
-- ORDER BY u.embedding <=> :query_embedding
-- LIMIT 10;

-- FORGE: Compare two preachers' profiles
-- SELECT * FROM preacher_profile_stats
-- WHERE preacher_id IN (:pastor_id, :exemplar_id);
