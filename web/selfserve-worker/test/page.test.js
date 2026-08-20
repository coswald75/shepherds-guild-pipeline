import { describe, it } from "node:test";
import assert from "node:assert/strict";
import worker from "../src/index.js";

const OG_IMAGE = "https://sermonsteward.com/og-sermon-steward.png";
const PAGE_URL = "https://try.sermonsteward.com";

function metaContent(html, attr, name) {
  const re = new RegExp(`${attr}="${name}" content="([^"]*)"`);
  const m = html.match(re);
  assert.ok(m, `missing ${attr}="${name}"`);
  return m[1];
}

describe("GET / social cards", () => {
  it("emits Open Graph and Twitter tags for try.sermonsteward.com", async () => {
    const res = await worker.fetch(new Request(`${PAGE_URL}/`), {});
    assert.equal(res.status, 200);
    assert.match(res.headers.get("Content-Type") || "", /text\/html/);
    const html = await res.text();

    assert.equal(metaContent(html, "property", "og:type"), "website");
    assert.equal(metaContent(html, "property", "og:url"), PAGE_URL);
    assert.equal(metaContent(html, "property", "og:image"), OG_IMAGE);
    assert.equal(metaContent(html, "property", "og:image:width"), "1200");
    assert.equal(metaContent(html, "property", "og:image:height"), "630");
    assert.match(metaContent(html, "property", "og:image:alt"), /Sermon Steward/);

    const ogTitle = metaContent(html, "property", "og:title");
    const ogDesc = metaContent(html, "property", "og:description");
    assert.match(ogTitle, /Sermon Steward/);
    assert.match(ogTitle, /upload one sermon, get a report/i);
    assert.match(ogDesc, /free one-sermon try/i);
    assert.match(ogDesc, /15 minutes/);
    assert.match(ogDesc, /never publish without your permission/i);

    assert.equal(metaContent(html, "name", "twitter:card"), "summary_large_image");
    assert.equal(metaContent(html, "name", "twitter:title"), ogTitle);
    assert.equal(metaContent(html, "name", "twitter:description"), ogDesc);
    assert.equal(metaContent(html, "name", "twitter:image"), OG_IMAGE);

    assert.doesNotMatch(html, /Guild Hall/);
    assert.doesNotMatch(html, /start this week/i);
    assert.doesNotMatch(html, /voice[- ]on[- ]day[- ]one/i);
    assert.doesNotMatch(html, /paid checkout/i);
  });
});
