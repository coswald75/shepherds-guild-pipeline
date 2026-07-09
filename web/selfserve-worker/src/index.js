/**
 * Sermon Steward — "Try it" self-serve Worker
 * ─────────────────────────────────────────────────────────────────────────
 * Public landing page (no token) where a pastor drops one MP3 + name/church/
 * email. The file is streamed to R2 and a `self_serve_jobs` row is created with
 * status='pending'. A local poller then runs the full ingest and emails the
 * report. This Worker does NOT run the pipeline — it's just the front door.
 *
 * Routes:
 *   GET  /                → landing page (HTML)
 *   POST /api/submit      → multipart/form-data {name, church, email, file}
 *
 * Bindings (wrangler.toml):
 *   env.AUDIO_BUCKET           R2 bucket (sermon-steward-audio)
 *   env.R2_PUBLIC_BASE         https://sermons-cdn.sermonsteward.com
 *   env.SUPABASE_URL / SUPABASE_SERVICE_KEY
 *   env.MAX_UPLOAD_MB / RATE_PER_DAY
 */

export default {
  async fetch(request, env) {
    try {
      const url = new URL(request.url);
      if (request.method === "GET" && url.pathname === "/") {
        return new Response(PAGE_HTML, {
          headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" },
        });
      }
      if (request.method === "POST" && url.pathname === "/api/submit") {
        return await handleSubmit(request, env);
      }
      return new Response("Not found", { status: 404 });
    } catch (err) {
      console.error("Worker error:", err);
      return json({ ok: false, error: err.message || "Internal error" }, 500);
    }
  },
};

// ───────────────────────────────────────────────────────────────────────────

async function handleSubmit(request, env) {
  const form = await request.formData();
  const name = (form.get("name") || "").toString().trim();
  const church = (form.get("church") || "").toString().trim() || null;
  const email = (form.get("email") || "").toString().trim().toLowerCase();
  const file = form.get("file");

  if (!name) return json({ ok: false, error: "Please enter your name." }, 400);
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) return json({ ok: false, error: "Please enter a valid email." }, 400);
  if (!file || typeof file === "string") return json({ ok: false, error: "Please attach an MP3." }, 400);

  const maxBytes = (parseInt(env.MAX_UPLOAD_MB || "200", 10)) * 1_000_000;
  if (file.size > maxBytes) return json({ ok: false, error: `File too large (max ${env.MAX_UPLOAD_MB} MB).` }, 400);
  const type = file.type || "";
  const okType = type.startsWith("audio/") || /\.mp3$/i.test(file.name || "");
  if (!okType) return json({ ok: false, error: "That doesn't look like an audio file. Please upload an MP3." }, 400);

  // Per-email rate cap over a rolling 24h.
  const cap = parseInt(env.RATE_PER_DAY || "3", 10);
  const since = new Date(Date.now() - 24 * 3600 * 1000).toISOString();
  const recent = await sb(env,
    `/self_serve_jobs?email=eq.${encodeURIComponent(email)}&created_at=gt.${encodeURIComponent(since)}&select=id`);
  if (Array.isArray(recent) && recent.length >= cap) {
    return json({ ok: false, error: "You've reached today's limit. Please try again tomorrow." }, 429);
  }

  // Use one id for both the R2 key and the job row, so they're easy to trace.
  const jobId = crypto.randomUUID();
  const key = `self-serve/${jobId}.mp3`;
  await env.AUDIO_BUCKET.put(key, file.stream(), {
    httpMetadata: { contentType: type || "audio/mpeg", cacheControl: "public, max-age=31536000, immutable" },
    customMetadata: { uploadedBy: "sermon-steward-try", email },
  });
  const audioUrl = `${env.R2_PUBLIC_BASE}/${key}`;

  await sb(env, `/self_serve_jobs`, {
    method: "POST",
    headers: { Prefer: "return=minimal" },
    body: JSON.stringify({
      id: jobId, name, church_name: church, email,
      audio_key: key, audio_url: audioUrl, status: "pending",
    }),
  });

  return json({ ok: true });
}

// ───────────────────────────────────────────────────────────────────────────

async function sb(env, path, init = {}) {
  const headers = {
    apikey: env.SUPABASE_SERVICE_KEY,
    Authorization: `Bearer ${env.SUPABASE_SERVICE_KEY}`,
    "Content-Type": "application/json",
    ...(init.headers || {}),
  };
  const r = await fetch(`${env.SUPABASE_URL}/rest/v1${path}`, { ...init, headers });
  if (!r.ok) throw new Error(`Supabase ${r.status}: ${(await r.text()).slice(0, 200)}`);
  // A successful insert with Prefer: return=minimal comes back 201 with an empty
  // body — parse only when there's actually content.
  const text = await r.text();
  return text ? JSON.parse(text) : null;
}

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status, headers: { "Content-Type": "application/json" },
  });
}

// ───────────────────────────────────────────────────────────────────────────
// Landing page — matches the sermonsteward.com home aesthetic.
// ───────────────────────────────────────────────────────────────────────────

