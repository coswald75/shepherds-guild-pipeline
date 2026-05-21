/**
 * Sermon Steward — upload Worker
 * ─────────────────────────────────────────────────────────────────────────
 * Single-Worker upload pipeline for sound techs / pastors.
 *
 * Routes (all relative to the worker's hostname; <slug> is the church slug):
 *   GET  /<slug>?token=<bearer>           → renders the upload page (HTML)
 *   GET  /<slug>/api/preachers            → JSON list of preachers + recent series
 *   POST /<slug>/api/preacher             → JSON {name}; creates a new preacher row
 *   POST /<slug>/api/upload               → multipart/form-data with file + metadata
 *
 * Auth is a per-church bearer token stored on churches.upload_token. The
 * frontend reads it from ?token=...; API endpoints accept it via the same
 * querystring or an X-Upload-Token header.
 *
 * The file is streamed directly into the bound R2 bucket — no presigning.
 * Cloudflare Workers (free plan) cap request body at 100 MB, paid at 500 MB.
 * That's comfortable for sermon MP3s (typically 40–60 MB).
 *
 * Bindings expected (see wrangler.toml):
 *   env.AUDIO_BUCKET            R2 bucket (sermon-steward-audio)
 *   env.R2_PUBLIC_BASE          https://sermons-cdn.sermonsteward.com
 *   env.SUPABASE_URL            project URL
 *   env.SUPABASE_SERVICE_KEY    service-role key (set via `wrangler secret put`)
 */

export default {
  async fetch(request, env, ctx) {
    try {
      return await route(request, env);
    } catch (err) {
      console.error("Worker error:", err);
      return jsonError(500, err.message || "Internal error");
    }
  },
};

// ───────────────────────────────────────────────────────────────────────────
// Routing
// ───────────────────────────────────────────────────────────────────────────

async function route(request, env) {
  const url = new URL(request.url);

  // Match /<slug> or /<slug>/api/<action>
  const m = url.pathname.match(/^\/([\w-]+)(?:\/api\/([\w-]+))?\/?$/);
  if (!m) return new Response("Not found", { status: 404 });
  const [, slug, action] = m;

  const token =
    url.searchParams.get("token") ||
    request.headers.get("x-upload-token") ||
    "";

  if (!action) {
    // Page render — bad tokens still render the page, with an error inside.
    return renderPage({ env, slug, token });
  }

  // API endpoints — token must be valid.
  const church = await getChurch(env, slug, token);
  if (!church) return jsonError(401, "Invalid or missing token");

  if (action === "preachers" && request.method === "GET") {
    const data = await getPreachers(env, church.id);
    return jsonResponse(data);
  }
  if (action === "preacher" && request.method === "POST") {
    const body = await request.json();
    if (!body.name || typeof body.name !== "string") {
      return jsonError(400, "Missing name");
    }
    const row = await createPreacher(env, church.id, body.name.trim());
    return jsonResponse(row);
  }
  if (action === "upload" && request.method === "POST") {
    return handleUpload(request, env, church);
  }

  return jsonError(404, `Unknown action: ${action}`);
}

// ───────────────────────────────────────────────────────────────────────────
// Upload handler
// ───────────────────────────────────────────────────────────────────────────

