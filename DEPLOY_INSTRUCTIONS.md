# Deployment Instructions for showcasev4.html

## For: Local deployment bot with Cloudflare access
## Date: March 15, 2026

---

## WHAT TO DEPLOY

Deploy the single file:

```
/Users/dad/shepherds-guild/pipeline copy 2/showcasev4.html
```

This file should be placed at:

```
theshepherdsguild.com/showcasev4.html
```

So the live URL becomes: `https://theshepherdsguild.com/showcasev4.html`

---

## WHAT THIS FILE IS

A single self-contained HTML file (~2094 lines) — all CSS, JS, and markup in one file. No build step, no dependencies, no npm, no framework. It loads two external resources:

1. **Google Fonts** (Cormorant Garamond, DM Sans, JetBrains Mono) — via CDN link in `<head>`
2. **Supabase** — via REST API calls to `https://twbunmbzyqcqzgffdrib.supabase.co` using an anon key already embedded in the JS

That's it. No other files, no images, no assets to upload alongside it.

---

## WHAT'S NEW IN V4 (vs V3)

1. **PreFlight Check** — new view under Analysis in the sidebar. Pastors paste a sermon draft and get it analyzed against their coaching benchmarks. Calls a Supabase Edge Function (`/functions/v1/preflight-check`). Note: the edge function may not be deployed yet — the UI gracefully handles this with an error message.
2. **Sermon Viewer Modal** — clicking any illustration card opens a full-screen modal showing the complete sermon manuscript with rhetorical function tags. Close via × button or clicking the backdrop.
3. **Bug fixes** — Growth Area metrics now render correctly (was broken in V3). Hall distinction stat renders correctly. Latent book secondary metrics render correctly.

---

## DO NOT

- **DO NOT modify the file contents.** No minification, no prettification, no "optimization." Deploy exactly as-is.
- **DO NOT rename it.** It must be `showcasev4.html`. The URL path matters.
- **DO NOT remove or replace any existing files on the site** — especially:
  - `index.html` (landing page)
  - `showcasev3.html` (previous version — keep it live, existing links may point to it)
  - `/showcasev2/` directory (previous version, may still be linked)
  - Any other existing pages or assets
- **DO NOT change any DNS, SSL, or Cloudflare settings.**
- **DO NOT modify caching headers** — the file should use standard Cloudflare defaults.
- **DO NOT set up any server-side processing** — this is purely static HTML served as-is.

---

## DEPLOYMENT METHOD

This depends on how `theshepherdsguild.com` is currently hosted on Cloudflare:

### If Cloudflare Pages (drag-and-drop upload):
1. Go to the Cloudflare dashboard → Workers & Pages → the shepherd's guild project
2. Create a new deployment
3. Upload `showcasev4.html` to the root of the project alongside existing files
4. Deploy

### If Cloudflare Pages (git-connected):
1. Add `showcasev4.html` to the root of the connected git repository
2. Commit and push
3. Cloudflare Pages will auto-deploy

### If using Wrangler CLI:
```bash
mkdir -p /tmp/sg-deploy
cp "/Users/dad/shepherds-guild/pipeline copy 2/showcasev4.html" /tmp/sg-deploy/
# Also copy any existing site files that should remain (index.html, showcasev3.html, etc.)
npx wrangler pages deploy /tmp/sg-deploy --project-name <project-name>
```

---

## VERIFICATION

After deployment, confirm:

1. `https://theshepherdsguild.com/showcasev4.html` loads
2. The sidebar shows "Chris Oswald" and "Providence Community Church"
3. The stats show: 79 sermons, 2,869 units, 81% expository, 258 illustrations
4. Click "Exemplar Similarities" in the sidebar — should show Kevin DeYoung, Voddie Baucham, Tim Keller with match percentages
5. Click "Growth Areas" — each growth area should display metric boxes with numbers (e.g., "26 CHRIS" and "27 FERGUSON" for the first one)
6. Click "PreFlight Check" — should show a textarea with "Paste your sermon text here..." placeholder and a "RUN PRE-FLIGHT CHECK" button
7. Click "Illustrations" — cards should appear. Click any card — a modal should open showing the full sermon manuscript with unit-by-unit breakdown
8. All data loads from Supabase (not hardcoded) — if the numbers above appear, it's working

---

## CONTEXT (for the bot's understanding)

This is a pastor analytics dashboard. Each pastor gets the same HTML file with a different URL parameter:

- Chris Oswald: `showcasev4.html` (no param needed — he's the default)
- Future pastors: `showcasev4.html?id=<their-uuid>`

The file reads all data from Supabase at runtime. There is nothing pastor-specific in the HTML itself. One file serves all customers.

The formatting and layout have been carefully refined and approved. Every pixel is intentional. Do not attempt to improve, optimize, or reformat anything.
