import type { Env, JsonRpcRequest, JsonRpcResponse } from "./types";
import {
  AuthError,
  authenticate,
  authenticateByChurchSlug,
  authenticateBySlug,
  authenticateGuildHall,
} from "./auth";
import { TOOLS, callTool } from "./tools";
import { listPromptsForAuth, renderPrompt } from "./prompts";
import {
  authorizationServerMetadata,
  protectedResourceMetadata,
  unauthenticatedResponse,
} from "./oauth/metadata";
import { handleRegister } from "./oauth/register";
import {
  handleAuthorize,
  handleAuthorizeCallback,
  handleAuthorizeCallbackExchange,
  handleAuthorizeCode,
  handleAuthorizeEmail,
} from "./oauth/authorize";
import { handleToken } from "./oauth/token";

// Sermon Steward — Model Context Protocol server.
//
// Cloudflare Worker that lets a pastor's LLM client (Claude Desktop,
// Claude.ai, ChatGPT with MCP) query that pastor's own preaching corpus
// as a first-class tool.
//
// Protocol: JSON-RPC 2.0 over HTTP. We implement just the methods MCP
// clients actually call:
//   - initialize           (handshake, capabilities)
//   - tools/list           (advertise the four tools)
//   - tools/call           (execute a tool)
//   - prompts/list         (advertise voice/context prompts)
//   - prompts/get          (return a rendered prompt message)
//   - notifications/initialized   (no-op ack)
//   - ping                 (liveness)
//
// Auth: Bearer token in the Authorization header. Validated on every
// JSON-RPC call except `initialize` and `ping` (those are safe pre-auth
// for capability negotiation).
//
// CORS: open to all origins for tool calls. Clients run in-browser
// (claude.ai connectors) or in desktop apps with arbitrary origins.

const PROTOCOL_VERSION = "2025-03-26";
const SERVER_INFO = {
  name: "sermon-steward",
  version: "0.1.0",
} as const;

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
  "Access-Control-Allow-Headers": "authorization, content-type, mcp-session-id",
  "Access-Control-Expose-Headers": "mcp-session-id",
};

function jsonResponse(body: unknown, status = 200, extra: HeadersInit = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json",
      ...CORS_HEADERS,
      ...extra,
    },
  });
}

function rpcOk(id: JsonRpcRequest["id"], result: unknown): JsonRpcResponse {
  return { jsonrpc: "2.0", id: id ?? null, result };
}

function rpcErr(
  id: JsonRpcRequest["id"],
  code: number,
  message: string,
  data?: unknown,
): JsonRpcResponse {
  return { jsonrpc: "2.0", id: id ?? null, error: { code, message, data } };
}

// Standard JSON-RPC error codes — clients log/display these distinctly.
const RPC_PARSE_ERROR = -32700;
const RPC_INVALID_REQUEST = -32600;
const RPC_METHOD_NOT_FOUND = -32601;
const RPC_INVALID_PARAMS = -32602;
const RPC_INTERNAL_ERROR = -32603;