async function handleUpload(request, env, church) {
  const form = await request.formData();
  const file = form.get("file");
  const title = (form.get("title") || "").toString().trim();
  const date = (form.get("date") || "").toString().trim();
  const preacherId = (form.get("preacher_id") || "").toString().trim();
  const series = (form.get("series") || "").toString().trim() || null;
  const primaryText = (form.get("primary_text") || "").toString().trim() || null;

  if (!file || !(file instanceof File)) return jsonError(400, "Missing file");
  if (!title) return jsonError(400, "Missing title");
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return jsonError(400, "Date must be YYYY-MM-DD");
  if (!preacherId) return jsonError(400, "Missing preacher_id");

  const sermonSlug = `${slugify(title)}-${date}`;
  const key = `${church.slug}/${sermonSlug}.mp3`;

  // Stream into R2.
  await env.AUDIO_BUCKET.put(key, file.stream(), {
    httpMetadata: {
      contentType: file.type || "audio/mpeg",
      cacheControl: "public, max-age=31536000, immutable",
    },
    customMetadata: {
      uploadedBy: "sermon-steward-upload",
      churchSlug: church.slug,
    },
  });

  const hostedUrl = `${env.R2_PUBLIC_BASE}/${key}`;

  // Insert sermons row. audio_url also set to the hosted URL since we have
  // no upstream URL of record for tech-uploaded sermons.
  const sermon = await insertSermon(env, {
    preacher_id: preacherId,
    title,
    date,
    slug: sermonSlug,
    series_name: series,
    primary_text: primaryText,
    audio_url: hostedUrl,
    hosted_audio_url: hostedUrl,
    upload_source: "tech_upload",
  });

  return jsonResponse({
    ok: true,
    sermon_id: sermon.id,
    hosted_audio_url: hostedUrl,
    sermon_slug: sermonSlug,
  });
}

// ───────────────────────────────────────────────────────────────────────────
// Supabase REST helpers
// ───────────────────────────────────────────────────────────────────────────

async function sb(env, path, init = {}) {
  const headers = {
    apikey: env.SUPABASE_SERVICE_KEY,
    Authorization: `Bearer ${env.SUPABASE_SERVICE_KEY}`,
    "Content-Type": "application/json",
    ...(init.headers || {}),
  };
  const url = `${env.SUPABASE_URL}/rest/v1${path}`;
  const r = await fetch(url, { ...init, headers });
  if (!r.ok) {
    const body = await r.text();
    throw new Error(`Supabase ${r.status}: ${body.slice(0, 200)}`);
  }
  return r.status === 204 ? null : r.json();
}

async function getChurch(env, slug, token) {
  if (!slug || !token) return null;
  const rows = await sb(
    env,
    `/churches?slug=eq.${encodeURIComponent(slug)}&upload_token=eq.${encodeURIComponent(token)}&select=id,slug,name`
  );
  return rows && rows.length ? rows[0] : null;
}

async function getPreachers(env, churchId) {
  const preachers = await sb(
    env,
    `/preachers?church_id=eq.${churchId}&select=id,name&order=name.asc`
  );
  // Recent series for this church — last 12 distinct series_names across any
  // of its preachers. Uses PostgREST embedded-resource filter.
  const recent = await sb(
    env,
    `/sermons?select=series_name,preachers!inner(church_id)&preachers.church_id=eq.${churchId}&series_name=not.is.null&order=date.desc&limit=50`
  ).catch(() => null);
  const seriesSet = new Set();
  for (const r of recent || []) if (r.series_name) seriesSet.add(r.series_name);
  return { preachers, recent_series: Array.from(seriesSet).slice(0, 12) };
}

async function createPreacher(env, churchId, name) {
  const inserted = await sb(env, `/preachers?select=id,name`, {
    method: "POST",
    headers: { Prefer: "return=representation" },
    body: JSON.stringify({
      church_id: churchId,
      name,
      is_public: true,
    }),
  });
  return Array.isArray(inserted) ? inserted[0] : inserted;
}

async function insertSermon(env, row) {
  const inserted = await sb(env, `/sermons?select=id`, {
    method: "POST",
    headers: { Prefer: "return=representation" },
    body: JSON.stringify(row),
  });
  return Array.isArray(inserted) ? inserted[0] : inserted;
}

// ───────────────────────────────────────────────────────────────────────────
// Utilities
// ───────────────────────────────────────────────────────────────────────────

