import { createClient } from "@supabase/supabase-js";
import type { Env } from "../types";
import { adminClient } from "../auth";
import {
  bindClientToPreacher,
  consumeLoginState,
  createLoginState,
  deleteLoginState,
  getClient,
  issueAuthorizationCode,
  peekLoginState,
} from "./store";
import {
  codeEntryPage,
  errorPage,
  fragmentBouncerPage,
  signInPage,
  successPage,
} from "./views";

// /oauth/authorize and its companions.
//
// Three flows under one path family:
//
//   GET  /oauth/authorize?...        → render sign-in page (asks for email)
//   POST /oauth/authorize/email      → send magic link via Supabase Auth
//   GET  /oauth/authorize/callback   → magic-link landing; issue auth code
//
// State carries through via the login_states table (server-side) — never
// in a cookie, never in the URL beyond an opaque state token.
//
// Required env to use Supabase Auth as the identity layer:
//   SUPABASE_ANON_KEY  — for emailing magic link from the user's side
// The redirect target Supabase Auth uses comes back to /oauth/authorize/callback.

// ─── GET /oauth/authorize ──────────────────────────────────────────────────
// Entry point. Validates the OAuth parameters, then renders the sign-in
// page. We DON'T issue the code yet — that happens after magic-link click.

export async function handleAuthorize(req: Request, env: Env): Promise<Response> {
  const url = new URL(req.url);
  const clientId = url.searchParams.get("client_id");
  const redirectUri = url.searchParams.get("redirect_uri");
  const responseType = url.searchParams.get("response_type");
  const codeChallenge = url.searchParams.get("code_challenge");
  const codeChallengeMethod =
    url.searchParams.get("code_challenge_method") ?? "S256";
  const scope = url.searchParams.get("scope") ?? "corpus:read";
  const state = url.searchParams.get("state") ?? undefined;

  if (!clientId || !redirectUri) {
    return errorPage({
      title: "Missing parameters",
      detail: "This sign-in link is missing required OAuth parameters. " +
        "Try installing the connector again from your LLM client.",
    });
  }
  if (responseType !== "code") {
    return errorPage({
      title: "Unsupported response type",
      detail: `Only response_type=code is supported (got ${responseType}).`,
    });
  }
  if (!codeChallenge) {
    return errorPage({
      title: "PKCE required",
      detail: "Your LLM client must send a PKCE code_challenge. " +
        "Modern Claude Desktop / ChatGPT clients do this automatically.",
    });
  }
  if (codeChallengeMethod !== "S256") {
    return errorPage({
      title: "Unsupported PKCE method",
      detail: `Only S256 is supported (got ${codeChallengeMethod}).`,
    });
  }

  // Confirm the client is registered and the redirect_uri matches one of
  // the whitelisted URIs from registration.
  const client = await getClient(env, clientId);
  if (!client || client.revoked_at) {
    return errorPage({
      title: "Client not registered",
      detail: "This client ID isn't recognized. " +
        "Try removing and re-adding the connector in your LLM.",
    });
  }
  if (!client.redirect_uris.includes(redirectUri)) {
    return errorPage({
      title: "Redirect URI mismatch",
      detail: "The redirect URI doesn't match what was registered.",
    });
  }

  // OK — render the sign-in form. Pass the OAuth params as hidden form
  // fields so they round-trip through the POST that sends the magic link.
  return signInPage({
    clientName: client.client_name ?? "Your LLM",
    formAction: "/oauth/authorize/email",
    hidden: {
      client_id: clientId,
      redirect_uri: redirectUri,
      response_type: responseType,
      code_challenge: codeChallenge,
      code_challenge_method: codeChallengeMethod,
      scope,
      ...(state ? { state } : {}),
    },
  });
}

// ─── POST /oauth/authorize/email ───────────────────────────────────────────
// User submits email. We send a magic link via Supabase Auth with a
// redirect_to that brings them back to /oauth/authorize/callback?login_state=...

