/**
 * Shared helpers for the try. self-serve Worker.
 *
 * Presigned R2 PUT uses SigV4 query-string auth (same algorithm as aws4fetch /
 * the official Cloudflare R2 example). Tickets bind a job id to the pastor's
 * form fields so /api/complete cannot invent a key the Worker did not issue.
 */

const encoder = new TextEncoder();

export const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
export const JOB_ID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export const PRESIGN_EXPIRES_SEC = 3600;

export function maxUploadBytes(maxMb) {
  const mb = parseInt(maxMb || "200", 10);
  return (Number.isFinite(mb) && mb > 0 ? mb : 200) * 1_000_000;
}

export function looksLikeAudio(filename, type) {
  const t = (type || "").toString();
  const name = (filename || "").toString();
  return t.startsWith("audio/") || /\.mp3$/i.test(name);
}

export function validateFields({ name, email, filename, type, size, maxBytes }) {
  if (!name) return "Please enter your name.";
  if (!EMAIL_RE.test(email)) return "Please enter a valid email.";
  if (!filename) return "Please attach an MP3.";
  if (!looksLikeAudio(filename, type)) {
    return "That doesn't look like an audio file. Please upload an MP3.";
  }
  const n = Number(size);
  if (!Number.isFinite(n) || n <= 0) return "Please attach an MP3.";
  if (n > maxBytes) {
    const mb = Math.round(maxBytes / 1_000_000);
    return `That file is too large. Please use an MP3 of ${mb} MB or less.`;
  }
  return null;
}

export function selfServeKey(jobId) {
  return `self-serve/${jobId}.mp3`;
}