function slugify(s) {
  return (s || "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}

function jsonResponse(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function jsonError(status, message) {
  return jsonResponse({ ok: false, error: message }, status);
}

// ───────────────────────────────────────────────────────────────────────────
// HTML page
// ───────────────────────────────────────────────────────────────────────────

async function renderPage({ env, slug, token }) {
  // Pre-fetch church name for the page header (best-effort).
  let churchName = "";
  let tokenValid = false;
  if (token) {
    const church = await getChurch(env, slug, token).catch(() => null);
    if (church) {
      churchName = church.name;
      tokenValid = true;
    }
  }

  const todayIso = new Date().toISOString().slice(0, 10);
  const html = PAGE_HTML
    .replaceAll("__SLUG__", slug)
    .replaceAll("__CHURCH_NAME__", escapeHtml(churchName || slug))
    .replaceAll("__TOKEN_VALID__", tokenValid ? "true" : "false")
    .replaceAll("__TOKEN__", escapeHtml(token))
    .replaceAll("__TODAY__", todayIso);

  return new Response(html, {
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": "no-store",
    },
  });
}

function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

const PAGE_HTML = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Upload Sermon — __CHURCH_NAME__</title>
<style>
  :root {
    --ink: #1a1a1a;
    --muted: #6b6b6b;
    --line: #d8d4cb;
    --bg: #f8f5ef;
    --accent: #8b3a1a;
    --accent-soft: #f3e8df;
    --ok: #2c6e3a;
    --error: #a02525;
  }
  * { box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
    color: var(--ink);
    background: var(--bg);
    margin: 0;
    padding: 32px 16px;
    line-height: 1.5;
  }
  .wrap { max-width: 600px; margin: 0 auto; }
  h1 {
    font-family: Georgia, "Iowan Old Style", serif;
    font-size: 28px;
    margin: 0 0 4px;
    font-weight: 600;
  }
  .subtitle { color: var(--muted); margin-bottom: 28px; font-size: 15px; }
  .card {
    background: white;
    border: 1px solid var(--line);
    border-radius: 8px;
    padding: 24px;
  }
  label { display: block; font-weight: 600; margin: 14px 0 6px; font-size: 14px; }
  label .opt { font-weight: 400; color: var(--muted); }
  input[type=text], input[type=date], select, textarea {
    width: 100%;
    padding: 10px 12px;
    border: 1px solid var(--line);
    border-radius: 6px;
    font-size: 15px;
    font-family: inherit;
    background: white;
  }
  input:focus, select:focus, textarea:focus {
    outline: none;
    border-color: var(--accent);
    box-shadow: 0 0 0 3px var(--accent-soft);
  }
  #drop-zone {
    margin-top: 6px;
    border: 2px dashed var(--line);
    border-radius: 8px;
    padding: 32px 16px;
    text-align: center;
    cursor: pointer;
    transition: all 0.15s;
    background: #fafaf6;
  }
  #drop-zone.hover { border-color: var(--accent); background: var(--accent-soft); }
  #drop-zone .hint { color: var(--muted); font-size: 14px; margin-top: 4px; }
  #drop-zone.has-file { border-style: solid; border-color: var(--ok); background: white; }
  #file-info { font-size: 14px; margin-top: 8px; color: var(--muted); }
  .more-toggle {
    display: inline-block;
    margin-top: 14px;
    color: var(--accent);
    cursor: pointer;
    font-size: 14px;
    user-select: none;
  }
  .more-toggle:hover { text-decoration: underline; }
  #more { display: none; margin-top: 8px; }
  #more.open { display: block; }
  button.submit {
    width: 100%;
    margin-top: 20px;
    padding: 14px;
    background: var(--accent);
    color: white;
    border: none;
    border-radius: 6px;
    font-size: 16px;
    font-weight: 600;
    cursor: pointer;
    font-family: inherit;
  }
  button.submit:hover { background: #6e2d13; }
  button.submit:disabled { background: var(--muted); cursor: not-allowed; }
  #progress {
    display: none;
    height: 8px;
    background: var(--line);
    border-radius: 4px;
    overflow: hidden;
    margin-top: 16px;
  }
  #progress.show { display: block; }
  #progress-bar {
    height: 100%;
    width: 0;
    background: var(--accent);
    transition: width 0.2s;
  }
  #status {
    margin-top: 14px;
    padding: 12px;
    border-radius: 6px;
    font-size: 14px;
    display: none;
  }
  #status.show { display: block; }
  #status.ok { background: #e3f1e6; color: var(--ok); }
  #status.error { background: #fbe5e5; color: var(--error); }
  .invalid-token {
    background: #fbe5e5;
    border: 1px solid var(--error);
    color: var(--error);
    padding: 16px;
    border-radius: 6px;
  }
  .footer { text-align: center; color: var(--muted); font-size: 13px; margin-top: 24px; }
