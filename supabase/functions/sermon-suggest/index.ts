// "Suggest a change" capture for sermon pages. Isolated from chat / record-feedback.
// POST JSON: { sermon_slug, item_location, item_label?, current_text, suggested_text,
//              name?, email?, page_path?, website?(honeypot), elapsed_ms? } -> { ok: true }
// Public (verify_jwt false), CORS limited to sermonsteward.com + preview workers, writes to
// public.sermon_suggestions via service role. NEVER edits a page; Chris reviews the queue.
// Abuse controls: honeypot field, minimum time on form, length caps, URL-count cap,
// per-IP limits (5 / 10 min, 20 / day; IP stored only as a salted SHA-256), global 300 / day.
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const ALLOWED = [/^https:\/\/sermonsteward\.com$/, /^https:\/\/www\.sermonsteward\.com$/, /^https:\/\/[a-z0-9-]+\.chris-386\.workers\.dev$/, /^http:\/\/localhost(:\d+)?$/];
function cors(origin: string | null) {
  const ok = origin && ALLOWED.some((r) => r.test(origin));
  return {
    "Access-Control-Allow-Origin": ok ? origin! : "https://sermonsteward.com",
    "Access-Control-Allow-Headers": "content-type",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Content-Type": "application/json",
    "Vary": "Origin",
  };
}
const s = (v: unknown, n: number) => (v == null ? "" : String(v)).trim().slice(0, n);

async function sha(text: string) {
  const b = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(b)).map((x) => x.toString(16).padStart(2, "0")).join("");
}

Deno.serve(async (req) => {
  const H = cors(req.headers.get("origin"));
  const json = (d: unknown, status = 200) => new Response(JSON.stringify(d), { status, headers: H });
  if (req.method === "OPTIONS") return new Response("ok", { headers: H });
  if (req.method !== "POST") return json({ error: "POST only" }, 405);
  let b: any;
  try { b = await req.json(); } catch { return json({ error: "Invalid JSON" }, 400); }

  // Bots: honeypot filled or form submitted implausibly fast -> pretend success, store nothing.
  if (s(b?.website, 200) || Number(b?.elapsed_ms ?? 99999) < 2500) return json({ ok: true });

  const row = {
    sermon_slug: s(b?.sermon_slug, 200),
    item_location: s(b?.item_location, 200),
    item_label: s(b?.item_label, 200) || null,
    current_text: s(b?.current_text, 4000),
    suggested_text: s(b?.suggested_text, 4000),
    submitter_name: s(b?.name, 120) || null,
    submitter_email: s(b?.email, 200) || null,
    page_path: s(b?.page_path, 300) || null,
    user_agent: s(req.headers.get("user-agent"), 300) || null,
  };
  if (!row.sermon_slug || !row.item_location || !row.current_text) return json({ error: "missing fields" }, 400);
  if (row.suggested_text.length < 2) return json({ error: "Please write what you'd like it to say." }, 400);
  if (row.suggested_text === row.current_text) return json({ error: "That's the same as the current wording." }, 400);
  if ((row.suggested_text.match(/https?:\/\//g) || []).length > 2) return json({ error: "Too many links." }, 400);
  if (row.submitter_email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(row.submitter_email)) return json({ error: "That email doesn't look right." }, 400);

  const admin = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!);
  const ip = (req.headers.get("cf-connecting-ip") || req.headers.get("x-forwarded-for") || "").split(",")[0].trim();
  const ip_hash = ip ? await sha("sermon-suggest:" + ip + ":" + (Deno.env.get("SUPABASE_URL") || "")) : null;
  const since = (ms: number) => new Date(Date.now() - ms).toISOString();
  try {
    if (ip_hash) {
      const { count: c10 } = await admin.from("sermon_suggestions").select("id", { count: "exact", head: true }).eq("ip_hash", ip_hash).gte("created_at", since(10 * 60e3));
      const { count: cDay } = await admin.from("sermon_suggestions").select("id", { count: "exact", head: true }).eq("ip_hash", ip_hash).gte("created_at", since(24 * 3600e3));
      if ((c10 ?? 0) >= 5 || (cDay ?? 0) >= 20) return json({ error: "Thanks! You've sent a lot of suggestions; please try again later." }, 429);
    }
    const { count: all } = await admin.from("sermon_suggestions").select("id", { count: "exact", head: true }).gte("created_at", since(24 * 3600e3));
    if ((all ?? 0) >= 300) return json({ error: "Suggestions are paused for today. Please email us instead." }, 429);
    const { data: sermon } = await admin.from("sermons").select("id").eq("slug", row.sermon_slug).limit(1).maybeSingle();
    if (!sermon) return json({ error: "unknown sermon" }, 400);
    const { error } = await admin.from("sermon_suggestions").insert({ ...row, sermon_id: sermon.id, ip_hash });
    if (error) { console.error("suggest insert error", error); return json({ error: "could not save" }, 500); }
  } catch (e) {
    console.error("suggest error", e); return json({ error: "could not save" }, 500);
  }
  return json({ ok: true });
});
