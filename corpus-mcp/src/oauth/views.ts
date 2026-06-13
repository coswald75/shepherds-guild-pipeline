// HTML templates for the OAuth flow's user-facing pages. Minimal styling
// for v1 — clean, on-brand-ish, mobile-friendly. The pastor sees these
// briefly during the magic-link round-trip.
//
// Kept as plain strings rather than a templating library to stay inside
// the Worker bundle and avoid an extra dependency. The escape helper
// prevents any user-provided string (email, client name, error message)
// from breaking the markup.

function esc(s: string): string {
  return s.replace(/[&<>"']/g, (c) => {
    switch (c) {
      case "&": return "&amp;";
      case "<": return "&lt;";
      case ">": return "&gt;";
      case "\"": return "&quot;";
      case "'": return "&#39;";
      default: return c;
    }
  });
}

const BASE_CSS = `
  :root {
    --bg: #fbf8f1; --ink: #1a1a1a; --ink-soft: #4a4a4a; --ink-faint: #828282;
    --rule: #e6e1d3; --accent: #c4452f; --accent-deep: #9a3624;
    --gold: #b8893a; --serif: 'Source Serif Pro', Iowan Old Style, Georgia, serif;
    --sans: Inter, system-ui, -apple-system, sans-serif;
  }
  * { box-sizing: border-box; }
  html, body {
    margin: 0; padding: 0; min-height: 100vh;
    background: var(--bg); color: var(--ink);
    font-family: var(--sans); font-size: 16px; line-height: 1.55;
    -webkit-font-smoothing: antialiased;
    display: flex; align-items: center; justify-content: center;
  }
  .card {
    max-width: 440px; width: 100%; margin: 24px;
    padding: 32px 28px; border: 1px solid var(--rule);
    border-radius: 8px; background: #fff;
  }
  h1 {
    font-family: var(--serif); font-weight: 600; font-size: 26px;
    margin: 0 0 8px; color: var(--ink);
  }
  .sub { color: var(--ink-soft); font-size: 14px; margin: 0 0 24px; }
  .field { display: block; margin: 0 0 16px; }
  .field label {
    display: block; font-size: 12px; letter-spacing: 0.5px;
    text-transform: uppercase; color: var(--ink-faint); margin: 0 0 6px;
  }
  .field input[type="email"],
  .field input[type="text"] {
    width: 100%; padding: 10px 12px; border: 1px solid var(--rule);
    border-radius: 6px; font-size: 15px; font-family: var(--sans);
    background: var(--bg);
  }
  .field input[type="email"]:focus,
  .field input[type="text"]:focus {
    outline: none; border-color: var(--gold);
  }
  .field input.code {
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 22px; letter-spacing: 6px; text-align: center;
    padding: 14px 12px;
  }
  button.primary {
    display: block; width: 100%; padding: 12px;
    background: var(--accent); color: #fff;
    border: none; border-radius: 6px; font-size: 15px; font-weight: 600;
    cursor: pointer; font-family: var(--sans);
  }
  button.primary:hover { background: var(--accent-deep); }
  button.primary:disabled { opacity: 0.6; cursor: default; }
  .err {
    margin-top: 16px; padding: 10px 12px;
    background: #fbe9e5; border: 1px solid var(--accent-deep);
    border-radius: 6px; color: var(--accent-deep); font-size: 14px;
  }
  .ok {
    margin-top: 16px; padding: 10px 12px;
    background: #f0e7d4; border: 1px solid var(--gold);
    border-radius: 6px; color: #6a4a18; font-size: 14px;
  }
  .meta {
    margin-top: 20px; font-size: 12px; color: var(--ink-faint);
  }
  code {
    background: var(--bg); padding: 1px 5px; border-radius: 3px;
    font-size: 12.5px; color: var(--ink-soft);
  }
`;