export function hex(bytes) {
  return [...bytes].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export function b64urlEncode(bytes) {
  let bin = "";
  const arr = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  for (let i = 0; i < arr.length; i++) bin += String.fromCharCode(arr[i]);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

export function b64urlDecode(str) {
  const pad = str.length % 4 === 0 ? "" : "=".repeat(4 - (str.length % 4));
  const b64 = str.replace(/-/g, "+").replace(/_/g, "/") + pad;
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

async function hmacSha256(key, data) {
  const rawKey = typeof key === "string" ? encoder.encode(key) : key;
  const cryptoKey = await crypto.subtle.importKey(
    "raw",
    rawKey,
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const payload = typeof data === "string" ? encoder.encode(data) : data;
  return new Uint8Array(await crypto.subtle.sign("HMAC", cryptoKey, payload));
}

export async function sha256Hex(text) {
  const digest = await crypto.subtle.digest("SHA-256", encoder.encode(text));
  return hex(new Uint8Array(digest));
}

function uriEncode(str, encodeSlash) {
  return encodeURIComponent(str).replace(/[!'()*]/g, (c) =>
    `%${c.charCodeAt(0).toString(16).toUpperCase()}`
  ).replace(/%2F/g, encodeSlash ? "%2F" : "/");
}

/**
 * Generic S3-compatible query-string presign (SigV4).
 * `canonicalUri` must already include the leading slash (path-style or virtual-host).
 */
export async function presignS3({
  accessKeyId,
  secretAccessKey,
  region = "auto",
  method = "PUT",
  host,
  canonicalUri,
  expiresSec = PRESIGN_EXPIRES_SEC,
  amzDate,
  extraQuery = {},
}) {
  const dateTime = amzDate || new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d+Z$/, "Z");
  const dateStamp = dateTime.slice(0, 8);
  const credential = `${accessKeyId}/${dateStamp}/${region}/s3/aws4_request`;

  const query = {
    "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
    "X-Amz-Credential": credential,
    "X-Amz-Date": dateTime,
    "X-Amz-Expires": String(expiresSec),
    "X-Amz-SignedHeaders": "host",
    ...extraQuery,
  };
  const canonicalQuery = Object.keys(query)
    .sort()
    .map((k) => `${uriEncode(k, true)}=${uriEncode(String(query[k]), true)}`)
    .join("&");

  const canonicalHeaders = `host:${host}\n`;
  const canonicalRequest = [
    method,
    canonicalUri,
    canonicalQuery,
    canonicalHeaders,
    "host",
    "UNSIGNED-PAYLOAD",
  ].join("\n");

  const stringToSign = [
    "AWS4-HMAC-SHA256",
    dateTime,
    `${dateStamp}/${region}/s3/aws4_request`,
    await sha256Hex(canonicalRequest),
  ].join("\n");

  const kDate = await hmacSha256(`AWS4${secretAccessKey}`, dateStamp);
  const kRegion = await hmacSha256(kDate, region);
  const kService = await hmacSha256(kRegion, "s3");
  const kSigning = await hmacSha256(kService, "aws4_request");
  const signature = hex(await hmacSha256(kSigning, stringToSign));

  return `https://${host}${canonicalUri}?${canonicalQuery}&X-Amz-Signature=${signature}`;
}

export async function presignR2Put({
  accountId,
  accessKeyId,
  secretAccessKey,
  bucket,
  key,
  expiresSec = PRESIGN_EXPIRES_SEC,
}) {
  const host = `${accountId}.r2.cloudflarestorage.com`;
  const canonicalUri = `/${uriEncode(bucket, false)}/${uriEncode(key, false)}`;
  return presignS3({
    accessKeyId,
    secretAccessKey,
    region: "auto",
    method: "PUT",
    host,
    canonicalUri,
    expiresSec,
  });
}

export async function signTicket(secret, payload) {
  const body = b64urlEncode(encoder.encode(JSON.stringify(payload)));
  const sig = b64urlEncode(await hmacSha256(secret, body));
  return `${body}.${sig}`;
}

export async function verifyTicket(secret, ticket) {
  if (!ticket || typeof ticket !== "string") return null;
  const dot = ticket.lastIndexOf(".");
  if (dot <= 0) return null;
  const body = ticket.slice(0, dot);
  const sig = ticket.slice(dot + 1);
  const expected = b64urlEncode(await hmacSha256(secret, body));
  if (sig.length !== expected.length) return null;
  let diff = 0;
  for (let i = 0; i < sig.length; i++) diff |= sig.charCodeAt(i) ^ expected.charCodeAt(i);
  if (diff !== 0) return null;
  try {
    const payload = JSON.parse(new TextDecoder().decode(b64urlDecode(body)));
    if (!payload || payload.v !== 1) return null;
    if (!JOB_ID_RE.test(payload.id || "")) return null;
    if (payload.key !== selfServeKey(payload.id)) return null;
    if (!payload.exp || Date.now() > payload.exp) return null;
    return payload;
  } catch {
    return null;
  }
}

// ── Sermon metadata (title / date / optional series) ─────────────────────────

export const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
export const MAX_TITLE_LEN = 200;

/** Validate the pastor-supplied sermon title + preached date (YYYY-MM-DD).
 *  `today` is injectable for tests. Returns an error string or null. */
export function validateSermonMeta({ title, date, series, today = new Date() }) {
  const t = (title || "").toString().trim();
  if (!t) return "Please enter the sermon title.";
  if (t.length > MAX_TITLE_LEN) return "Please shorten the sermon title.";
  const d = (date || "").toString().trim();
  if (!DATE_RE.test(d)) return "Please enter the date the sermon was preached.";
  const parsed = new Date(`${d}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== d) {
    return "Please enter the date the sermon was preached.";
  }
  // Allow a day of slack for time zones; reject far-future and implausible dates.
  const limit = new Date(today.getTime() + 36 * 3600 * 1000);
  if (parsed > limit) return "The sermon date can't be in the future.";
  if (parsed.getUTCFullYear() < 1900) return "Please check the sermon date.";
  if ((series || "").toString().trim().length > MAX_TITLE_LEN) return "Please shorten the series name.";
  return null;
}

// ── Regional cohorts (/<code> upload links) ─────────────────────────────────

/** Default cohort map; override with the COHORTS var (JSON) in wrangler.toml.
 *  code (URL path) → { id (stored on self_serve_jobs.cohort), label (shown on the page) } */
export const DEFAULT_COHORTS = {
  mw: { id: "sg-mountain-west", label: "Sovereign Grace Midwest" },
};

export const COHORT_CODE_RE = /^[a-z0-9][a-z0-9-]{0,31}$/;

export function parseCohorts(raw) {
  if (!raw) return DEFAULT_COHORTS;
  try {
    const obj = typeof raw === "string" ? JSON.parse(raw) : raw;
    const out = {};
    for (const [code, v] of Object.entries(obj || {})) {
      const c = code.toLowerCase();
      if (!COHORT_CODE_RE.test(c) || !v || !v.id) continue;
      out[c] = { id: String(v.id), label: String(v.label || v.id) };
    }
    return out;
  } catch {
    return DEFAULT_COHORTS;
  }
}

/** Resolve a cohort code (from the URL path or the form) → cohort or null. */
export function resolveCohort(cohorts, code) {
  const c = (code || "").toString().trim().toLowerCase().replace(/^\/+|\/+$/g, "");
  if (!c || !COHORT_CODE_RE.test(c)) return null;
  return Object.prototype.hasOwnProperty.call(cohorts, c) ? { code: c, ...cohorts[c] } : null;
}