</style>
</head>
<body>
<div class="wrap">
  <h1>Upload a sermon</h1>
  <div class="subtitle">for <strong>__CHURCH_NAME__</strong></div>

  <div id="invalid" class="invalid-token" style="display:none">
    This upload link is missing or invalid. Please contact your Sermon Steward
    administrator for a fresh link.
  </div>

  <form id="form" class="card" enctype="multipart/form-data" style="display:none">
    <label>Audio file (MP3)</label>
    <div id="drop-zone">
      <div>Drop an MP3 here, or <a href="#" id="browse">click to browse</a></div>
      <div class="hint">Typical sermon files are 30–80 MB.</div>
      <div id="file-info"></div>
      <input type="file" id="file" name="file" accept="audio/mpeg,audio/mp3,.mp3" style="display:none" required />
    </div>

    <label for="title">Title</label>
    <input type="text" id="title" name="title" required placeholder="e.g. The Story of the Lamb" />

    <label for="date">Date preached</label>
    <input type="date" id="date" name="date" required value="__TODAY__" />

    <label for="preacher">Preacher</label>
    <select id="preacher" name="preacher_id" required>
      <option value="">Loading…</option>
    </select>

    <span class="more-toggle" id="more-toggle">+ More details (optional)</span>
    <div id="more">
      <label for="primary_text">Primary text <span class="opt">(optional)</span></label>
      <input type="text" id="primary_text" name="primary_text" placeholder="e.g. Revelation 21:1–8" />

      <label for="series">Series <span class="opt">(optional)</span></label>
      <input type="text" id="series" name="series" list="series-list" placeholder="e.g. Revelation" />
      <datalist id="series-list"></datalist>
    </div>

    <button type="submit" class="submit" id="submit-btn">Upload sermon</button>
    <div id="progress"><div id="progress-bar"></div></div>
    <div id="status"></div>
  </form>

  <div class="footer">Sermon Steward · sermonsteward.com</div>
</div>

