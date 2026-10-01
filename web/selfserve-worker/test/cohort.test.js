import { describe, it, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import worker from "../src/index.js";
import { validateSermonMeta, parseCohorts, resolveCohort, DEFAULT_COHORTS } from "../src/lib.js";

const BASE = "https://try.sermonsteward.com";

function makeEnv(overrides = {}) {
  return {
    SUPABASE_URL: "https://example.supabase.co",
    SUPABASE_SERVICE_KEY: "test-service-key",
    R2_ACCOUNT_ID: "acct",
    R2_ACCESS_KEY_ID: "AKIDEXAMPLE",
    R2_SECRET_ACCESS_KEY: "secret",
    R2_BUCKET: "sermon-steward-audio",
    R2_PUBLIC_BASE: "https://sermons-cdn.sermonsteward.com",
    MAX_UPLOAD_MB: "200",
    RATE_PER_DAY: "3",
    AUDIO_BUCKET: { head: async () => ({ size: 40_000_000 }), delete: async () => {} },
    ...overrides,
  };
}

const post = (path, body) =>
  new Request(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

const goodFields = {
  name: "Pastor Test",
  church: "Grace Church Denver",
  email: "test@example.org",
  title: "Productive Problem Solving",
  date: "2026-09-27",
  filename: "sermon.mp3",
  type: "audio/mpeg",
  size: 40_000_000,
};

let inserts;
let realFetch;
beforeEach(() => {
  inserts = [];
  realFetch = globalThis.fetch;
  globalThis.fetch = async (url, init = {}) => {
    const u = String(url);
    if (u.includes("/rest/v1/self_serve_jobs")) {
      if ((init.method || "GET") === "POST") {
        inserts.push(JSON.parse(init.body));
        return new Response("", { status: 201 });
      }
      return new Response("[]", { status: 200 });
    }
    throw new Error(`unexpected fetch ${u}`);
  };
});
afterEach(() => { globalThis.fetch = realFetch; });

describe("landing pages", () => {
  it("GET / asks for title + date, keeps church optional, no cohort, no prayer", async () => {
    const html = await (await worker.fetch(new Request(`${BASE}/`), makeEnv())).text();
    assert.match(html, /id="title"[^>]*required/);
    assert.match(html, /id="date"[^>]*required/);
    assert.match(html, /id="series"/);
    assert.match(html, /Church <span class="opt">\(optional\)<\/span>/);
    assert.match(html, /id="cohort" name="cohort" value=""/);
    assert.doesNotMatch(html, /pray/i);
    assert.doesNotMatch(html, /Shepherd/i);
    assert.doesNotMatch(html, /__[A-Z_]+__/);
  });

  it("GET /mw serves the regional page with church required and the code set", async () => {
    const res = await worker.fetch(new Request(`${BASE}/mw`), makeEnv());
    assert.equal(res.status, 200);
    const html = await res.text();
    assert.match(html, /Free for Sovereign Grace Midwest pastors/);
    assert.match(html, /id="cohort" name="cohort" value="mw"/);
    assert.match(html, /id="church" name="church" required/);
    assert.doesNotMatch(html, /__[A-Z_]+__/);
    assert.equal((await worker.fetch(new Request(`${BASE}/MW/`), makeEnv())).status, 200);
  });

  it("unknown codes 404; COHORTS var overrides the defaults", async () => {
    assert.equal((await worker.fetch(new Request(`${BASE}/nope`), makeEnv())).status, 404);
    const env = makeEnv({ COHORTS: '{"se":{"id":"sg-southeast","label":"SG Southeast"}}' });
    assert.equal((await worker.fetch(new Request(`${BASE}/se`), env)).status, 200);
    assert.equal((await worker.fetch(new Request(`${BASE}/mw`), env)).status, 404);
  });
});

describe("POST /api/prepare validation", () => {
  it("requires a sermon title and a real preached date", async () => {
    for (const [patch, re] of [
      [{ title: "" }, /title/i],
      [{ date: "" }, /date/i],
      [{ date: "2026-02-30" }, /date/i],
      [{ date: "2999-01-01" }, /future/i],
    ]) {
      const res = await worker.fetch(post("/api/prepare", { ...goodFields, ...patch }), makeEnv());
      assert.equal(res.status, 400);
      assert.match((await res.json()).error, re);
    }
  });

  it("cohort uploads need a church and a known code", async () => {
    let res = await worker.fetch(post("/api/prepare", { ...goodFields, church: "", cohort: "mw" }), makeEnv());
    assert.equal(res.status, 400);
    assert.match((await res.json()).error, /church/i);
    res = await worker.fetch(post("/api/prepare", { ...goodFields, cohort: "bogus" }), makeEnv());
    assert.equal(res.status, 400);
  });
});

describe("prepare → complete stores title, date, series, cohort", () => {
  it("tags a /mw upload with the cohort id sealed in the ticket", async () => {
    const env = makeEnv();
    const prep = await (await worker.fetch(post("/api/prepare", { ...goodFields, cohort: "mw", series: "" }), env)).json();
    assert.equal(prep.ok, true);
    const done = await (await worker.fetch(post("/api/complete", { ticket: prep.ticket }), env)).json();
    assert.equal(done.ok, true);
    assert.equal(inserts.length, 1);
    const row = inserts[0];
    assert.equal(row.cohort, "sg-mountain-west");
    assert.equal(row.sermon_title, "Productive Problem Solving");
    assert.equal(row.sermon_date, "2026-09-27");
    assert.equal(row.series_name, null);
    assert.equal(row.church_name, "Grace Church Denver");
  });

  it("public uploads have no cohort, and a tampered ticket is rejected", async () => {
    const env = makeEnv();
    const prep = await (await worker.fetch(post("/api/prepare", { ...goodFields, series: "1 Samuel" }), env)).json();
    await worker.fetch(post("/api/complete", { ticket: prep.ticket }), env);
    assert.equal(inserts[0].cohort, null);
    assert.equal(inserts[0].series_name, "1 Samuel");
    const [body, sig] = prep.ticket.split(".");
    const forged = Buffer.from(JSON.stringify({ ...JSON.parse(Buffer.from(body, "base64url")), cohort: "sg-mountain-west" }))
      .toString("base64url") + "." + sig;
    const res = await worker.fetch(post("/api/complete", { ticket: forged }), env);
    assert.equal(res.status, 400);
    assert.equal(inserts.length, 1);
  });
});

describe("lib helpers", () => {
  it("validateSermonMeta", () => {
    const today = new Date("2026-09-30T12:00:00Z");
    assert.equal(validateSermonMeta({ title: "A", date: "2026-09-27", today }), null);
    assert.equal(validateSermonMeta({ title: "A", date: "2026-10-01", today }), null); // tz slack
    assert.match(validateSermonMeta({ title: "A", date: "2026-10-05", today }), /future/);
    assert.match(validateSermonMeta({ title: "A", date: "09/27/2026", today }), /date/);
    assert.match(validateSermonMeta({ title: "x".repeat(201), date: "2026-09-27", today }), /shorten/);
  });

  it("parseCohorts / resolveCohort", () => {
    assert.deepEqual(parseCohorts(undefined), DEFAULT_COHORTS);
    assert.deepEqual(parseCohorts("not json"), DEFAULT_COHORTS);
    const c = parseCohorts('{"MW":{"id":"sg-mountain-west"},"bad code!":{"id":"x"}}');
    assert.deepEqual(Object.keys(c), ["mw"]);
    assert.equal(resolveCohort(c, "/mw/").id, "sg-mountain-west");
    assert.equal(resolveCohort(c, "api"), null);
    assert.equal(resolveCohort(c, "../mw"), null);
  });
});
