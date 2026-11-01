// SigV4 query-string presigning for R2's S3 API (same algorithm as
// web/selfserve-worker/src/lib.js). Keys stay in Worker secrets; only the
// short-lived signed URL is sent to the browser.
const encoder = new TextEncoder();

function hex(bytes) {
  return [...new Uint8Array(bytes)].map((b) => b.toString(16).padStart(2, "0")).join("");
}
async function hmacSha256(key, data) {
  const raw = typeof key === "string" ? encoder.encode(key) : key;
  const k = await crypto.subtle.importKey("raw", raw, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return new Uint8Array(await crypto.subtle.sign("HMAC", k, encoder.encode(data)));
}
async function sha256Hex(text) {
  return hex(await crypto.subtle.digest("SHA-256", encoder.encode(text)));
}
function uriEncode(str, encodeSlash) {
  return encodeURIComponent(str)
    .replace(/[!'()*]/g, (c) => `%${c.charCodeAt(0).toString(16).toUpperCase()}`)
    .replace(/%2F/g, encodeSlash ? "%2F" : "/");
}

/** Presigned UploadPart URL for an existing multipart upload. */
export async function presignR2UploadPart({
  accountId, accessKeyId, secretAccessKey, bucket, key, uploadId, partNumber,
  expiresSec = 3600, amzDate,
}) {
  const host = `${accountId}.r2.cloudflarestorage.com`;
  const canonicalUri = `/${uriEncode(bucket, false)}/${uriEncode(key, false)}`;
  const dateTime = amzDate || new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d+Z$/, "Z");
  const dateStamp = dateTime.slice(0, 8);
  const scope = `${dateStamp}/auto/s3/aws4_request`;
  const query = {
    "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
    "X-Amz-Credential": `${accessKeyId}/${scope}`,
    "X-Amz-Date": dateTime,
    "X-Amz-Expires": String(expiresSec),
    "X-Amz-SignedHeaders": "host",
    partNumber: String(partNumber),
    uploadId,
  };
  const canonicalQuery = Object.keys(query).sort()
    .map((k) => `${uriEncode(k, true)}=${uriEncode(String(query[k]), true)}`).join("&");
  const canonicalRequest = ["PUT", canonicalUri, canonicalQuery, `host:${host}\n`, "host", "UNSIGNED-PAYLOAD"].join("\n");
  const stringToSign = ["AWS4-HMAC-SHA256", dateTime, scope, await sha256Hex(canonicalRequest)].join("\n");
  const kDate = await hmacSha256(`AWS4${secretAccessKey}`, dateStamp);
  const kSigning = await hmacSha256(await hmacSha256(await hmacSha256(kDate, "auto"), "s3"), "aws4_request");
  const signature = hex(await hmacSha256(kSigning, stringToSign));
  return `https://${host}${canonicalUri}?${canonicalQuery}&X-Amz-Signature=${signature}`;
}
