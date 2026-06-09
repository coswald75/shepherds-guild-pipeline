#!/usr/bin/env tsx
/**
 * Issue an MCP bearer token for a pastor.
 *
 * Usage:
 *   tsx scripts/issue-token.ts --preacher "Chris Oswald" --label "Chris's laptop"
 *   tsx scripts/issue-token.ts --preacher-id <uuid> --label "iPad"
 *
 * The raw token is printed once and never stored — copy it into your
 * MCP client config immediately. Only the SHA-256 hash goes to the DB.
 *
 * Requires env:
 *   SUPABASE_URL                 (or default below)
 *   SUPABASE_SERVICE_ROLE_KEY    (from Supabase dashboard → API)
 */

import { createClient } from "@supabase/supabase-js";
import { createHash, randomBytes } from "node:crypto";
import { parseArgs } from "node:util";

const SUPABASE_URL =
  process.env.SUPABASE_URL ??
  "https://twbunmbzyqcqzgffdrib.supabase.co";

const SERVICE_ROLE_KEY = process.env.SUPABASE_SERVICE_ROLE_KEY;
if (!SERVICE_ROLE_KEY) {
  console.error(
    "Missing SUPABASE_SERVICE_ROLE_KEY. Export it from your shell, e.g.\n" +
      "  export SUPABASE_SERVICE_ROLE_KEY=eyJ...\n" +
      "(Grab it from Supabase dashboard → Project Settings → API → service_role)",
  );
  process.exit(1);
}

const { values } = parseArgs({
  options: {
    preacher: { type: "string" },
    "preacher-id": { type: "string" },
    label: { type: "string" },
  },
});

const label = values.label ?? "default";
if (!values.preacher && !values["preacher-id"]) {
  console.error(
    "Specify --preacher \"<name>\" OR --preacher-id <uuid>. " +
      "Optionally --label \"<short description>\" (default: \"default\").",
  );
  process.exit(1);
}

const supabase = createClient(SUPABASE_URL, SERVICE_ROLE_KEY, {
  auth: { persistSession: false, autoRefreshToken: false },
});

async function main() {
  // Resolve preacher
  let preacherId: string;
  let preacherName: string;
  if (values["preacher-id"]) {
    const { data, error } = await supabase
      .from("preachers")
      .select("id, name")
      .eq("id", values["preacher-id"])
      .maybeSingle();
    if (error || !data) {
      throw new Error(
        `Preacher with id ${values["preacher-id"]} not found: ${error?.message ?? "no match"}`,
      );
    }
    preacherId = data.id;
    preacherName = data.name;
  } else {
    const { data, error } = await supabase
      .from("preachers")
      .select("id, name")
      .ilike("name", values.preacher!)
      .limit(2);
    if (error) throw new Error(`Preacher lookup failed: ${error.message}`);
    if (!data || data.length === 0) {
      throw new Error(`No preacher matching "${values.preacher}"`);
    }
    if (data.length > 1) {
      throw new Error(
        `Multiple preachers match "${values.preacher}". Use --preacher-id instead.`,
      );
    }
    preacherId = data[0].id;
    preacherName = data[0].name;
  }

  // Generate a 32-byte random token, base64url-encoded, with the
  // `sst_` prefix so it's recognizable at a glance and our server can
  // fail fast on obviously-wrong values without a DB hit.
  const raw =
    "sst_" +
    randomBytes(32)
      .toString("base64")
      .replace(/\+/g, "-")
      .replace(/\//g, "_")
      .replace(/=+$/, "");

  const tokenHash = createHash("sha256").update(raw).digest("hex");

  const { error: insertErr } = await supabase.from("mcp_tokens").insert({
    token_hash: tokenHash,
    preacher_id: preacherId,
    name: label,
  });
  if (insertErr) throw new Error(`Insert failed: ${insertErr.message}`);

  console.log("");
  console.log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");
  console.log(`  Token issued for: ${preacherName}`);
  console.log(`  Label:            ${label}`);
  console.log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");
  console.log("");
  console.log("  Copy this token now — it is shown ONCE and not stored:");
  console.log("");
  console.log(`    ${raw}`);
  console.log("");
  console.log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");
  console.log("");
  console.log("  To revoke later:");
  console.log("");
  console.log(`    UPDATE mcp_tokens SET revoked_at = now()`);
  console.log(`      WHERE preacher_id = '${preacherId}'`);
  console.log(`        AND name = '${label.replace(/'/g, "''")}';`);
  console.log("");
}

main().catch((err) => {
  console.error("ERROR:", err.message);
  process.exit(1);
});