export async function handleAuthorizeEmail(
  req: Request,
  env: Env,
): Promise<Response> {
  let form: URLSearchParams;
  try {
    const body = await req.text();
    form = new URLSearchParams(body);
  } catch {
    return errorPage({
      title: "Bad form submission",
      detail: "Could not parse the form body.",
    });
  }

  const email = (form.get("email") ?? "").trim();
  const clientId = form.get("client_id");
  const redirectUri = form.get("redirect_uri");
  const codeChallenge = form.get("code_challenge");
  const codeChallengeMethod = form.get("code_challenge_method") ?? "S256";
  const scope = form.get("scope") ?? "corpus:read";
  const oauthState = form.get("state") ?? undefined;

  if (!email || !clientId || !redirectUri || !codeChallenge) {
    return errorPage({
      title: "Missing fields",
      detail: "Email and OAuth parameters are all required.",
    });
  }

  if (codeChallengeMethod !== "S256") {
    return errorPage({
      title: "Unsupported PKCE method",
      detail: "Only S256 is supported.",
    });
  }

  // Persist the in-flight OAuth params keyed by a state token; the magic
  // link carries that state back to us on click.
  const loginToken = await createLoginState(env, {
    client_id: clientId,
    redirect_uri: redirectUri,
    scope,
    code_challenge: codeChallenge,
    code_challenge_method: "S256",
    oauth_state: oauthState,
    email,
  });

  const origin = new URL(req.url).origin;
  // Callback URL is the BARE base — no query string. Supabase Auth's
  // redirect URL allowlist matching doesn't reliably handle query strings,
  // so we pass login_state through an HttpOnly cookie instead. This keeps
  // the allowlist requirement to a single literal URL: ${origin}/oauth/
  // authorize/callback (no wildcards needed).
  const callbackUrl = `${origin}/oauth/authorize/callback`;

  console.log(`[oauth.email] sending magic link`);
  console.log(`[oauth.email]   email: ${email}`);
  console.log(`[oauth.email]   callbackUrl: ${callbackUrl}`);
  console.log(`[oauth.email]   origin from req.url: ${origin}`);
  console.log(`[oauth.email]   SUPABASE_URL env: ${env.SUPABASE_URL}`);
  console.log(`[oauth.email]   anon key present: ${(env as unknown as { SUPABASE_ANON_KEY?: string }).SUPABASE_ANON_KEY ? "yes (length=" + (env as unknown as { SUPABASE_ANON_KEY: string }).SUPABASE_ANON_KEY.length + ")" : "NO"}`);

  // Trigger Supabase Auth magic-link send. Uses the public anon key so
  // the rate-limiting / abuse-protection rules of Supabase Auth apply.
  const anonKey =
    (env as unknown as { SUPABASE_ANON_KEY?: string }).SUPABASE_ANON_KEY;
  if (!anonKey) {
    return errorPage({
      title: "Server not fully configured",
      detail:
        "SUPABASE_ANON_KEY is not set on the Worker. Ask the admin to add it.",
      status: 500,
    });
  }
  const authClient = createClient(env.SUPABASE_URL, anonKey, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
  const { data: otpData, error: otpErr } = await authClient.auth.signInWithOtp({
    email,
    options: {
      emailRedirectTo: callbackUrl,
      // Don't auto-create users — only existing preachers should be able
      // to sign in. If the email isn't in auth.users we'll fall through
      // to the "not linked" error after click.
      shouldCreateUser: false,
    },
  });
  console.log(`[oauth.email] signInWithOtp returned`);
  console.log(`[oauth.email]   error: ${otpErr ? otpErr.message : "(none)"}`);
  console.log(`[oauth.email]   error code: ${otpErr ? (otpErr as { status?: number }).status ?? "?" : "n/a"}`);
  console.log(`[oauth.email]   data: ${JSON.stringify(otpData)}`);
  if (otpErr) {
    // Email rate limit, bad email, etc. — show the sign-in page again
    // with the error message inline so the pastor can retry.
    const client = await getClient(env, clientId);
    return signInPage({
      clientName: client?.client_name ?? "Your LLM",
      formAction: "/oauth/authorize/email",
      hidden: {
        client_id: clientId,
        redirect_uri: redirectUri,
        response_type: "code",
        code_challenge: codeChallenge,
        code_challenge_method: "S256",
        scope,
        ...(oauthState ? { state: oauthState } : {}),
      },
      error: otpErr.message,
      prefillEmail: email,
    });
  }

  // Render the code-entry page. All OAuth params round-trip as hidden form
  // fields, plus we set a backup HttpOnly cookie carrying the same login
  // state — the hidden field is what the OTP handler reads, the cookie
  // remains for the magic-link callback fallback. Cookie scope matches
  // /oauth/authorize/* so it covers both /code and /callback paths.
  const resp = codeEntryPage({
    email,
    formAction: "/oauth/authorize/code",
    hidden: {
      client_id: clientId,
      redirect_uri: redirectUri,
      response_type: "code",
      code_challenge: codeChallenge,
      code_challenge_method: "S256",
      scope,
      login_state: loginToken,
      ...(oauthState ? { state: oauthState } : {}),
    },
  });
  resp.headers.set(
    "Set-Cookie",
    `sst_login_state=${encodeURIComponent(loginToken)}; ` +
      `Path=/oauth/authorize; ` +
      `Max-Age=600; ` +
      `HttpOnly; ` +
      `Secure; ` +
      `SameSite=Lax`,
  );
  return resp;
}

// ─── POST /oauth/authorize/code ────────────────────────────────────────────
// User submits the 6-digit OTP code Supabase mailed them. We verify with
// Supabase Auth synchronously (same tab, listener still alive), resolve the
// preacher, mint the OAuth authorization code, and redirect back to the
// MCP client's loopback callback. This is the primary path on Desktop —
// the magic-link callback is kept as a fallback for clients whose
// listener happens to outlive the email round-trip (rare).

export async function handleAuthorizeCode(
  req: Request,
  env: Env,
): Promise<Response> {
  let form: URLSearchParams;
  try {
    form = new URLSearchParams(await req.text());
  } catch {
    return errorPage({
      title: "Bad form submission",
      detail: "Could not parse the form body.",
    });
  }

  const token = (form.get("token") ?? "").trim();
  const clientId = form.get("client_id");
  const redirectUri = form.get("redirect_uri");
  const codeChallenge = form.get("code_challenge");
  const codeChallengeMethod = form.get("code_challenge_method") ?? "S256";
  const scope = form.get("scope") ?? "corpus:read";
  const oauthState = form.get("state") ?? undefined;
  // login_state may be in the form (preferred — survives strict cookie
  // policies) or fallback to the HttpOnly cookie set at email-submit time.
  const cookies = parseCookies(req);
  const loginToken =
    form.get("login_state") ?? cookies.sst_login_state ?? null;

  if (!token || !clientId || !redirectUri || !codeChallenge || !loginToken) {
    return errorPage({
      title: "Missing fields",
      detail: "Code and OAuth parameters are all required. " +
        "Restart sign-in from your LLM if this keeps happening.",
    });
  }
  if (codeChallengeMethod !== "S256") {
    return errorPage({
      title: "Unsupported PKCE method",
      detail: "Only S256 is supported.",
    });
  }

  // Look up the in-flight OAuth params WITHOUT consuming — a wrong code
  // attempt should let the pastor retry on the same page.
  const loginState = await peekLoginState(env, loginToken);
  if (!loginState) {
    return errorPage({
      title: "Sign-in expired",
      detail: "Your sign-in session expired or was already used. " +
        "Restart the connection from your LLM.",
    });
  }

  // Defense-in-depth: the params in the form must match what we stashed
  // server-side. If a client tries to swap client_id or redirect_uri after
  // we issued the OTP, reject.
  if (
    loginState.client_id !== clientId ||
    loginState.redirect_uri !== redirectUri ||
    loginState.code_challenge !== codeChallenge
  ) {
    return errorPage({
      title: "Sign-in parameters changed",
      detail: "The OAuth parameters don't match the original request. " +
        "Restart sign-in from your LLM.",
    });
  }

  const anonKey =
    (env as unknown as { SUPABASE_ANON_KEY?: string }).SUPABASE_ANON_KEY;
  if (!anonKey) {
    return errorPage({
      title: "Server not configured",
      detail: "SUPABASE_ANON_KEY missing on Worker.",
      status: 500,
    });
  }
  const authClient = createClient(env.SUPABASE_URL, anonKey, {
    auth: { persistSession: false, autoRefreshToken: false },
  });

  console.log(`[oauth.code] verifying OTP for ${loginState.email}`);
  const { data: verifyData, error: verifyErr } = await authClient.auth.verifyOtp({
    email: loginState.email,
    token,
    type: "email",
  });
  if (verifyErr || !verifyData?.user) {
    console.log(`[oauth.code]   verify error: ${verifyErr?.message ?? "(unknown)"}`);
    // Re-render the code page with the inline error so the pastor can retry.
    // Login state is INTACT (we used peek, not consume), so the same code
    // entry attempt can be retried up to Supabase's OTP attempt limit.
    return codeEntryPage({
      email: loginState.email,
      formAction: "/oauth/authorize/code",
      hidden: {
        client_id: clientId,
        redirect_uri: redirectUri,
        response_type: "code",
        code_challenge: codeChallenge,
        code_challenge_method: "S256",
        scope,
        login_state: loginToken,
        ...(oauthState ? { state: oauthState } : {}),
      },
      error: verifyErr?.message ?? "That code didn't work. Try again.",
    });
  }
  const authUserId = verifyData.user.id;
  console.log(`[oauth.code]   verified user ${authUserId}`);

  // Resolve the preacher row linked to this auth user.
  const supabase = adminClient(env);
  const { data: preacher, error: pErr } = await supabase
    .from("preachers")
    .select("id, name")
    .eq("auth_user_id", authUserId)
    .maybeSingle();
  if (pErr || !preacher) {
    // OTP verified, but no preacher row links to this user. Don't render
    // the code page again — the pastor will keep retrying with valid codes
    // and getting the same error. Surface the actionable detail instead.
    return errorPage({
      title: "Not linked to a preacher",
      detail:
        `Signed in successfully as ${loginState.email} but this account ` +
        `isn't linked to a preacher profile in Sermon Steward. ` +
        `Contact the admin to link your auth user ID (${authUserId}) ` +
        `to your preacher row.`,
    });
  }

  // Bind the DCR'd client to this preacher on first use (no-op afterwards).
  await bindClientToPreacher(env, loginState.client_id, preacher.id);

  // Mint the OAuth authorization code and redirect to the MCP client's
  // loopback callback. Cleanup: delete the login_state (we held it open
  // for retries; now it's spent).
  const code = await issueAuthorizationCode(env, {
    client_id: loginState.client_id,
    preacher_id: preacher.id,
    redirect_uri: loginState.redirect_uri,
    scope: loginState.scope,
    code_challenge: loginState.code_challenge,
    code_challenge_method: loginState.code_challenge_method as "S256",
  });
  await deleteLoginState(env, loginToken);

  const redirect = new URL(loginState.redirect_uri);
  redirect.searchParams.set("code", code);
  if (loginState.oauth_state) {
    redirect.searchParams.set("state", loginState.oauth_state);
  }

  // Clear the backup cookie now that we've consumed the login state.
  const successResp = successPage(redirect.toString());
  successResp.headers.set(
    "Set-Cookie",
    "sst_login_state=; Path=/oauth/authorize; Max-Age=0; HttpOnly; Secure; SameSite=Lax",
  );
  return successResp;
}

// ─── POST /oauth/authorize/callback/exchange ───────────────────────────────
// Called by the fragment-bouncer page (above) with the access_token + refresh
// token pulled from the URL fragment. We verify the token with Supabase Auth
// (which gives us the auth_user_id), resolve the preacher, issue the OAuth
// authorization code, and redirect back to the client.

export async function handleAuthorizeCallbackExchange(
  req: Request,
  env: Env,
): Promise<Response> {
  let form: URLSearchParams;
  try {
    form = new URLSearchParams(await req.text());
  } catch {
    return errorPage({
      title: "Bad exchange request",
      detail: "Could not parse the form body.",
    });
  }
  const accessToken = form.get("access_token");
  if (!accessToken) {
    return errorPage({
      title: "Missing access token",
      detail: "The fragment-bouncer didn't include an access_token. " +
        "Try the sign-in link again.",
    });
  }

  const cookies = parseCookies(req);
  const loginToken = cookies.sst_login_state;
  console.log(`[oauth.exchange] entry`);
  console.log(`[oauth.exchange]   accessToken: ${accessToken.slice(0, 20)}...`);
  console.log(`[oauth.exchange]   loginToken cookie: ${loginToken ? "present" : "MISSING"}`);

  if (!loginToken) {
    return errorPage({
      title: "Missing login state",
      detail: "The login-state cookie was not present on this request. " +
        "Restart sign-in from your LLM.",
    });
  }

  // Look up the in-flight OAuth params we stashed before sending the email.
  const loginState = await consumeLoginState(env, loginToken);
  if (!loginState) {
    return errorPage({
      title: "Sign-in expired",
      detail: "Your sign-in session expired or was already used. " +
        "Restart the connection from your LLM.",
    });
  }

  // Verify the access token with Supabase Auth's getUser endpoint.
  const anonKey =
    (env as unknown as { SUPABASE_ANON_KEY?: string }).SUPABASE_ANON_KEY;
  if (!anonKey) {
    return errorPage({
      title: "Server not configured",
      detail: "SUPABASE_ANON_KEY missing on Worker.",
      status: 500,
    });
  }
  const authClient = createClient(env.SUPABASE_URL, anonKey, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
  const { data: userData, error: userErr } =
    await authClient.auth.getUser(accessToken);
  console.log(`[oauth.exchange]   getUser error: ${userErr?.message ?? "(none)"}`);
  console.log(`[oauth.exchange]   getUser user id: ${userData?.user?.id ?? "(none)"}`);
  if (userErr || !userData?.user) {
    return errorPage({
      title: "Sign-in failed",
      detail: userErr?.message ?? "Could not verify the access token.",
    });
  }
  const authUserId = userData.user.id;

  // Look up the preacher row linked to this auth user.
  const supabase = adminClient(env);
  const { data: preacher, error: pErr } = await supabase
    .from("preachers")
    .select("id, name")
    .eq("auth_user_id", authUserId)
    .maybeSingle();
  if (pErr || !preacher) {
    return errorPage({
      title: "Not linked to a preacher",
      detail:
        `Signed in successfully as ${loginState.email} but this account ` +
        `isn't linked to a preacher profile in Sermon Steward. ` +
        `Contact the admin to link your auth user ID (${authUserId}) ` +
        `to your preacher row.`,
    });
  }

  // First-time clients get bound to this preacher; subsequent calls are no-ops.
  await bindClientToPreacher(env, loginState.client_id, preacher.id);

  // Mint the authorization code and redirect back to the MCP client.
  const code = await issueAuthorizationCode(env, {
    client_id: loginState.client_id,
    preacher_id: preacher.id,
    redirect_uri: loginState.redirect_uri,
    scope: loginState.scope,
    code_challenge: loginState.code_challenge,
    code_challenge_method: loginState.code_challenge_method as "S256",
  });

  const redirect = new URL(loginState.redirect_uri);
  redirect.searchParams.set("code", code);
  if (loginState.oauth_state) {
    redirect.searchParams.set("state", loginState.oauth_state);
  }

  // Clear the login state cookie now that we've consumed it.
  const successResp = successPage(redirect.toString());
  successResp.headers.set(
    "Set-Cookie",
    "sst_login_state=; Path=/oauth/authorize; Max-Age=0; HttpOnly; Secure; SameSite=Lax",
  );
  return successResp;
}

// Parse cookies from a Cookie request header into a name→value map.
function parseCookies(req: Request): Record<string, string> {
  const cookieHeader = req.headers.get("cookie") ?? "";
  const result: Record<string, string> = {};
  for (const part of cookieHeader.split(";")) {
    const eq = part.indexOf("=");
    if (eq === -1) continue;
    const name = part.slice(0, eq).trim();
    const value = part.slice(eq + 1).trim();
    if (name) result[name] = decodeURIComponent(value);
  }
  return result;
}

// ─── GET /oauth/authorize/callback ─────────────────────────────────────────
// Magic link click lands here. Supabase Auth provides a `token_hash` (PKCE
// flow) or appends `#access_token=…` to the URL fragment. We rely on the
// query-string `token_hash` + `type=email` parameters Supabase passes by
// default for email OTP confirmations.

export async function handleAuthorizeCallback(
  req: Request,
  env: Env,
): Promise<Response> {
  const url = new URL(req.url);
  // login_state is read from an HttpOnly cookie set during /oauth/authorize/email.
  // (Previously this was in the URL query string, but Supabase Auth's redirect
  // allowlist matching rejects URLs with query strings.)
  const cookies = parseCookies(req);
  const loginToken =
    cookies.sst_login_state ?? url.searchParams.get("login_state") ?? null;
  const tokenHash = url.searchParams.get("token_hash");
  const type = url.searchParams.get("type") ?? "email";

  console.log(`[oauth.callback] entry`);
  console.log(`[oauth.callback]   loginToken: ${loginToken ? "present" : "MISSING"}`);
  console.log(`[oauth.callback]   tokenHash: ${tokenHash ? "present" : "MISSING"}`);
  console.log(`[oauth.callback]   type: ${type}`);

  if (!loginToken) {
    return errorPage({
      title: "Missing login state",
      detail: "We couldn't find the login-state cookie. This usually means " +
        "you opened the magic link on a different device or browser than the " +
        "one you started sign-in on. Restart sign-in on the same device.",
    });
  }

  // When Supabase uses its default magic-link flow, the access_token comes
  // back in the URL FRAGMENT (#access_token=...) which is browser-only and
  // never reaches the server. If we got here without a token_hash in the
  // query, return a tiny client-side bouncer page that reads the fragment
  // and POSTs the tokens back to /oauth/authorize/callback/exchange.
  if (!tokenHash) {
    console.log(`[oauth.callback] no token_hash in query — returning fragment bouncer`);
    return fragmentBouncerPage();
  }

  // Re-fetch the OAuth params we stashed before sending the email.
  const loginState = await consumeLoginState(env, loginToken);
  if (!loginState) {
    return errorPage({
      title: "Sign-in expired",
      detail: "Your sign-in link expired or was already used. " +
        "Restart the connection from your LLM.",
    });
  }

  // Verify the magic-link token with Supabase Auth.
  const anonKey =
    (env as unknown as { SUPABASE_ANON_KEY?: string }).SUPABASE_ANON_KEY;
  if (!anonKey) {
    return errorPage({
      title: "Server not configured",
      detail: "SUPABASE_ANON_KEY missing on Worker.",
      status: 500,
    });
  }
  const authClient = createClient(env.SUPABASE_URL, anonKey, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
  const { data: verifyData, error: verifyErr } =
    await authClient.auth.verifyOtp({
      token_hash: tokenHash,
      type: type as "email" | "magiclink",
    });
  if (verifyErr || !verifyData?.user) {
    return errorPage({
      title: "Sign-in failed",
      detail: verifyErr?.message ?? "Could not verify the link.",
    });
  }
  const authUserId = verifyData.user.id;

  // Look up the preacher row linked to this auth user.
  const supabase = adminClient(env);
  const { data: preacher, error: pErr } = await supabase
    .from("preachers")
    .select("id, name")
    .eq("auth_user_id", authUserId)
    .maybeSingle();
  if (pErr || !preacher) {
    return errorPage({
      title: "Not linked to a preacher",
      detail:
        `Signed in successfully as ${loginState.email} but this account ` +
        `isn't linked to a preacher profile in Sermon Steward. ` +
        `Contact the admin to link your auth user ID (${authUserId}) ` +
        `to your preacher row.`,
    });
  }

  // First-time clients get bound to this preacher; subsequent calls are no-ops.
  await bindClientToPreacher(env, loginState.client_id, preacher.id);

  // Mint the authorization code and redirect back to the MCP client.
  const code = await issueAuthorizationCode(env, {
    client_id: loginState.client_id,
    preacher_id: preacher.id,
    redirect_uri: loginState.redirect_uri,
    scope: loginState.scope,
    code_challenge: loginState.code_challenge,
    code_challenge_method: loginState.code_challenge_method as "S256",
  });

  const redirect = new URL(loginState.redirect_uri);
  redirect.searchParams.set("code", code);
  if (loginState.oauth_state) {
    redirect.searchParams.set("state", loginState.oauth_state);
  }
  return successPage(redirect.toString());
}
