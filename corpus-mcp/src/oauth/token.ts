import type { Env } from "../types";
import {
  consumeAuthorizationCode,
  exchangeRefreshToken,
  getClient,
  issueAccessToken,
  verifyPkceS256,
} from "./store";

// POST /oauth/token — two grant types:
//
//   grant_type=authorization_code
//     Exchanges a code (issued at /authorize) for an access_token. PKCE
//     verification happens here: we hashed the code_challenge into the
//     code's row; client provides code_verifier; we hash + compare.
//
//   grant_type=refresh_token
//     Rotates an expired access_token using its refresh_token. The old
//     access_token + refresh_token are revoked; a new pair is issued.
//
// Public clients (token_endpoint_auth_method=none) authenticate ONLY via
// PKCE — no client_secret. This matches OAuth 2.1 best practice for
// installable apps like Claude Desktop and ChatGPT.

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Allow-Headers": "content-type, authorization",
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json",
      "Cache-Control": "no-store",
      ...CORS,
    },
  });
}

function errorResponse(
  error: string,
  description: string,
  status = 400,
): Response {
  return jsonResponse({ error, error_description: description }, status);
}

export async function handleToken(req: Request, env: Env): Promise<Response> {
  if (req.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: CORS });
  }
  if (req.method !== "POST") {
    return errorResponse("invalid_request", "Method must be POST", 405);
  }

  // Token endpoint accepts application/x-www-form-urlencoded per OAuth spec.
  let form: URLSearchParams;
  const ctype = req.headers.get("content-type") ?? "";
  if (ctype.includes("application/x-www-form-urlencoded")) {
    form = new URLSearchParams(await req.text());
  } else if (ctype.includes("application/json")) {
    // Be lenient — some MCP clients have sent JSON in the wild.
    const body = (await req.json().catch(() => ({}))) as Record<string, unknown>;
    form = new URLSearchParams();
    for (const [k, v] of Object.entries(body)) {
      if (typeof v === "string") form.set(k, v);
    }
  } else {
    return errorResponse(
      "invalid_request",
      "Content-Type must be application/x-www-form-urlencoded or application/json",
    );
  }

  const grantType = form.get("grant_type");
  if (!grantType) {
    return errorResponse("invalid_request", "Missing grant_type");
  }

  if (grantType === "authorization_code") {
    return handleCodeExchange(form, env);
  }
  if (grantType === "refresh_token") {
    return handleRefresh(form, env);
  }
  return errorResponse(
    "unsupported_grant_type",
    `grant_type ${grantType} is not supported`,
  );
}

// ─── grant_type=authorization_code ─────────────────────────────────────────
async function handleCodeExchange(
  form: URLSearchParams,
  env: Env,
): Promise<Response> {
  const code = form.get("code");
  const clientId = form.get("client_id");
  const redirectUri = form.get("redirect_uri");
  const codeVerifier = form.get("code_verifier");

  if (!code || !clientId || !redirectUri || !codeVerifier) {
    return errorResponse(
      "invalid_request",
      "code, client_id, redirect_uri, and code_verifier are all required",
    );
  }

  const client = await getClient(env, clientId);
  if (!client || client.revoked_at) {
    return errorResponse("invalid_client", "Unknown client_id");
  }

  // Consume the code (one-time read). If already used or expired, reject.
  const codeRow = await consumeAuthorizationCode(env, code);
  if (!codeRow) {
    return errorResponse(
      "invalid_grant",
      "Authorization code is invalid, expired, or already used",
    );
  }
  if (codeRow.client_id !== clientId) {
    return errorResponse(
      "invalid_grant",
      "Code was issued to a different client",
    );
  }
  if (codeRow.redirect_uri !== redirectUri) {
    return errorResponse(
      "invalid_grant",
      "redirect_uri does not match the original authorization request",
    );
  }

  // PKCE: hash the verifier and compare to the stored challenge.
  const pkceOk = await verifyPkceS256(codeVerifier, codeRow.code_challenge);
  if (!pkceOk) {
    return errorResponse(
      "invalid_grant",
      "PKCE verification failed",
    );
  }

  const pair = await issueAccessToken(env, {
    client_id: clientId,
    preacher_id: codeRow.preacher_id,
    scope: codeRow.scope,
  });
  return jsonResponse(pair);
}

// ─── grant_type=refresh_token ──────────────────────────────────────────────
async function handleRefresh(
  form: URLSearchParams,
  env: Env,
): Promise<Response> {
  const refreshToken = form.get("refresh_token");
  const clientId = form.get("client_id");

  if (!refreshToken || !clientId) {
    return errorResponse(
      "invalid_request",
      "refresh_token and client_id are required",
    );
  }

  const client = await getClient(env, clientId);
  if (!client || client.revoked_at) {
    return errorResponse("invalid_client", "Unknown client_id");
  }

  const pair = await exchangeRefreshToken(env, refreshToken);
  if (!pair) {
    return errorResponse(
      "invalid_grant",
      "Refresh token is invalid, expired, or already rotated",
    );
  }
  return jsonResponse(pair);
}