<script>
  const SLUG = "__SLUG__";
  const TOKEN = "__TOKEN__";
  const TOKEN_VALID = __TOKEN_VALID__;

  const $ = (id) => document.getElementById(id);

  if (!TOKEN_VALID) {
    $("invalid").style.display = "block";
  } else {
    $("form").style.display = "block";
    initForm();
  }

  async function initForm() {
    // Load preachers + recent series
    try {
      const r = await fetch(\`/\${SLUG}/api/preachers?token=\${encodeURIComponent(TOKEN)}\`);
      const data = await r.json();
      const sel = $("preacher");
      sel.innerHTML = "";
      const placeholder = document.createElement("option");
      placeholder.value = "";
      placeholder.textContent = "— select preacher —";
      sel.appendChild(placeholder);
      for (const p of data.preachers || []) {
        const o = document.createElement("option");
        o.value = p.id;
        o.textContent = p.name;
        sel.appendChild(o);
      }
      const guest = document.createElement("option");
      guest.value = "__guest__";
      guest.textContent = "Other / Guest preacher…";
      sel.appendChild(guest);

      const dl = $("series-list");
      for (const s of data.recent_series || []) {
        const o = document.createElement("option");
        o.value = s;
        dl.appendChild(o);
      }
    } catch (e) {
      showStatus("error", "Failed to load preacher list. Refresh and try again.");
    }

    // Drag-drop
    const dz = $("drop-zone");
    const fi = $("file");
    $("browse").addEventListener("click", (e) => { e.preventDefault(); fi.click(); });
    dz.addEventListener("click", () => fi.click());
    dz.addEventListener("dragover", (e) => { e.preventDefault(); dz.classList.add("hover"); });
    dz.addEventListener("dragleave", () => dz.classList.remove("hover"));
    dz.addEventListener("drop", (e) => {
      e.preventDefault();
      dz.classList.remove("hover");
      if (e.dataTransfer.files.length) {
        fi.files = e.dataTransfer.files;
        onFileChosen();
      }
    });
    fi.addEventListener("change", onFileChosen);
    function onFileChosen() {
      const f = fi.files[0];
      if (!f) return;
      const mb = (f.size / 1_000_000).toFixed(1);
      $("file-info").textContent = \`\${f.name} (\${mb} MB)\`;
      dz.classList.add("has-file");
    }

    // More toggle
    $("more-toggle").addEventListener("click", () => {
      $("more").classList.toggle("open");
      const open = $("more").classList.contains("open");
      $("more-toggle").textContent = open ? "− Hide optional details" : "+ More details (optional)";
    });

    // Guest preacher prompt
    $("preacher").addEventListener("change", async (e) => {
      if (e.target.value !== "__guest__") return;
      const name = prompt("Guest preacher's name?");
      if (!name || !name.trim()) {
        e.target.value = "";
        return;
      }
      try {
        const r = await fetch(\`/\${SLUG}/api/preacher?token=\${encodeURIComponent(TOKEN)}\`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: name.trim() }),
        });
        if (!r.ok) throw new Error("Create failed: " + r.status);
        const created = await r.json();
        const o = document.createElement("option");
        o.value = created.id;
        o.textContent = created.name;
        const sel = $("preacher");
        // Insert before guest option
        sel.insertBefore(o, sel.querySelector('option[value="__guest__"]'));
        sel.value = created.id;
      } catch (err) {
        showStatus("error", "Couldn't add guest preacher. Try again.");
        e.target.value = "";
      }
    });

    // Submit
    $("form").addEventListener("submit", onSubmit);
  }

  async function onSubmit(e) {
    e.preventDefault();
    const file = $("file").files[0];
    if (!file) return showStatus("error", "Pick an audio file first.");
    if ($("preacher").value === "__guest__") return showStatus("error", "Finish entering the guest preacher.");

    const fd = new FormData(e.target);
    $("submit-btn").disabled = true;
    $("status").className = "";
    $("progress").classList.add("show");
    $("progress-bar").style.width = "0%";

    const xhr = new XMLHttpRequest();
    xhr.open("POST", \`/\${SLUG}/api/upload?token=\${encodeURIComponent(TOKEN)}\`);
    xhr.upload.onprogress = (evt) => {
      if (evt.lengthComputable) {
        const pct = (evt.loaded / evt.total) * 100;
        $("progress-bar").style.width = pct + "%";
      }
    };
    xhr.onload = () => {
      $("submit-btn").disabled = false;
      $("progress").classList.remove("show");
      let body;
      try { body = JSON.parse(xhr.responseText); } catch (_) { body = {}; }
      if (xhr.status >= 200 && xhr.status < 300 && body.ok) {
        showStatus("ok",
          "Uploaded. Sermon Steward will email the pastor when the artifacts are ready (usually Tuesday morning).");
        $("form").reset();
        $("file-info").textContent = "";
        $("drop-zone").classList.remove("has-file");
        $("date").value = "__TODAY__";
      } else {
        showStatus("error", "Upload failed: " + (body.error || xhr.statusText || "unknown"));
      }
    };
    xhr.onerror = () => {
      $("submit-btn").disabled = false;
      $("progress").classList.remove("show");
      showStatus("error", "Network error. Check your connection and try again.");
    };
    xhr.send(fd);
  }

  function showStatus(kind, msg) {
    const el = $("status");
    el.textContent = msg;
    el.className = kind + " show";
  }
</script>
</body>
</html>
`;