function shell(title: string, body: string): string {
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Source+Serif+Pro:wght@500;600&display=swap" rel="stylesheet">
<style>${BASE_CSS}</style>
</head>
<body>
<div class="card">${body}</div>
</body>
</html>`;
}

function htmlResponse(html: string, status = 200): Response {
  return new Response(html, {
    status,
    headers: { "Content-Type": "text/html; charset=utf-8" },
  });
}

// ─── Sign-in page (GET /oauth/authorize when not yet authenticated) ────────
export function signInPage(opts: {
  clientName: string;
  formAction: string;
  hidden: Record<string, string>;
  error?: string;
  prefillEmail?: string;
}): Response {
  const hiddenFields = Object.entries(opts.hidden)
    .map(
      ([k, v]) => `<input type="hidden" name="${esc(k)}" value="${esc(v)}">`,
    )
    .join("\n");
  const errBlock = opts.error
    ? `<div class="err">${esc(opts.error)}</div>`
    : "";
  const body = `
    <h1>Connect to Sermon Steward</h1>
    <p class="sub">
      ${esc(opts.clientName)} wants to read from your sermon corpus.
      Sign in with your pastoral email to continue.
    </p>
    <form method="POST" action="${esc(opts.formAction)}">
      ${hiddenFields}
      <div class="field">
        <label for="email">Email</label>
        <input type="email" id="email" name="email" required
               value="${esc(opts.prefillEmail ?? "")}"
               placeholder="you@yourchurch.org" autocomplete="email">
      </div>
      <button type="submit" class="primary">Send sign-in link</button>
      ${errBlock}
    </form>
    <p class="meta">
      We'll email you a link. Click it on this device to finish connecting.
    </p>`;
  return htmlResponse(shell("Connect to Sermon Steward", body));
}

// ─── Link-sent confirmation page ───────────────────────────────────────────
// Kept as a fallback rendering for any flow that still wants the magic-link
// experience (none today — Desktop's loopback listener times out before the
// link is clicked). Default flow uses codeEntryPage instead.
export function linkSentPage(email: string): Response {
  const body = `
    <h1>Check your email</h1>
    <p class="sub">
      We sent a sign-in link to <strong>${esc(email)}</strong>.
      Open it on this device to finish connecting Sermon Steward.
    </p>
    <div class="ok">
      The link is valid for 5 minutes. If you don't see it, check spam.
    </div>
    <p class="meta">You can close this window after clicking the link.</p>`;
  return htmlResponse(shell("Check your email — Sermon Steward", body));
}

// ─── Code-entry page (default OTP path) ────────────────────────────────────
// The pastor enters the numeric code Supabase mailed them. Stays in the
// same tab as the email submission, so Claude Desktop's loopback listener
// on localhost:5051 is still alive when we redirect the code back to it.
//
// Code LENGTH is governed by the Supabase project's Email OTP Length
// setting (Dashboard → Authentication → Email → Email OTP Length;
// default 6, configurable 6–10). This project is currently set to 8.
// The form accepts 6–10 digits rather than hardcoding a count so it
// survives any future change to that setting — the server-side
// verifyOtp is the real validator and doesn't care about length.
// (2026-06-11: was hardcoded to 6, which silently blocked the 7th/8th
// digit of the 8-digit codes the project actually mails — surfaced
// when connecting Perplexity.)
//
// All OAuth params round-trip as hidden fields (same shape as signInPage)
// so a wrong code attempt can re-render this page without losing context.
export function codeEntryPage(opts: {
  email: string;
  formAction: string;
  hidden: Record<string, string>;
  error?: string;
}): Response {
  const hiddenFields = Object.entries(opts.hidden)
    .map(
      ([k, v]) => `<input type="hidden" name="${esc(k)}" value="${esc(v)}">`,
    )
    .join("\n");
  const errBlock = opts.error
    ? `<div class="err">${esc(opts.error)}</div>`
    : "";
  const body = `
    <h1>Enter your sign-in code</h1>
    <p class="sub">
      We emailed a code to <strong>${esc(opts.email)}</strong>.
      Enter it below to finish connecting Sermon Steward.
    </p>
    <form method="POST" action="${esc(opts.formAction)}">
      ${hiddenFields}
      <div class="field">
        <label for="token">Code from your email</label>
        <input type="text" id="token" name="token" required
               class="code" inputmode="numeric" pattern="[0-9]{6,10}"
               maxlength="10" autocomplete="one-time-code"
               placeholder="Enter the code" autofocus>
      </div>
      <button type="submit" class="primary">Sign in</button>
      ${errBlock}
    </form>
    <p class="meta">
      The code is valid for a few minutes. If you also see a sign-in link in
      your email, you can ignore it — the code is faster.
    </p>`;
  return htmlResponse(shell("Enter your code — Sermon Steward", body));
}

// ─── Error page ────────────────────────────────────────────────────────────
export function errorPage(opts: {
  title: string;
  detail: string;
  status?: number;
}): Response {
  const body = `
    <h1>${esc(opts.title)}</h1>
    <p class="sub">${esc(opts.detail)}</p>
    <p class="meta">
      If this keeps happening, contact the person who shared Sermon Steward
      with you.
    </p>`;
  return htmlResponse(shell(opts.title, body), opts.status ?? 400);
}

// ─── Fragment-bouncing page ────────────────────────────────────────────────
// Supabase Auth's email magic-link flow puts the access_token in the URL
// fragment (#access_token=...), which is browser-only and never sent to
// the server. This page runs a tiny JS to extract the fragment values
// and POST them back to our server. The cookie carries login_state.
export function fragmentBouncerPage(): Response {
  const body = `
    <h1>Connecting…</h1>
    <p class="sub">Signing you in to Sermon Steward.</p>
    <div class="ok" id="status">Reading sign-in token from URL…</div>
    <form id="exchange" method="POST"
          action="/oauth/authorize/callback/exchange" style="display:none">
      <input type="hidden" name="access_token" id="access_token">
      <input type="hidden" name="refresh_token" id="refresh_token">
      <input type="hidden" name="provider_token" id="provider_token">
    </form>
    <script>
      (function () {
        var status = document.getElementById('status');
        var hash = (location.hash || '').replace(/^#/, '');
        if (!hash) {
          status.textContent = 'Missing tokens. Try the sign-in link again.';
          status.className = 'err';
          return;
        }
        var params = new URLSearchParams(hash);
        var at = params.get('access_token');
        var rt = params.get('refresh_token') || '';
        if (!at) {
          status.textContent = 'No access token in URL fragment. Try the sign-in link again.';
          status.className = 'err';
          return;
        }
        document.getElementById('access_token').value = at;
        document.getElementById('refresh_token').value = rt;
        status.textContent = 'Verifying…';
        document.getElementById('exchange').submit();
      })();
    </script>`;
  return htmlResponse(shell("Connecting — Sermon Steward", body));
}

// ─── Success page (after successful auth, before redirect) ─────────────────
// In practice we redirect immediately — this is a fallback for clients that
// can't handle the redirect (rare). Shown for ~2s before auto-redirect.
export function successPage(redirectUrl: string): Response {
  const body = `
    <h1>You're connected.</h1>
    <p class="sub">Returning you to your LLM…</p>
    <div class="ok">If you aren't redirected automatically,
      <a href="${esc(redirectUrl)}">click here</a>.
    </div>
    <script>
      setTimeout(function(){
        window.location.href = ${JSON.stringify(redirectUrl)};
      }, 800);
    </script>`;
  return htmlResponse(shell("Connected — Sermon Steward", body));
}
