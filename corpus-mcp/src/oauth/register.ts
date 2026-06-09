import type { Env } from "../types";
import { registerClient } from "./store";

// Dynamic Client Registration (RFC 7591).
//
// MCP clients (Claude Desktop, Claude.ai, ChatGPT) POST here to register
// themselves silently — no admin approval. They send:
//
//   {
//     "client_name": "Claude Desktop",
//     "redirect_uris": ["http://localhost:33418/oauth/callback"],
//     "token_endpoint_auth_method": "none"
//   }
//
// We mint a client_id and return it. Because we require PKCE, there's no
// client_secret to manage — the security comes from the code-challenge/
// verifier pair the client generates per authorization attempt.
//
// One row per registration. A single pastor will accumulate clients as
// they install on new devices; that's fine.

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Allow-Headers": "content-type",
};

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...CORS },
  });
}

function errorResponse(error: string, description: string, status = 400) {
  return jsonResponse({ error, error_description: description }, status);
}

interface RegistrationRequest {
  client_name?: unknown;
  redirect_uris?: unknown;
  token_endpoint_auth_method?: unknown;
  grant_types?: unknown;
  response_types?: unknown;
}

export async function handleRegister(req: Request, env: Env): Promise<Response> {
  if (req.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: CORS });
  }
  if (req.method !== "POST") {
    return errorResponse("invalid_request", "Method must be POST", 405);
  }

  let body: RegistrationRequest;
  try {
    body = (await req.json()) as RegistrationRequest;
  } catch {
    return errorResponse("invalid_request", "Body must be JSON");
  }

  // Validate redirect_uris — required, must be at least one valid URL.
  if (!Array.isArray(body.redirect_uris) || body.redirect_uris.length === 0) {
    return errorResponse(
      "invalid_redirect_uri",
      "At least one redirect_uri is required",
    );
  }
  const redirectUris: string[] = [];
  for (const u of body.redirect_uris) {
    if (typeof u !== "string") {
      return errorResponse("invalid_redirect_uri", "Each URI must be a string");
    }
    try {
      const parsed = new URL(u);
      // Allow http only for localhost (Claude Desktop callback) and https
      // for everything else.
      if (
        parsed.protocol !== "https:" &&
        !(parsed.protocol === "http:" &&
          (parsed.hostname === "localhost" || parsed.hostname === "127.0.0.1"))
      ) {
        return errorResponse(
          "invalid_redirect_uri",
          `URI must use https (or http for localhost): ${u}`,
        );
      }
      redirectUris.push(u);
    } catch {
      return errorResponse("invalid_redirect_uri", `Malformed URI: ${u}`);
    }
  }

  // We only support PKCE / public clients in v1.
  const authMethod =
    typeof body.token_endpoint_auth_method === "string"
      ? body.token_endpoint_auth_method
      : "none";
  if (authMethod !== "none") {
    return errorResponse(
      "invalid_client_metadata",
      "Only token_endpoint_auth_method=\"none\" is supported (PKCE required)",
    );
  }

  const clientName =
    typeof body.client_name === "string" ? body.client_name : undefined;

  try {
    const client = await registerClient(env, {
      client_name: clientName,
      redirect_uris: redirectUris,
      token_endpoint_auth_method: "none",
    });
    return jsonResponse(
      {
        client_id: client.client_id,
        client_name: client.client_name,
        redirect_uris: client.redirect_uris,
        token_endpoint_auth_method: "none",
        grant_types: ["authorization_code", "refresh_token"],
        response_types: ["code"],
        scope: client.scope,
      },
      201,
    );
  } catch (err) {
    console.error("[oauth] /register failed", err);
    return errorResponse(
      "server_error",
      "Registration failed; please retry",
      500,
    );
  }
}