export default {
  async fetch(req: Request, env: Env): Promise<Response> {
    const url = new URL(req.url);
    const pathname = url.pathname;

    // ─── CORS preflight ────────────────────────────────────────────────────
    if (req.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: CORS_HEADERS });
    }

    // ─── OAuth discovery + flow endpoints ──────────────────────────────────
    // Order matters: discovery + OAuth routes are handled before MCP routing
    // so they don't get treated as JSON-RPC payloads.
    if (req.method === "GET" && pathname === "/.well-known/oauth-protected-resource") {
      return protectedResourceMetadata(req);
    }
    if (req.method === "GET" && pathname === "/.well-known/oauth-authorization-server") {
      return authorizationServerMetadata(req);
    }
    if (pathname === "/oauth/register") {
      return handleRegister(req, env);
    }
    if (req.method === "GET" && pathname === "/oauth/authorize") {
      return handleAuthorize(req, env);
    }
    if (req.method === "POST" && pathname === "/oauth/authorize/email") {
      return handleAuthorizeEmail(req, env);
    }
    // OTP code submission — the primary auth path on Desktop. Stays in the
    // same tab as the email submission so Claude Desktop's loopback listener
    // is still alive when we redirect.
    if (req.method === "POST" && pathname === "/oauth/authorize/code") {
      return handleAuthorizeCode(req, env);
    }
    if (req.method === "GET" && pathname === "/oauth/authorize/callback") {
      return handleAuthorizeCallback(req, env);
    }
    if (req.method === "POST" && pathname === "/oauth/authorize/callback/exchange") {
      return handleAuthorizeCallbackExchange(req, env);
    }
    if (pathname === "/oauth/token") {
      return handleToken(req, env);
    }

    // ─── Streamable-HTTP standalone SSE probe → 405 ────────────────────────
    // MCP's Streamable HTTP transport lets a client open a standalone
    // server→client notification stream by issuing GET <endpoint> with
    // `Accept: text/event-stream`. A server that does NOT offer such a
    // stream MUST answer 405 Method Not Allowed (MCP spec, 2025-03-26) —
    // that's the signal telling the client to fall back to plain
    // request/response over POST, which is all we implement.
    //
    // Without this, a GET on the MCP endpoint fell through to the
    // friendly landing page (HTTP 200, text/plain). Lenient clients
    // (Claude, ChatGPT, Grok) ignore that; stricter ones (Perplexity,
    // 2026-06-13) see a 200 that is neither SSE nor a 405 and declare
    // the whole connector TEMPORARILY_UNAVAILABLE — tools never load
    // even though auth + POST tools/list work perfectly.
    //
    // Gated strictly on the event-stream Accept so browser landing-page
    // GETs (text/html, */*) and the OAuth/discovery GETs above are
    // untouched.
    if (req.method === "GET") {
      const accept = req.headers.get("accept") || "";
      if (accept.includes("text/event-stream")) {
        return new Response(
          "This MCP server uses request/response over POST and does not " +
            "offer a standalone SSE stream. Send JSON-RPC via POST.",
          { status: 405, headers: { ...CORS_HEADERS, Allow: "POST" } },
        );
      }
    }

    // ─── GET / — friendly landing page ─────────────────────────────────────
    if (req.method === "GET" && pathname === "/") {
      return new Response(
        `Sermon Steward MCP server — ${SERVER_INFO.version}\n\n` +
          `This URL is meant to be added as a Model Context Protocol\n` +
          `connector in Claude Desktop, Claude.ai, or ChatGPT.\n\n` +
          `Public per-preacher endpoints:\n` +
          `  https://corpus-mcp.chris-386.workers.dev/p/<preacher-slug>\n` +
          `  (example: /p/chris-oswald, /p/ricky-alcantar, /p/charles-spurgeon)\n\n` +
          `Public church-wide endpoints (all preachers at one church):\n` +
          `  https://corpus-mcp.chris-386.workers.dev/c/<church-slug>\n` +
          `  (example: /c/cross-of-grace-church)\n` +
          `  Add ?speaker=<preacher-slug> to narrow to one preacher at\n` +
          `  that church without changing the connector URL.\n\n` +
          `Guild Hall — canonical Reformed reference library:\n` +
          `  https://corpus-mcp.chris-386.workers.dev/g\n` +
          `  Spans Piper, Keller, Spurgeon, MacArthur, Lloyd-Jones,\n` +
          `  Sproul, Ferguson, DeYoung, Carson, Watson, and more.\n` +
          `  Add ?speaker=<slug> to narrow to one Guild member.\n\n` +
          `Setup guides:\n` +
          `  https://sermonsteward.com/study/connect\n`,
        { status: 200, headers: { "Content-Type": "text/plain" } },
      );
    }

    // ─── GET /p/:slug — preacher-scoped landing page ───────────────────────
    // Friendly text for someone who pastes the URL into a browser instead
    // of adding it as an MCP connector. POSTs to the same path get
    // JSON-RPC handling below.
    const slugMatch = pathname.match(/^\/p\/([a-z0-9-]+)\/?$/);
    if (req.method === "GET" && slugMatch) {
      const slug = slugMatch[1];
      return new Response(
        `Sermon Steward MCP — scoped to /p/${slug}\n\n` +
          `Add this URL as a Model Context Protocol connector in\n` +
          `Claude Desktop, Cowork, or ChatGPT to query this preacher's\n` +
          `corpus. No auth required — sermon material is public.\n\n` +
          `Discovery + per-pastor pages:\n` +
          `  https://sermonsteward.com/pastors/${slug}\n`,
        { status: 200, headers: { "Content-Type": "text/plain" } },
      );
    }

    // ─── GET /c/:slug — church-scoped landing page ─────────────────────────
    // Same friendly text idea, but for the whole-church endpoint. POSTs hit
    // the JSON-RPC handler below, which routes auth through
    // authenticateByChurchSlug.
    const churchSlugMatch = pathname.match(/^\/c\/([a-z0-9-]+)\/?$/);
    const churchSpeakerFilter = url.searchParams.get("speaker");
    if (req.method === "GET" && churchSlugMatch) {
      const slug = churchSlugMatch[1];
      return new Response(
        `Sermon Steward MCP — scoped to /c/${slug}\n\n` +
          `Whole-church corpus: every sermon from every preacher at this\n` +
          `church flows through here, properly attributed. Add this URL as\n` +
          `an MCP connector in Claude Desktop, Cowork, or ChatGPT. No\n` +
          `auth required — sermon material is public.\n\n` +
          (churchSpeakerFilter
            ? `Currently filtered to speaker: ${churchSpeakerFilter}\n\n`
            : `Add ?speaker=<preacher-slug> to narrow to one preacher\n` +
              `(e.g. /c/${slug}?speaker=ricky-alcantar).\n\n`) +
          `Discovery + per-church pages:\n` +
          `  https://sermonsteward.com/churches/${slug}\n`,
        { status: 200, headers: { "Content-Type": "text/plain" } },
      );
    }

    // ─── GET /g — Guild Hall landing page ──────────────────────────────────
    // The canonical Reformed reference library, queryable as one corpus.
    // POSTs to /g hit the JSON-RPC handler below, which routes auth
    // through authenticateGuildHall.
    const guildPathMatch = pathname.match(/^\/g\/?$/);
    const guildSpeakerFilter = url.searchParams.get("speaker");
    if (req.method === "GET" && guildPathMatch) {
      return new Response(
        `Sermon Steward MCP — Guild Hall\n\n` +
          `The canonical Reformed reference library: Piper, Keller,\n` +
          `Spurgeon, MacArthur, Lloyd-Jones, Sproul, Ferguson, DeYoung,\n` +
          `Carson, Watson, Mahaney, Boice, Stott, Robinson, Baucham,\n` +
          `Campbell Morgan, S. Lewis Johnson, and David VanAcker.\n\n` +
          `Add this URL as an MCP connector in Claude Desktop, Cowork,\n` +
          `or ChatGPT. No auth required — material is public.\n\n` +
          (guildSpeakerFilter
            ? `Currently filtered to speaker: ${guildSpeakerFilter}\n\n`
            : `Add ?speaker=<preacher-slug> to narrow to one member\n` +
              `(e.g. /g?speaker=charles-spurgeon).\n\n`) +
          `Discovery + Guild Hall index:\n` +
          `  https://sermonsteward.com/guild-hall\n`,
        { status: 200, headers: { "Content-Type": "text/plain" } },
      );
    }

    if (req.method !== "POST") {
      return jsonResponse(
        { error: "Use POST with a JSON-RPC 2.0 message" },
        405,
      );
    }

    // Parse JSON-RPC message
    let msg: JsonRpcRequest;
    try {
      msg = (await req.json()) as JsonRpcRequest;
    } catch {
      return jsonResponse(
        rpcErr(null, RPC_PARSE_ERROR, "Invalid JSON"),
        400,
      );
    }

    if (msg.jsonrpc !== "2.0" || typeof msg.method !== "string") {
      return jsonResponse(
        rpcErr(msg.id ?? null, RPC_INVALID_REQUEST, "Not a JSON-RPC 2.0 request"),
        400,
      );
    }

    // Methods that don't require auth (handshake + liveness).
    if (msg.method === "initialize") {
      return jsonResponse(
        rpcOk(msg.id, {
          protocolVersion: PROTOCOL_VERSION,
          capabilities: {
            tools: { listChanged: false },
            prompts: { listChanged: false },
          },
          serverInfo: SERVER_INFO,
          instructions:
            "A pastor's own decomposed sermon corpus. Use the single " +
            "ask_corpus tool for everything — search, full-sermon pulls, " +
            "browsing by date, and serendipity. Pass the pastor's question " +
            "through in their own words; the tool routes internally. " +
            "Cite results by sermon title and date. Never invent quotes " +
            "or claims attributed to the preacher.",
        }),
      );
    }
    if (msg.method === "ping") {
      return jsonResponse(rpcOk(msg.id, {}));
    }
    if (msg.method === "notifications/initialized") {
      // MCP clients send this as a one-way notification after handshake.
      // No response body required; return 204.
      return new Response(null, { status: 204, headers: CORS_HEADERS });
    }

    // Everything below this point requires identity resolution.
    //
    // Four paths:
    //   /p/:slug   — preacher-scoped public read. Identity comes from the
    //                URL path. Tool queries filter by that preacher_id.
    //   /c/:slug   — church-scoped public read. Identity is the whole
    //                church roster. Tool queries filter by
    //                preacher_id IN preacher_ids. Optional ?speaker=
    //                narrows to one preacher inside the church.
    //   /g         — Guild Hall public read. Identity is the canonical
    //                reference library (preachers.church_id IS NULL).
    //                Tool queries filter by preacher_id IN preacher_ids.
    //                Optional ?speaker= narrows to one Guild member.
    //   anything   — legacy bearer-token path (sst_* via mcp_tokens, or
    //                sst_oauth_* via oauth_access_tokens). Kept for
    //                backward compatibility with existing pastor configs.
    const isPublicSlugPath = Boolean(slugMatch || churchSlugMatch || guildPathMatch);
    let auth;
    try {
      if (slugMatch) {
        auth = await authenticateBySlug(slugMatch[1], env);
      } else if (churchSlugMatch) {
        auth = await authenticateByChurchSlug(
          churchSlugMatch[1],
          churchSpeakerFilter,
          env,
        );
      } else if (guildPathMatch) {
        auth = await authenticateGuildHall(guildSpeakerFilter, env);
      } else {
        auth = await authenticate(req, env);
      }
    } catch (err) {
      if (err instanceof AuthError) {
        // 401 responses carry a WWW-Authenticate header that points the
        // MCP client at the OAuth protected-resource metadata, kicking
        // off the discovery flow. This is how Claude Desktop / Claude.ai
        // know to show "Sign in" instead of failing silently.
        //
        // Public slug path errors (404 unknown / 400 malformed) are
        // returned verbatim — no OAuth dance, since those paths are
        // public-read and clients shouldn't be redirected to sign in
        // for a bad URL.
        if (err.status === 401 && !isPublicSlugPath) {
          const origin = new URL(req.url).origin;
          return jsonResponse(
            rpcErr(msg.id ?? null, -32001, err.message),
            401,
            {
              "WWW-Authenticate":
                `Bearer resource_metadata="${origin}/.well-known/oauth-protected-resource"`,
            },
          );
        }
        return jsonResponse(
          rpcErr(msg.id ?? null, -32001, err.message),
          err.status,
        );
      }
      return jsonResponse(
        rpcErr(msg.id ?? null, RPC_INTERNAL_ERROR, "Auth failed"),
        500,
      );
    }

    try {
      switch (msg.method) {
        case "tools/list":
          return jsonResponse(
            rpcOk(msg.id, {
              tools: TOOLS.map((t) => ({
                name: t.name,
                description: t.description,
                inputSchema: t.inputSchema,
              })),
            }),
          );

        case "tools/call": {
          const params = (msg.params ?? {}) as {
            name?: string;
            arguments?: Record<string, unknown>;
          };
          if (typeof params.name !== "string") {
            return jsonResponse(
              rpcErr(msg.id ?? null, RPC_INVALID_PARAMS, "Missing tool name"),
            );
          }
          const result = await callTool(
            params.name,
            params.arguments ?? {},
            auth,
            env,
          );
          return jsonResponse(rpcOk(msg.id, result));
        }

        case "prompts/list":
          return jsonResponse(
            rpcOk(msg.id, { prompts: listPromptsForAuth(auth) }),
          );

        case "prompts/get": {
          const params = (msg.params ?? {}) as {
            name?: string;
            arguments?: Record<string, string>;
          };
          if (typeof params.name !== "string") {
            return jsonResponse(
              rpcErr(msg.id ?? null, RPC_INVALID_PARAMS, "Missing prompt name"),
            );
          }
          const rendered = renderPrompt(
            params.name,
            params.arguments ?? {},
            auth,
          );
          if (!rendered) {
            return jsonResponse(
              rpcErr(msg.id ?? null, RPC_INVALID_PARAMS, "Unknown prompt"),
            );
          }
          return jsonResponse(rpcOk(msg.id, rendered));
        }

        default:
          return jsonResponse(
            rpcErr(
              msg.id ?? null,
              RPC_METHOD_NOT_FOUND,
              `Method not found: ${msg.method}`,
            ),
          );
      }
    } catch (err) {
      console.error("MCP handler error", err);
      return jsonResponse(
        rpcErr(
          msg.id ?? null,
          RPC_INTERNAL_ERROR,
          (err as Error).message || "Internal server error",
        ),
        500,
      );
    }
  },
};