const PAGE_HTML = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Try Sermon Steward — turn one sermon into a full report</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
  :root {
    --bg:#fbf8f1; --bg-card:#ffffff; --ink:#1a1a1a; --ink-soft:#4a4a4a; --ink-faint:#828282;
    --rule:#e6e1d3; --accent:#c4452f; --accent-deep:#9a3624; --accent-soft:#f0d4cc; --highlight:#fef0c8;
    --ok:#2c6e3a;
    --sans:'Inter',system-ui,-apple-system,"Segoe UI",sans-serif;
  }
  * { box-sizing:border-box; }
  html,body { margin:0; padding:0; background:var(--bg); color:var(--ink);
    font-family:var(--sans); font-size:17px; line-height:1.55; -webkit-font-smoothing:antialiased; }
  a { color:var(--accent); text-decoration:none; }
  a:hover { color:var(--accent-deep); }
  .site-header { padding:28px 32px; }
  .wordmark { font-weight:800; font-size:22px; letter-spacing:-0.02em; color:var(--ink); }
  .wordmark .dot { color:var(--accent); }
  .wrap { max-width:920px; margin:0 auto; padding:0 24px; }

  .hero { text-align:center; padding:24px 0 8px; }
  .tag { display:inline-block; background:var(--highlight); color:var(--ink); font-size:13px;
    font-weight:600; padding:6px 14px; border-radius:999px; margin-bottom:24px; }
  h1 { font-weight:800; font-size:clamp(2.3rem,5.5vw,3.9rem); line-height:1.04; letter-spacing:-0.035em; margin:0 0 20px; }
  h1 .accent { color:var(--accent); }
  .deck { font-size:clamp(1.1rem,2.2vw,1.35rem); line-height:1.45; color:var(--ink-soft); max-width:600px; margin:0 auto 8px; }

  .features { display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:16px; margin:44px 0; }
  .feature { background:var(--bg-card); border:1px solid var(--rule); border-radius:12px; padding:20px 22px; }
  .feature h3 { margin:0 0 6px; font-size:16px; font-weight:700; }
  .feature p { margin:0; font-size:14.5px; color:var(--ink-soft); line-height:1.45; }
  .feature .ic { font-size:20px; }

  .cta-card { background:var(--bg-card); border:1px solid var(--rule); border-radius:16px;
    padding:32px; max-width:560px; margin:0 auto 48px; box-shadow:0 1px 2px rgba(0,0,0,0.04),0 10px 30px rgba(0,0,0,0.05); }
  .cta-card h2 { margin:0 0 4px; font-size:24px; font-weight:800; letter-spacing:-0.02em; }
  .cta-card .sub { margin:0 0 22px; color:var(--ink-soft); font-size:15px; }
  label { display:block; font-weight:600; font-size:14px; margin:14px 0 6px; }
  label .opt { font-weight:400; color:var(--ink-faint); }
  input[type=text], input[type=email] { width:100%; padding:12px 14px; border:1px solid var(--rule);
    border-radius:9px; font-size:16px; font-family:inherit; background:#fff; }
  input:focus { outline:none; border-color:var(--accent); box-shadow:0 0 0 3px var(--accent-soft); }
  #drop { margin-top:6px; border:2px dashed var(--rule); border-radius:11px; padding:26px 16px; text-align:center;
    cursor:pointer; background:#fcfbf7; transition:all .15s; }
  #drop.hover { border-color:var(--accent); background:var(--accent-soft); }
  #drop.has-file { border-style:solid; border-color:var(--ok); background:#fff; }
  #drop .hint { color:var(--ink-faint); font-size:13.5px; margin-top:4px; }
  #file-info { font-size:14px; margin-top:8px; color:var(--ink-soft); }
  button.submit { width:100%; margin-top:22px; padding:16px; background:var(--accent); color:#fff; border:none;
    border-radius:10px; font-size:17px; font-weight:700; cursor:pointer; font-family:inherit;
    box-shadow:0 4px 12px rgba(196,69,47,0.2); transition:background .12s, transform .12s; }
  button.submit:hover { background:var(--accent-deep); transform:translateY(-1px); }
  button.submit:disabled { background:var(--ink-faint); cursor:not-allowed; transform:none; box-shadow:none; }
  #progress { display:none; height:8px; background:var(--rule); border-radius:4px; overflow:hidden; margin-top:16px; }
  #progress.show { display:block; }
  #bar { height:100%; width:0; background:var(--accent); transition:width .2s; }
  #status { margin-top:16px; padding:14px; border-radius:9px; font-size:14.5px; display:none; }
  #status.show { display:block; }
  #status.ok { background:#e3f1e6; color:var(--ok); }
  #status.error { background:#fbe5e5; color:var(--accent-deep); }
  .privacy { text-align:center; font-size:12.5px; color:var(--ink-faint); margin-top:14px; }
  footer { padding:24px 32px; font-size:13px; color:var(--ink-faint); text-align:center; border-top:1px solid var(--rule); }
</style>
</head>
<body>
<header class="site-header"><span class="wordmark">Sermon Steward<span class="dot">.</span></span></header>

<div class="wrap">
  <div class="hero">
    <div class="tag">Free · one sermon · no account needed</div>
    <h1>See everything in your sermon<br><span class="accent">you didn't have time to write down.</span></h1>
    <p class="deck">Upload one sermon. We'll send back a transcript, discussion questions,
      writing prompts, and a full report &mdash; usually within about 15 minutes.</p>
  </div>

  <div class="features">
    <div class="feature"><div class="ic">📝</div><h3>AI-ready transcripts</h3>
      <p>A clean, accurate transcript of your message &mdash; ready to search, quote, and repurpose.</p></div>
    <div class="feature"><div class="ic">💬</div><h3>Discussion questions</h3>
      <p>Small-group questions drawn straight from your sermon, with follow-ups and Scripture anchors.</p></div>
    <div class="feature"><div class="ic">✍️</div><h3>Writing prompts</h3>
      <p>Concepts from each point of the sermon to explore further in your own reading and writing.</p></div>
    <div class="feature"><div class="ic">🔎</div><h3>What we noticed</h3>
      <p>The doctrinal threads, themes, and notable moments our analysis surfaced in your message.</p></div>
    <div class="feature"><div class="ic">🙏</div><h3>Resources for your people</h3>
      <p>A prayer, a family conversation prompt, daily readings, and a memory verse &mdash; all from the sermon.</p></div>
    <div class="feature"><div class="ic">📄</div><h3>A sample article</h3>
      <p>One writing prompt drafted into a full sample article, written in your own voice.</p></div>
  </div>

  <div class="cta-card">
    <h2>Try it with one sermon</h2>
    <p class="sub">Drop in an MP3 and we'll email your report.</p>
    <form id="form" enctype="multipart/form-data">
      <label for="name">Your name</label>
      <input type="text" id="name" name="name" required placeholder="e.g. Pastor John Smith">
      <label for="church">Church <span class="opt">(optional)</span></label>
      <input type="text" id="church" name="church" placeholder="e.g. Grace Community Church">
      <label for="email">Email</label>
      <input type="email" id="email" name="email" required placeholder="you@church.org">
      <label>Sermon audio (MP3)</label>
      <div id="drop">
        <div>Drop an MP3 here, or <a href="#" id="browse">click to browse</a></div>
        <div class="hint">Most sermon files are 30&ndash;90 MB.</div>
        <div id="file-info"></div>
        <input type="file" id="file" name="file" accept="audio/mpeg,audio/mp3,.mp3" style="display:none" required>
      </div>
      <button type="submit" class="submit" id="btn">Get my free report →</button>
      <div id="progress"><div id="bar"></div></div>
      <div id="status"></div>
    </form>
    <div class="privacy">We use your sermon only to generate your report. We never publish it without your say-so.</div>
  </div>
</div>

<footer>Sermon Steward &middot; <a href="https://sermonsteward.com">sermonsteward.com</a></footer>

<script>
  var $ = function(id){ return document.getElementById(id); };
  var fi = $("file"), dz = $("drop");
  $("browse").addEventListener("click", function(e){ e.preventDefault(); fi.click(); });
  dz.addEventListener("click", function(e){ if (e.target.id !== "browse") fi.click(); });
  dz.addEventListener("dragover", function(e){ e.preventDefault(); dz.classList.add("hover"); });
  dz.addEventListener("dragleave", function(){ dz.classList.remove("hover"); });
  dz.addEventListener("drop", function(e){ e.preventDefault(); dz.classList.remove("hover");
    if (e.dataTransfer.files.length){ fi.files = e.dataTransfer.files; onFile(); } });
  fi.addEventListener("change", onFile);
  function onFile(){ var f = fi.files[0]; if (!f) return;
    $("file-info").textContent = f.name + " (" + (f.size/1000000).toFixed(1) + " MB)";
    dz.classList.add("has-file"); }
  function showStatus(kind, msg){ var s = $("status"); s.textContent = msg; s.className = kind + " show"; }

  $("form").addEventListener("submit", function(e){
    e.preventDefault();
    if (!fi.files[0]) return showStatus("error", "Please attach an MP3 first.");
    var fd = new FormData(e.target);
    $("btn").disabled = true; $("status").className = "";
    $("progress").classList.add("show"); $("bar").style.width = "0%";
    var xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/submit");
    xhr.upload.onprogress = function(evt){ if (evt.lengthComputable) $("bar").style.width = (evt.loaded/evt.total*100) + "%"; };
    xhr.onload = function(){
      $("progress").classList.remove("show");
      var body = {}; try { body = JSON.parse(xhr.responseText); } catch(_){}
      if (xhr.status >= 200 && xhr.status < 300 && body.ok){
        $("form").reset(); $("file-info").textContent = ""; dz.classList.remove("has-file");
        showStatus("ok", "Thanks! We're studying your sermon now — your report will arrive by email in about 10–15 minutes.");
      } else {
        $("btn").disabled = false;
        showStatus("error", body.error || "Something went wrong. Please try again.");
      }
    };
    xhr.onerror = function(){ $("btn").disabled = false; $("progress").classList.remove("show");
      showStatus("error", "Network error. Check your connection and try again."); };
    xhr.send(fd);
  });
</script>
</body>
</html>`;
