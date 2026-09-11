# T1 nearly-free sermon ingest (POC)

Opt-in companion to the production **T2** path (`pipeline.py` / `weekly_ingest.py`).
This does **not** replace, delete, or change default weekly/paid ingest.

| Tier | Job | Default spend |
|---|---|---|
| **T0 Acquire** | Grab source text/audio + durable ids | $0 if text exists; AssemblyAI STT only when audio has no transcript (existing scraper / weekly_ingest) |
| **T1 Structure** | Chapters/chunks + searchable index | **$0** on text (local chunker + keyword index). Optional Voyage `--embed` is fractions of a cent |
| **T2 Decompose** | Existing Anthropic Sonnet unit graph | **~$0.21–0.41** per sermon (see `pipeline-README.md`) |

Promote a T1 sermon to T2 only when a paid seat / product event funds it.

## Why not AssemblyAI chaptering?

The hypothesis was: reuse AssemblyAI (already in this stack for STT) for cheap
chapters, and skip STT when text already exists.

**Rejected as the default T1 chunker** after checking current AssemblyAI docs/pricing:

1. **`auto_chapters` is deprecated** (Universal-2 only, **+$0.08/hr**, sunset
   **2026-09-15**). It 500s on Universal-3.5 Pro.
2. The documented replacement is **LLM Gateway** (Claude / GPT tokens). That is
   T2-class spend, not cents-per-sermon structure.
3. Chapters only exist if you already paid **STT** (~$0.15/hr Universal-2,
   ~$0.21/hr Universal-3.5 Pro). A 40-minute sermon is already **~$0.10–0.14**
   before any chapter add-on — fine for T0 when there is no text, fatal for
   unpaid bulk of *already-transcribed* libraries.
4. **Text-first corpora** (Ligonier / RC Sproul landing pages, church-site HTML)
   never go through AssemblyAI. Those are the unpaid-bulk case this POC exists for.

**What T1 uses instead:** a local chapterer (stdlib only):

1. Reuse sidecar chapters if T0 already attached them (`chapters` / `auto_chapters`
   with `headline`, `summary`, `start`/`end` ms).
2. Else split on markdown/HTML headings (`##`, `<h4>`, …).
3. Else split on oral discourse markers (`First,` / `Second,` / `Finally,`).
4. Else paragraph windows (~400 words) with character offsets.

Keyword inverted index is always built. Voyage embeddings are **opt-in**
(`--embed` + `VOYAGE_API_KEY`).

## How to run the POC (3–10 sermons, no secrets)

From the repo root, with the six committed fixtures (original test copy — CI
and a laptop without `.env` can run this):

```bash
# no ANTHROPIC_API_KEY, ASSEMBLYAI_API_KEY, or VOYAGE_API_KEY required
python t1_ingest.py batch fixtures/t1
```

That is six sermons. To add a few already-in-repo public transcripts *without*
changing production ingest:

```bash
python t1_ingest.py ingest fixtures/t1/heading-blessing.txt
python t1_ingest.py ingest sermon-transcripts/john-stott/the-son-john-1118.json --output t1_output
# optional: more files, still T1 only
python t1_ingest.py batch fixtures/t1 --limit 6
```

Search the cheap index:

```bash
python t1_ingest.py search "justification"
python t1_ingest.py search "sign of Jonah"
```

Print the cost model:

```bash
python t1_ingest.py cost
```

Run the unit tests (no network, no keys):

```bash
python -m pytest tests/test_t1_ingest.py -q
```

## Where artifacts land

Default output directory: **`t1_output/`** (gitignored, same idea as `output/`).

```
t1_output/
  run_report.json          # sermon count, $ estimate, APIs actually called
  index.json               # corpus keyword index + sermon catalog
  sermons/<slug>.json      # source text, chapters (offsets / timestamps), terms
  promote/<slug>.promote.json   # written by `t1_ingest.py promote` (stub)
```

Each `sermons/*.json` includes:

- `text` — cleaned source (HTML stripped when needed)
- `chapters[]` — `title`, `text`, `char_start` / `char_end`, optional `start_ms` / `end_ms`
- `index` — `keyword` or `voyage`
- `cost` — `usd_estimate` and `apis_called` (empty on the default path)
- `promote.command` — the existing T2 invoke line

Override the destination with `--output /tmp/t1-demo`.

## Cost model (T1 vs current T2)

Prices are public mid-2026 list rates, not a quote. T2 numbers match
`pipeline-README.md` (~$0.31–0.41 all-in).

| Path | APIs called | Typical $/sermon |
|---|---|---|
| **T1, text already available (default)** | none | **$0.00** |
| **T1 + `--embed`** | Voyage `voyage-3.5` on ~8–15 chunks | **~$0.0005** (Voyage is $0.06 / 1M tokens) |
| **T0 STT only** (no text, existing AssemblyAI job) | AssemblyAI transcribe | **~$0.10–0.14** for 40 min. This is *acquire*, not T1 structure |
| **T1 if we had used AssemblyAI `auto_chapters`** | STT + deprecated +$0.08/hr | **~$0.15–0.22** — misses the cents target and is sunsetting |
| **T2 production** | Anthropic Sonnet decompose + Voyage units | **~$0.21–0.41** (decompose is almost all of it) |
| **T2 + Haiku artifacts** | + 5 Haiku calls | + ~$0.03 |

Unpaid bulk (free public libraries, multi-decade church sites, Sermon Audit
horizon) should stay on T1 until a monetization event. Weekly paid customers
keep using `weekly_ingest.py` unchanged.

## Promote to T2 (stub)

```bash
python t1_ingest.py promote t1_output/sermons/<slug>.json
```

Writes a receipt under `t1_output/promote/` and prints the **existing** command:

```bash
python pipeline.py decompose "<source_path>" --preacher "<name>" --dry-run
```

The POC does **not** invoke that command. `--execute` still only writes the
receipt. When you are ready to spend, run `pipeline.py` / `pipeline_batch.py`
yourself. Do not add a second decompose client.

## Default behavior is unchanged

- `weekly_ingest.py weekly` still discover → AssemblyAI (if needed) → Anthropic
  batch → Voyage → Haiku → render → deploy.
- `pipeline.py decompose|batch|ingest` is untouched.
- T1 is a **separate entrypoint** (`t1_ingest.py`) and package (`t1/`).
  It refuses to import `pipeline.py` so Anthropic is never pulled in by accident.

## Layout

```
t1_ingest.py              # CLI
t1/                       # acquire, chunker, index, cost, promote
fixtures/t1/              # 6 sermons, no secrets
tests/test_t1_ingest.py
t1-README.md              # this file
```
