-- 003_church_scoped_rpcs.sql
-- ─────────────────────────────────────────────────────────────────────────
-- Applied 2026-06-09 via Supabase MCP apply_migration.
-- Adds church-wide variants of match_units_for_preacher and
-- find_sermon_by_title_in_text. These are called by the corpus-mcp Worker
-- when an MCP request arrives at /c/<church-slug> (the church-scoped
-- public endpoint) — they scope queries by `preacher_id = ANY(uuid[])`
-- across every preacher at the church, instead of `preacher_id = single`.
--
-- The scoring + ranking math is identical to the preacher variants. The
-- only structural difference: match_units_for_church RETURNS additional
-- preacher_id + preacher_name columns so the consumer can attribute hits
-- across a multi-preacher church corpus.

CREATE OR REPLACE FUNCTION public.match_units_for_church(
  p_preacher_ids uuid[],
  p_query_embedding vector,
  p_query_text text DEFAULT NULL::text,
  p_match_count integer DEFAULT 4,
  p_rhetorical_functions text[] DEFAULT NULL::text[],
  p_primary_text text DEFAULT NULL::text,
  p_keyword_weight double precision DEFAULT 0.4,
  p_doctrinal_loci text[] DEFAULT NULL::text[]
)
RETURNS TABLE(
  unit_id uuid,
  sermon_id uuid,
  sermon_title text,
  sermon_date date,
  primary_text text,
  unit_index integer,
  rhetorical_function text,
  illustration_type text,
  doctrinal_loci text[],
  content text,
  summary text,
  similarity double precision,
  keyword_score double precision,
  final_score double precision,
  preacher_id uuid,
  preacher_name text
)
LANGUAGE plpgsql
STABLE
AS $function$
BEGIN
  PERFORM set_config('hnsw.iterative_scan', 'relaxed_order', true);
  PERFORM set_config('hnsw.max_scan_tuples', '20000', true);

  RETURN QUERY
  WITH candidates AS (
    SELECT
      u.id AS u_id,
      (u.embedding <=> p_query_embedding) AS distance
    FROM units u
    JOIN sermons s ON s.id = u.sermon_id
    WHERE s.preacher_id = ANY(p_preacher_ids)
      AND u.embedding IS NOT NULL
      AND (p_rhetorical_functions IS NULL OR u.rhetorical_function = ANY(p_rhetorical_functions))
      AND (p_primary_text IS NULL OR s.primary_text ILIKE '%' || p_primary_text || '%')
      AND (p_doctrinal_loci IS NULL OR u.doctrinal_loci && p_doctrinal_loci)
    ORDER BY u.embedding <=> p_query_embedding
    LIMIT GREATEST(100, p_match_count * 5)
  ),
  scored AS (
    SELECT
      u.id AS unit_id,
      s.id AS sermon_id,
      s.title AS sermon_title,
      s.date AS sermon_date,
      s.primary_text AS primary_text,
      u.unit_index,
      u.rhetorical_function,
      u.illustration_type,
      u.doctrinal_loci,
      u.content,
      u.summary,
      (1 - c.distance)::FLOAT AS similarity,
      CASE
        WHEN p_query_text IS NULL OR length(trim(p_query_text)) = 0 THEN 0.0::FLOAT
        ELSE ts_rank(u.content_tsv, websearch_to_tsquery('english', p_query_text))::FLOAT
      END AS keyword_score,
      s.preacher_id AS preacher_id,
      pr.name AS preacher_name
    FROM candidates c
    JOIN units u ON u.id = c.u_id
    JOIN sermons s ON s.id = u.sermon_id
    JOIN preachers pr ON pr.id = s.preacher_id
  )
  SELECT
    scored.unit_id, scored.sermon_id, scored.sermon_title, scored.sermon_date,
    scored.primary_text, scored.unit_index, scored.rhetorical_function,
    scored.illustration_type, scored.doctrinal_loci, scored.content,
    scored.summary,
    scored.similarity,
    scored.keyword_score,
    ((1 - p_keyword_weight) * scored.similarity
     + p_keyword_weight * LEAST(scored.keyword_score * 5.0, 1.0))::FLOAT AS final_score,
    scored.preacher_id,
    scored.preacher_name
  FROM scored
  ORDER BY final_score DESC
  LIMIT p_match_count;
END;
$function$;


CREATE OR REPLACE FUNCTION public.find_sermon_by_title_in_text_church(
  p_preacher_ids uuid[],
  p_text text
)
RETURNS uuid
LANGUAGE sql
STABLE
AS $function$
  WITH normalized AS (
    SELECT lower(trim(p_text)) AS q
  ),
  matches AS (
    SELECT
      s.id,
      s.title,
      CASE
        -- Case 1: title is a substring of the question (strongest)
        WHEN strpos((SELECT q FROM normalized), lower(s.title)) > 0
          THEN 1000 + length(s.title)
        -- Case 3: exact match
        WHEN lower(s.title) = (SELECT q FROM normalized)
          THEN 900 + length(s.title)
        -- Case 2: question is a prefix of the title (LLM truncated)
        WHEN lower(s.title) LIKE (SELECT q FROM normalized) || '%'
          AND length((SELECT q FROM normalized)) >= 5
          THEN 500 + length((SELECT q FROM normalized))
        -- Case 4: question is a substring of the title (somewhere in middle)
        WHEN strpos(lower(s.title), (SELECT q FROM normalized)) > 0
          AND length((SELECT q FROM normalized)) >= 8
          THEN 200 + length((SELECT q FROM normalized))
        ELSE 0
      END AS score
    FROM sermons s
    WHERE s.preacher_id = ANY(p_preacher_ids)
      AND length(s.title) >= 5
  )
  SELECT id FROM matches WHERE score > 0
  ORDER BY score DESC, length(title) DESC
  LIMIT 1;
$function$;
