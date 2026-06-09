# Sermon Steward MCP — Architecture

**Status:** Live, deployed 2026-06-08.
**Author of the path we landed on:** worked out through a long debugging session;
documented here so the next contributor (or our future selves) doesn't have to
re-derive it.

## TL;DR

Each pastor's sermon corpus is exposed at a public URL like
`https://corpus-mcp.chris-386.workers.dev/p/<slug>` — for example
`/p/chris-oswald` or `/p/ricky-alcantar`. Anyone can add that URL as a
Model Context Protocol connector in Claude Desktop / Cowork. No
account, no token, no OAuth dance. Inside Claude / Cowork, that
connector exposes one tool, `ask_corpus`, scoped to the named
preacher's sermons.

A directory page at `sermonsteward.com/pastors` lists every connectable
pastor with three install paths per card: copy the URL into Cowork's
connector UI, copy a prompt that has Cowork edit your config file for
you, or paste a JSON snippet directly into your `claude_desktop_config.json`.

This shape is the right one for this product because sermon material
**isn't private** — it's a public utterance the pastor wants spread.
The hard requirement isn't access control; it's **accurate attribution**.
That's a data-integrity property, not a security property, and we
enforce it through joined preacher data in every response.

## How we got here — what didn't work

We tried three other shapes first. The notes are kept here as a
warning to future iterations.

### Attempt 1: Per-pastor bearer tokens via `mcp_tokens`

Each pastor got an `sst_*` token; the token mapped to a `preacher_id`
via the `mcp_tokens` table; downstream code scoped queries by that
preacher_id. Worked, but:

- **Onboarding required an admin step.** Issue token, securely
  transmit it to the pastor, walk them through pasting it into a
  config file. Non-tech pastors stalled at step one.
- **Tokens are credentials with no protective purpose** — sermons are
  public; the "secret" was just a scope-selector dressed as a
  credential.

