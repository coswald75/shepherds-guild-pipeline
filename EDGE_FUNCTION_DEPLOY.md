# Deploying the PreFlight Check Edge Function

## What This Is

A Supabase Edge Function that powers the PreFlight Check feature in the dashboard. When a pastor pastes a sermon draft and clicks "Run Pre-Flight Check," the dashboard calls this function, which:

1. Fetches the pastor's coaching benchmarks from Supabase
2. Sends the sermon + benchmarks to Claude for analysis
3. Returns structured JSON with grades, benchmark scores, and recommendations

## Prerequisites

1. **Supabase CLI** installed: `npm install -g supabase`
2. **Supabase project** linked (you already have one at `twbunmbzyqcqzgffdrib`)
3. **Anthropic API key** — same one used in your `.env`

## Step-by-Step Deployment

### 1. Login to Supabase CLI

```bash
supabase login
```

This opens a browser for authentication.

### 2. Link your project

```bash
cd "/Users/dad/shepherds-guild/pipeline copy 2"
supabase link --project-ref twbunmbzyqcqzgffdrib
```

### 3. Set the required secrets

The edge function needs two environment variables:

```bash
supabase secrets set ANTHROPIC_API_KEY="your-anthropic-api-key-here"
```

Note: `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` are automatically available inside edge functions — you do NOT need to set them.

### 4. Deploy the function

```bash
supabase functions deploy preflight-check --no-verify-jwt
```

The `--no-verify-jwt` flag is needed because the dashboard calls this function using the anon key (not a user JWT). The function itself validates the request body.

### 5. Verify

```bash
curl -X POST "https://twbunmbzyqcqzgffdrib.supabase.co/functions/v1/preflight-check" \
  -H "Content-Type: application/json" \
  -H "apikey: YOUR_SUPABASE_ANON_KEY" \
  -H "Authorization: Bearer YOUR_SUPABASE_ANON_KEY" \
  -d '{"preacher_id": "9c6f8d69-de55-45db-ac60-0fe6d0cfff59", "sermon_text": "This is a test sermon with enough words to pass the minimum threshold. We are testing the edge function deployment. The function should return a JSON analysis of this text against the coaching benchmarks stored in Supabase. This needs to be at least one hundred words to work properly so I am adding more content here to ensure the test goes through correctly and the Claude API receives enough context."}'
```

If it returns JSON with `overall_grade`, `benchmark_scores`, etc. — it's working.

## File Location

```
supabase/functions/preflight-check/index.ts
```

## What It Costs

Each PreFlight Check call uses approximately:
- ~2,000-4,000 input tokens (prompt + sermon text)
- ~1,000-2,000 output tokens (JSON response)
- Model: claude-sonnet-4-5-20250929
- Estimated cost: ~$0.02-0.04 per check

## Troubleshooting

**"ANTHROPIC_API_KEY not configured"** — Run `supabase secrets set ANTHROPIC_API_KEY="..."` again.

**"No analysis found"** — The preacher hasn't had `generate_analysis.py` run yet. Run it first.

**CORS errors in browser** — The function includes CORS headers for `*`. If still failing, check the Supabase dashboard → Edge Functions → Logs.

**Timeout** — Claude API calls can take 10-30 seconds. Supabase Edge Functions have a 60-second timeout by default, which should be sufficient.

## DO NOT

- Do not hardcode any API keys in the function file — they're read from environment via `Deno.env.get()`
- Do not modify the prompt template without also updating `preflight_check.py` (they should stay in sync)
- Do not change the function name — the dashboard calls `/functions/v1/preflight-check` specifically
