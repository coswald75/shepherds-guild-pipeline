# Shepherd's Guild — Sermon Decomposition Pipeline v3

## Setup

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure environment
cp env.template .env
# Edit .env with your API keys and Supabase credentials

# 3. Place the spec file next to pipeline.py
# sermon-decomposition-spec-v3.md should be in the same directory

# 4. Create the Supabase schema
# Run supabase-schema-v3.sql in your Supabase SQL editor
```

## Usage

### Single sermon (full pipeline: decompose → embed → ingest)
```bash
python pipeline.py decompose sermon.txt --preacher "John MacArthur"
```

### Single sermon (decompose only — for QA review before ingesting)
```bash
python pipeline.py decompose sermon.txt --preacher "John MacArthur" --dry-run
```

### Batch processing (all .txt files in a folder)
```bash
python pipeline.py batch ./transcripts/macarthur/ --preacher "John MacArthur"
```

### Guild Hall canonical preachers
```bash
python pipeline.py batch ./transcripts/spurgeon/ --preacher "Charles Spurgeon" --canonical
```

### Ingest a previously decomposed JSON (skip decomposition, just embed + write to DB)
```bash
python pipeline.py ingest output/sermon_decomposed.json --preacher "John MacArthur"
```

## File Structure

```
pipeline/
├── pipeline.py                         # Main pipeline script
├── sermon-decomposition-spec-v3.md     # The v3 decomposition spec (system prompt)
├── supabase-schema-v3.sql              # Database schema
├── requirements.txt                    # Python dependencies
├── env.template                        # Environment variable template
├── .env                                # Your actual keys (git-ignored)
└── output/                             # Auto-created
    ├── sermon_decomposed.json          # Decomposition output (one per sermon)
    └── batch_report_*.json             # Batch processing reports
```

## Pipeline Stages

### Stage 1: Decompose
- Sends transcript to Claude Sonnet 4.5 with the v3 spec as system prompt
- Receives structured JSON conforming to the decomposition spec
- Saves JSON to `output/` directory (always, for audit trail and QA)
- Attaches pipeline metadata: model, token counts, cost, timestamp

### Stage 2: Embed
- Sends each unit's `content` field to Voyage 3.5
- Generates 1024-dimensional embeddings for semantic search
- Uses `input_type="document"` for optimal retrieval performance
- Batches units (32 per API call) with rate limiting

### Stage 3: Ingest
- Creates preacher record if not exists
- Inserts sermon with all sermon-level metadata
- Inserts units with embeddings and structured metadata
- Inserts citations (Tier 1 + Tier 2), quotations (Tier 3), and BT moves
- All foreign keys properly linked

## Cost Estimates (March 2026 pricing)

| Component | Cost per sermon |
|-----------|----------------|
| Decomposition (Sonnet 4.5) | ~$0.30-0.40 |
| Embeddings (Voyage 3.5) | ~$0.01 |
| Supabase | Free tier / negligible |
| **Total** | **~$0.31-0.41** |

For a 30-sermon corpus: ~$10-12
For the full Guild Hall (330 sermons): ~$100-135

## QA Workflow

1. Run with `--dry-run` first to get decomposition JSON without database writes
2. Review the JSON — check rhetorical function assignments, citation tier accuracy, BT moves
3. If quality is good, run `ingest` command to embed and write to database
4. If quality needs work, adjust the spec or transcript and re-decompose