This path still works (Chris's machine uses it) and we kept it for
backward compatibility. But it's not the path we'd build today.

### Attempt 2: OAuth 2.1 + PKCE + DCR + magic-link sign-in

We built the full OAuth flow — server-side everything works when
curl'd directly. **It doesn't work end-to-end on Cowork+`mcp-remote`.**
The `mcp-remote` proxy that Cowork uses to talk to remote HTTP MCP
servers spawns a short-lived loopback listener on `localhost:5051`,
opens a browser tab to our `/oauth/authorize`, and expects the redirect
to arrive within that listener's lifetime. The magic-link round-trip
exceeds it. Worse, Cowork was spawning multiple parallel
`mcp-remote` processes that fought for the port; whichever lost the
bind had no listener, but kept running, and Cowork respawned them in a
loop that flooded Chrome with sign-in tabs.

We chased this for a full session. The bug is in the
Cowork-managed `mcp-remote` lifecycle, not in our Worker. **Until that's
fixed, OAuth-via-Cowork is unusable.** The Worker code is intact and
correct; if/when the proxy bug is solved, OAuth would unlock submission
to Anthropic's Connectors Directory (which requires it).

### Attempt 3: `claude://install-mcp?…` deep-link install URLs

A "GPT Store"-style one-click install button on each pastor card,
implemented as a `claude://install-mcp?...` URL scheme handoff. Browser
recognized the scheme and handed it to Cowork; Cowork has no
documented handler for that URL with our parameter shape, so the
click did nothing visible. Removed.

This MAY become viable if Anthropic ships a real install-URL spec
later. For now, it's a dead end.

### Attempt 4 (the one we landed on): URL-path-scoped public MCP

Detailed below.

## The design

```
┌──────────────────────────────────────────────────────────────────────┐
│  Visitor lands on sermonsteward.com/pastors                          │
│  Sees Chris's card + Ricky's card + future cards                     │
│  Picks one, clicks "Copy connector URL"                              │
└────────┬─────────────────────────────────────────────────────────────┘
         │
         │ Visitor opens Cowork → Customize → Connectors → Add Custom
         │ Pastes URL: https://corpus-mcp.chris-386.workers.dev/p/<slug>
         ▼
┌──────────────────────────────────────────────────────────────────────┐
│  Cowork registers the connector. POSTs JSON-RPC to that URL.         │
│  (No auth header.)                                                   │
└────────┬─────────────────────────────────────────────────────────────┘
         │
         │ initialize / tools/list / prompts/list / tools/call ask_corpus
         ▼
┌──────────────────────────────────────────────────────────────────────┐
│  Cloudflare Worker (corpus-mcp)                                      │
│  1. Path match /p/:slug → call authenticateBySlug(slug)              │
│  2. Look up preachers WHERE slug = :slug → AuthContext               │
│  3. Dispatch to ask_corpus, prompts, etc.                            │
│  4. Voyage embedding + Supabase match_units_for_preacher RPC         │
│  5. Return results joined with preacher name (attribution baked in)  │
└──────────────────────────────────────────────────────────────────────┘
```

**No token. No OAuth. The slug in the URL path is the identity
selector** — not a credential.

## Why this is the right shape

Three observations from many hours of arguing with the alternatives:

1. **The data wants to be public.** Sermons are utterances the pastor
   already preached to a congregation, posted to a church website,
   and put on YouTube. Restricting access to "the pastor who preached
   it" actively works against the product's mission.

2. **Attribution is the actual hard requirement.** "Don't let a query
   confuse Ricky's sermons for Chris's." That's enforced by foreign
   keys: every `sermons` row has a `preacher_id`, every API response
   joins through to `preacher.name`, every citation is correct by
   construction. Wrong attribution isn't possible as long as the FKs
   are sound.

3. **A token would have been scope dressed as a credential.** The MCP
   protocol expects an auth identifier, so we packaged a `preacher_id`
   inside a fake credential (`mcp_tokens.token_hash`). With the
   URL-path shape, the same `preacher_id` arrives via path resolution
   — same outcome, no fake credential.

## Components

### The Worker — `corpus-mcp/`

Cloudflare Worker. Routes:

| Path | Method | Auth | Purpose |
|---|---|---|---|
| `GET /` | GET | none | Human-readable landing page |
| `GET /p/:slug` | GET | none | Per-pastor landing page |
| `POST /p/:slug` | POST | **slug-based** | MCP JSON-RPC for that pastor |
| `POST /` (legacy) | POST | `sst_*` bearer | MCP JSON-RPC scoped by token's preacher_id |
| `POST /` (legacy) | POST | `sst_oauth_*` bearer | OAuth path (server works; broken end-to-end via Cowork's mcp-remote) |
| `GET /.well-known/oauth-*` | GET | none | OAuth discovery (kept for future) |
| `POST /oauth/*` | POST | flow-dependent | OAuth dance (works server-side, not deployable as primary UX yet) |

All three auth paths produce the same downstream `AuthContext` shape
(`{ preacher_id, preacher_name, token_name? }`), so the tool and
prompt handlers don't care how identity was resolved.

Key code:
- `src/auth.ts` → `authenticateBySlug(slug, env)`
- `src/index.ts` → path matcher for `/p/:slug`
- `src/tools/ask-corpus.ts` → scoped by `auth.preacher_id`
- `src/prompts/index.ts` → filtered by `auth.preacher_name`

### The Supabase column — `preachers.slug`

Added 2026-06-08 via migration `add_slug_to_preachers`. URL-safe
identifier per preacher. Auto-generated from `name` (lowercased,
non-alphanumerics → dashes). Manually disambiguated where names
collide:

- `greg-dirnberger-cog` / `greg-dirnberger-pcc` (one at Cross of Grace,
  one at Providence Community)
- `steve-whitacre-cog` / `steve-whitacre-pcc` (same)

Unique constraint enforces no two preachers share a slug.

### The directory page — `sermon-steward/_src/pastors.njk`

Eleventy template. Reads `_src/_data/pastors.json` and renders one
card per entry. Each card has three "Try this" install paths with
copy-to-clipboard buttons. The page is at `/pastors/` on the public
site.

Data file shape (`pastors.json`):

```json
{
  "mcp_base_url": "https://corpus-mcp.chris-386.workers.dev",
  "preachers": [
    {
      "name": "Chris Oswald",
      "slug": "chris-oswald",
      "church": "Providence Community Church",
      "location": "Lenexa, Kansas",
      "tradition": "Reformed, Sovereign Grace",
      "sermon_count": 446,
      "voice_prompt": "chris-oswald-voice",
      "bio": "…"
    }
  ]
}
```

(Some of these fields aren't rendered today but are kept in data so
future card variants can use them without a schema change.)

## The three install paths

A pastor's card shows three ways to register the connector. They all
reach the same end state — the same `mcp-remote` shim pointing at the
same `/p/<slug>` URL. Multiple paths exist because:

1. **Try this first — Copy connector URL.** Cowork's "Add custom
   connector" UI accepts a bare URL paste. This is the simplest
   manual path and works on every Cowork version. Three clicks.
2. **Try this — Copy Cowork install prompt.** A pre-substituted prompt
   that, pasted into a Cowork chat, has Cowork's local-agent mode
   edit `claude_desktop_config.json` for the user. Best for pastors
   who'd rather paste than navigate UI.
3. **Try this — Manual JSON setup.** Raw JSON snippet for users who
   prefer editing the config file directly, or for whom the first
   two paths don't work for any reason.

These exist because Anthropic's MCP install UX is still maturing.
When the official one-click install ships and Cowork supports it
reliably, paths 2 and 3 can collapse — the URL paste remains the
primitive.

## Operational checklist — adding a new pastor

1. **Add or confirm a `preachers` row.** Pastors imported by the
   pipeline already have one; new pastors need an explicit insert.
   `auth_user_id` and `church_id` are optional for the read-only flow.
2. **Run `slug` generation if it's a new row.** The migration's
   `UPDATE` already populated existing rows; new inserts can default
   the slug via a trigger or be set manually:

   ```sql
   UPDATE preachers
   SET slug = trim('-' from lower(regexp_replace(name, '[^a-zA-Z0-9]+', '-', 'g')))
   WHERE slug IS NULL;
   ```

   For name collisions, manually disambiguate with a church short-code
   suffix.
3. **Add an entry to `sermon-steward/_src/_data/pastors.json`.**
   At minimum: `name`, `slug`, `church`, `location`. Other fields
   surface in future card variants.
4. **(Optional) Add a voice prompt.** Drop a new file under
   `corpus-mcp/src/prompts/` and register it in `src/prompts/index.ts`
   with `preacherName` matching the `preachers.name` value exactly.
   Without a voice prompt, the connector still works; it just doesn't
   offer pastor-specific framing.
5. **`npm run build` + `git push`** the `sermon-steward` repo.
   Cloudflare Pages auto-deploys.

No Worker redeploy needed unless you change MCP protocol behavior.
Slug resolution is a DB lookup; new preachers + new slugs just work.

## What this doesn't solve

- **Anthropic Connectors Directory submission.** That requires OAuth,
  a privacy policy, branding assets, and polished docs. The OAuth-via-
  Cowork bug blocks this independently. See
  [OAUTH-DEPLOY-PLAN.md](OAUTH-DEPLOY-PLAN.md) for the deferred state.
- **In-Cowork discovery.** Users today find the connector via the
  sermonsteward.com directory, not via Cowork's connector search.
  When the Anthropic Directory submission lands, in-Cowork discovery
  becomes available.
- **Per-pastor private material.** `preacher_analysis` (candid AI
  writeups about each pastor) and `illustration_rewrites` (draft book
  material) should not be public-readable. We have not tightened
  their RLS — current `anon USING (true)` policies need to be replaced
  with per-pastor authenticated reads. This is the remaining piece of
  the F2 work.
- **Write surface.** Everything described here is read-only. If pastors
  eventually want to upload sermons or edit their voice prompt via a
  web UI, that needs its own auth path (likely Supabase Auth on the
  website, not on the MCP).

## Pointers

- Setup guide for pastors (Cowork-prompt flavor):
  [docs/setup-cowork-prompt.md](docs/setup-cowork-prompt.md)
- Setup guide for pastors (manual config flavor):
  [docs/setup-claude-desktop.md](docs/setup-claude-desktop.md)
- OAuth design (deferred until Cowork+mcp-remote bug is solved):
  [OAUTH-DESIGN.md](OAUTH-DESIGN.md)
- OAuth deploy plan (also deferred):
  [OAUTH-DEPLOY-PLAN.md](OAUTH-DEPLOY-PLAN.md)
- Public directory page source:
  `sermon-steward/_src/pastors.njk` + `_src/_data/pastors.json`
- Worker source: `corpus-mcp/src/`
