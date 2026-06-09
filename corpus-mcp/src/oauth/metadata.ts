// OAuth 2.0 + MCP discovery endpoints.
//
// Two well-known documents are served:
//
//   /.well-known/oauth-protected-resource    (RFC 9728)
//     Tells the MCP client where the authorization server lives. We act as
//     both resource and authorization server, so it points back at us.
//
//   /.well-known/oauth-authorization-server  (RFC 8414)
//     Tells the MCP client the endpoints, supported grant types, supported
//     PKCE methods, and the dynamic-client-registration endpoint.
//
// Both are unauthenticated GETs and safe to cache for ~1 hour.

function originOf(req: Request): string {
  return new URL(req.url).origin;
}

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, OPTIONS",
  "Access-Control-Allow-Headers": "content-type",
};

function jsonDiscovery(body: unknown) {
  return new Response(JSON.stringify(body, null, 2), {
    status: 200,
    headers: {
      "Content-Type": "application/json",
      "Cache-Control": "public, max-age=3600",
      ...CORS,
    },
  });
}

export function protectedResourceMetadata(req: Request): Response {
  const origin = originOf(req);
  return jsonDiscovery({
    resource: origin,
    authorization_servers: [origin],
    scopes_supported: ["corpus:read"],
    bearer_methods_supported: ["header"],
    resource_documentation: "https://sermonsteward.com/study/connect",
  });
}

export function authorizationServerMetadata(req: Request): Response {
  const origin = originOf(req);
  return jsonDiscovery({
    issuer: origin,
    authorization_endpoint: `${origin}/oauth/authorize`,
    token_endpoint: `${origin}/oauth/token`,
    registration_endpoint: `${origin}/oauth/register`,
    revocation_endpoint: `${origin}/oauth/revoke`,
    response_types_supported: ["code"],
    grant_types_supported: ["authorization_code", "refresh_token"],
    code_challenge_methods_supported: ["S256"],
    token_endpoint_auth_methods_supported: ["none"],
    scopes_supported: ["corpus:read"],
    service_documentation: "https://sermonsteward.com/study/connect",
  });
}

// 401 WWW-Authenticate response for unauthenticated MCP requests. Per
// MCP spec, the WWW-Authenticate header points the client at the
// protected-resource metadata document so it can discover the auth server.
export function unauthenticatedResponse(req: Request): Response {
  const origin = originOf(req);
  const wwwAuth =
    `Bearer resource_metadata="${origin}/.well-known/oauth-protected-resource"`;
  return new Response(
    JSON.stringify({
      error: "unauthorized",
      error_description: "Authentication required",
    }),
    {
      status: 401,
      headers: {
        "Content-Type": "application/json",
        "WWW-Authenticate": wwwAuth,
        ...CORS,
      },
    },
  );
}
