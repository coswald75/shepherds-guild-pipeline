# Analysis Pipeline & Dynamic Dashboard — Changelog

**Date:** March 14, 2026
**Session:** Claude Code working session with Chris Oswald

---

## Summary

Transformed the Shepherd's Guild dashboard from a single-preacher hardcoded showcase into a fully dynamic, multi-tenant system. Any pastor's sermon data can now be analyzed, stored, and rendered from a single HTML file by changing a URL parameter.

---

## Files Created

### `preacher_analysis_schema.sql`
- SQL migration for the `preacher_analysis` table in Supabase
- One row per preacher (upsert-friendly via `UNIQUE(preacher_id)`)
- Columns: `stats` (JSONB), `exemplar_matches` (JSONB), `hall_distinction` (JSONB), `growth_intro` (JSONB), `growth_areas` (JSONB), `latent_book` (JSONB), `quotes` (JSONB), plus metadata fields
- Includes commented-out RLS policy template for when auth is added
- **Status:** Deployed to Supabase (table exists and has Chris Oswald's data)

### `generate_analysis.py`
Four-step pipeline that generates the entire Analysis layer for a pastor's dashboard:

1. **AGGREGATE** — Queries Supabase for all decomposed sermon data. Computes:
   - Theological fingerprint (doctrinal loci counts)
   - Rhetorical register distribution (logos/pathos/ethos/etc. as percentages)
   - Homiletical method breakdown (exposition/theological_claim/application/etc.)
   - Illustration density, types, and counts
   - Application count, per-sermon average, and specificity breakdown
   - Quotation counts and top quoted authors
   - Series analysis (for latent book detection)

2. **COMPARE** — Fetches stats for all canonical (Guild Hall) preachers and ranks by weighted similarity:
   - Rhetorical register similarity (25%)
   - Theological fingerprint similarity (25%)
   - Homiletical method similarity (20%)
   - Illustration profile similarity (15%)
   - Expository rate comparison (15%)
   - Generates specific, named REASONS for each match (not just percentages)

3. **GENERATE** — Calls Claude API (Sonnet) with:
   - A style guide extracted from Chris's hand-written analysis prose
   - Few-shot examples of correct output for each section
   - All computed stats and comparison data
   - Produces: `hall_distinction`, `growth_intro`, `growth_areas` (3), `latent_book` (with evidence signals, evidence cards, secondary candidate)

4. **STORE** — Upserts everything into `preacher_analysis` table

**Usage:**
```bash
# Dry run (stdout + output/ file, no DB write)
python3 generate_analysis.py --preacher "Chris Oswald" --dry-run

# Live (writes to Supabase)
python3 generate_analysis.py --preacher "Chris Oswald"

# All customer preachers
python3 generate_analysis.py --all
```

**Key design decisions:**
- Style guide and few-shot examples are embedded in the script to preserve the hand-crafted prose voice
- Uses `load_dotenv(override=True)` because the shell environment had an empty `ANTHROPIC_API_KEY` that was blocking the `.env` file value
- Batches Supabase queries (20 sermon IDs, 50 unit IDs per request) to stay under URL length limits
- Temperature set to 0.7 for prose generation (creative but grounded)

---

## Files Modified

### `showcasev3.html`
Refactored from hardcoded single-preacher dashboard to fully dynamic multi-tenant dashboard.

**What changed:**

1. **Preacher ID is now dynamic:**
   - Reads `?id=UUID` from URL parameter
   - Falls back to Chris Oswald's UUID (`9c6f8d69-de55-45db-ac60-0fe6d0cfff59`) if none provided
   - `const PREACHER_ID = new URLSearchParams(window.location.search).get('id') || DEFAULT_PREACHER_ID`

2. **New async data loading on page init:**
   - `loadPreacherInfo()` — fetches name + church from `preachers` table (with foreign key join to `churches`)
   - `loadAnalysis()` — fetches the full `preacher_analysis` row

3. **Sidebar is now dynamic:**
   - Avatar initials computed from preacher name
   - Name, church, and mini-stats (sermon count, units, expository %, illustration count) all populated from Supabase data
   - Nav badges (illustration count, quotes count, sermons count) set dynamically

4. **Analysis sections replaced with render functions:**
   - `renderOverview()` — Theological Fingerprint bars, Homiletical Method grid, Rhetorical Register bars, Hall Distinction box
   - `renderExemplar()` — 3 exemplar match cards with percentages, names, ranks, and reason bullets
   - `renderGrowth()` — Growth intro box + 3 growth area cards with metrics and recommendations
   - `renderLatentBook()` — Book hero, evidence signals, evidence cards, and secondary candidate

5. **Quotes are now dynamic:**
   - `ALL_QUOTES` array populated from `preacher_analysis.quotes` JSONB instead of hardcoded array

6. **Page title set dynamically:**
   - `document.title = 'Archive Index & Analysis · ' + name + ' · Shepherd's Guild'`

**What was NOT changed:**
- All CSS (zero changes)
- HTML structure and class names (preserved exactly)
- Illustrations JS (already dynamic)
- Sermons table JS (already dynamic)
- Search Archive JS (already dynamic)
- Add-on sections (Herald, VoxPrompt, Hall Query, PrepKing)

### `.env`
- `ANTHROPIC_API_KEY` was empty — copied from `pipeline/.env` (the original pipeline directory)

---

## Database Changes

### Table created: `preacher_analysis`
- Via `preacher_analysis_schema.sql` run in Supabase SQL Editor

### Row inserted: Chris Oswald's analysis
- Via `python3 generate_analysis.py --preacher "Chris Oswald"`
- 48,841 bytes stored
- Exemplar matches: Kevin DeYoung (84%), Voddie Baucham (79%), Tim Keller (78%)

### Row inserted: `churches` table
- "Providence Community Church" (id: `c121e66b-777d-4568-89d3-9ceea258061b`)

### Row updated: `preachers` table
- Chris Oswald's `church_id` set to Providence Community Church

---

## How to Onboard a New Pastor

1. **Scrape sermons** (OpenClaw bot — already automated overnight)
2. **Run decomposition pipeline** (already automated):
   ```bash
   python3 pipeline.py batch ./transcripts/new-pastor/ --preacher "Brad Jones"
   ```
3. **Create church + preacher in Supabase** (if not already there):
   ```sql
   INSERT INTO churches (name) VALUES ('First Baptist Springfield');
   INSERT INTO preachers (name, church_id, is_canonical) VALUES ('Brad Jones', '<church-uuid>', false);
   ```
4. **Generate analysis:**
   ```bash
   python3 generate_analysis.py --preacher "Brad Jones"
   ```
5. **Give them their URL:**
   ```
   theshepherdsguild.com/showcasev3.html?id=<their-preacher-uuid>
   ```
6. **Weekly updates:** When new sermons are ingested, re-run `generate_analysis.py` to refresh stats and prose.

---

## Architecture After This Session

```
┌──────────────┐     ┌──────────────┐     ┌──────────────────┐
│  OpenClaw    │────>│  pipeline.py │────>│    Supabase      │
│  (scraping)  │     │  (decompose) │     │                  │
└──────────────┘     └──────────────┘     │  sermons         │
                                          │  units           │
                     ┌──────────────┐     │  illustrations   │
                     │ generate_    │────>│  quotations      │
                     │ analysis.py  │     │  preacher_analysis│
                     └──────────────┘     └────────┬─────────┘
                                                   │
                                          ┌────────▼─────────┐
                                          │  showcasev3.html │
                                          │  (single file,   │
                                          │   multi-tenant)  │
                                          └──────────────────┘
```

---

## What's Still Ahead

1. **Landing page** — marketing site explaining the product
2. **Supabase Auth** — pastor login so they don't need to know their UUID
3. **Row Level Security** — each pastor can only see their own data
4. **Deployment** — host showcasev3.html on Netlify/Vercel/similar
5. **Automated weekly re-analysis** — cron job or scheduled task to re-run `generate_analysis.py --all` after new sermons are ingested
