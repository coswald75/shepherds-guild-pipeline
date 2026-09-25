/**
 * Ligonier.org R.C. Sproul Sermon Scraper
 * Usage: node ligonier-scraper.js
 *
 * Scrapes sermon transcripts from learn.ligonier.org
 * Output: sermon-transcripts/rc-sproul/{slug}.json
 */

const fs = require("fs");
const path = require("path");

const BASE_URL = "https://learn.ligonier.org";
const OUT_DIR = "./sermon-transcripts/rc-sproul";
const DELAY_MS = 500; // polite delay between requests
const MAX_SERMONS = Number(process.env.MAX_SERMONS || 600); // full corpus is ~545
const NO_TX_DIR = path.join(OUT_DIR, "_no_transcript");

// ── helpers ────────────────────────────────────────────────────────────────

async function fetchPage(url) {
  const res = await fetch(url, {
    headers: {
      "User-Agent":
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
      Accept: "text/html,application/xhtml+xml",
    },
  });
  if (!res.ok) throw new Error(`HTTP ${res.status} for ${url}`);
  return res.text();
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

function sanitize(str) {
  return str.replace(/[\\/:*?"<>|]/g, "_").substring(0, 80);
}

// ── extract sermon slugs from the listing page ─────────────────────────────

function extractSermonSlugs(html) {
  // Match all href="/sermons/slug-here" patterns
  const slugs = [];
  const regex = /href="\/sermons\/([a-z0-9-]+)"/g;
  let match;
  while ((match = regex.exec(html)) !== null) {
    const slug = match[1];
    // Skip non-sermon slugs
    if (slug && !slugs.includes(slug)) {
      slugs.push(slug);
    }
  }
  return slugs;
}

// ── JSON field helpers ──────────────────────────────────────────────────────
// Sermon pages embed a JS data blob with clean, machine-readable fields.
// Prefer it over scraping rendered markup: the visible page also carries promo
// and event dates, which the old date regex picked up instead of the sermon's.
//
// The blob also embeds the previous and next sermons, plus topic objects that
// can share a sermon's slug, so a first-match lookup can silently return a
// neighbour's title or scripture. Every field is therefore read as the first
// occurrence after this page's single `"currentSermon":` marker.

const SERMON_ANCHOR = '"currentSermon":';

function readStringAt(html, valueStart) {
  let i = valueStart;
  while (i < html.length && /\s/.test(html[i])) i++;
  if (html.startsWith("null", i)) return null;
  if (html[i] !== '"') return null;
  const start = i;
  i++;
  while (i < html.length) {
    if (html[i] === "\\") { i += 2; continue; }
    if (html[i] === '"') break;
    i++;
  }
  try {
    return JSON.parse(html.slice(start, i + 1));
  } catch {
    return null;
  }
}

function sermonField(html, key, anchor) {
  const needle = `"${key}":`;
  const at = html.indexOf(needle, anchor);
  if (at === -1) return null;
  return readStringAt(html, at + needle.length);
}

function extractScriptureRef(html, anchor) {
  const at = html.indexOf('"primaryScriptureReference":', anchor);
  if (at === -1) return null;
  const window = html.slice(at, at + 600);
  const m = window.match(
    /"primaryScriptureReference":\{"end":\{"book":"[^"]*","verse":(\d+),"chapter":(\d+)\},"start":\{"book":"([^"]*)","verse":(\d+),"chapter":(\d+)\}\}/
  );
  if (!m) return null;
  const [, endVerse, endChapter, startBook, startVerse, startChapter] = m;
  const nameMatch = window.match(/"primaryScriptureReferenceStartBook":\{"book":"([^"]+)"\}/);
  const name =
    (nameMatch && nameMatch[1]) ||
    startBook.charAt(0).toUpperCase() + startBook.slice(1);
  if (startChapter === endChapter) {
    return startVerse === endVerse
      ? `${name} ${startChapter}:${startVerse}`
      : `${name} ${startChapter}:${startVerse}–${endVerse}`;
  }
  return `${name} ${startChapter}:${startVerse}–${endChapter}:${endVerse}`;
}

// ── extract transcript from individual sermon page ──────────────────────────

function extractSermonData(html, slug) {
  const anchor = html.indexOf(SERMON_ANCHOR);
  if (anchor === -1) {
    throw new Error(`no currentSermon block for ${slug}`);
  }

  // datePreached is an ISO timestamp, e.g. "2013-06-09T00:01:00.000Z".
  // Keep only the calendar date; emit null rather than a plausible-looking
  // wrong value when it is absent.
  const rawDate = sermonField(html, "datePreached", anchor);
  const date = rawDate && /^\d{4}-\d{2}-\d{2}/.test(rawDate) ? rawDate.slice(0, 10) : null;

  const title = sermonField(html, "sermonTitle", anchor);
  const transcript = sermonField(html, "sermonTranscript", anchor);
  const description = sermonField(html, "sermonSynopsis", anchor);
  const scriptureRef = extractScriptureRef(html, anchor);
  const audioUrl = sermonField(html, "externalAudioUrl", anchor);

  return {
    id: slug,
    contributor: "R.C. Sproul",
    contributorSlug: "rc-sproul",
    title: title || slug.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
    titleResolved: !!title,
    description,
    date,
    datePreached: rawDate || null,
    bibleReferences: scriptureRef ? [{ text: scriptureRef }] : [],
    transcript,
    audioUrl,
    sourceUrl: `${BASE_URL}/sermons/${slug}`,
    source: "ligonier.org",
    schemaVersion: 2,
  };
}

// ── main scraper ────────────────────────────────────────────────────────────

async function scrape() {
  console.log("=== Ligonier.org R.C. Sproul Sermon Scraper ===\n");

  fs.mkdirSync(OUT_DIR, { recursive: true });
  fs.mkdirSync(NO_TX_DIR, { recursive: true });

  // Step 1: Get sermon listing pages to collect slugs
  console.log("▶ Fetching sermon index...");
  let allSlugs = [];

  // The listing page shows sermons sorted by scripture
  // We need to paginate through it
  // First page
  try {
    const html = await fetchPage(`${BASE_URL}/sermons`);
    const slugs = extractSermonSlugs(html);
    allSlugs.push(...slugs);
    console.log(`  ✓ Page 1: found ${slugs.length} sermon links`);
  } catch (e) {
    console.error(`  ✗ Failed to fetch sermon index: ${e.message}`);
    return;
  }

  // Try additional pages if the site supports pagination
  for (let page = 2; page <= 25; page++) {
    await sleep(DELAY_MS);
    try {
      const html = await fetchPage(`${BASE_URL}/sermons?page=${page}`);
      const slugs = extractSermonSlugs(html);
      const newSlugs = slugs.filter((s) => !allSlugs.includes(s));
      if (newSlugs.length === 0) {
        console.log(`  ℹ Page ${page}: no new sermons, stopping pagination`);
        break;
      }
      allSlugs.push(...newSlugs);
      console.log(`  ✓ Page ${page}: found ${newSlugs.length} new sermon links (total: ${allSlugs.length})`);
    } catch (e) {
      console.log(`  ℹ Page ${page}: ${e.message}, stopping pagination`);
      break;
    }
  }

  console.log(`\n  Total unique sermon slugs: ${allSlugs.length}`);

  // Cap at MAX_SERMONS
  const slugsToFetch = allSlugs.slice(0, MAX_SERMONS);
  console.log(`  Fetching up to ${slugsToFetch.length} sermons\n`);

  // Step 2: Fetch each sermon's transcript
  let fetched = 0;
  let skipped = 0;
  let noTranscript = 0;

  for (const slug of slugsToFetch) {
    const filePath = path.join(OUT_DIR, `${slug}.json`);

    // Skip only if already downloaded AND written by the current extractor.
    // v1 records carry a page-render date rather than the sermon's own date,
    // so they must be re-fetched.
    const altPath = path.join(NO_TX_DIR, `${slug}.json`);
    const existing = fs.existsSync(filePath)
      ? filePath
      : fs.existsSync(altPath)
        ? altPath
        : null;
    if (existing) {
      let fresh = false;
      try {
        fresh = JSON.parse(fs.readFileSync(existing, "utf8")).schemaVersion >= 2;
      } catch {}
      if (fresh) {
        skipped++;
        continue;
      }
      fs.unlinkSync(existing);
    }

    await sleep(DELAY_MS);

    let html;
    try {
      html = await fetchPage(`${BASE_URL}/sermons/${slug}`);
    } catch (e) {
      console.error(`  ✗ Failed to fetch ${slug}: ${e.message}`);
      continue;
    }

    const data = extractSermonData(html, slug);

    const hasTranscript = !!data.transcript;
    const transcriptLen = data.transcript ? data.transcript.length : 0;

    // Sermons Ligonier has not transcribed still carry a real date and audio
    // URL, so keep the record — just outside the folder the batch reads.
    const dest = hasTranscript ? filePath : path.join(NO_TX_DIR, `${slug}.json`);
    fs.writeFileSync(dest, JSON.stringify(data, null, 2), "utf8");

    if (!hasTranscript) noTranscript++;

    console.log(
      `  [${String(fetched + skipped + 1).padStart(3, "0")}] ${sanitize(data.title)} — ${hasTranscript ? `${transcriptLen} chars` : "NO TRANSCRIPT"}`
    );
    fetched++;
  }

  // Write index
  const indexPath = path.join(OUT_DIR, "_index.json");
  const index = {
    slug: "rc-sproul",
    fullName: "R.C. Sproul",
    source: "ligonier.org",
    totalFound: allSlugs.length,
    fetched: fetched + skipped,
    withTranscript: fetched + skipped - noTranscript,
    noTranscript,
    scrapedAt: new Date().toISOString(),
    allSlugs: allSlugs,
  };
  fs.writeFileSync(indexPath, JSON.stringify(index, null, 2), "utf8");

  console.log(`\n  ✓ Done — ${fetched} new, ${skipped} cached, ${noTranscript} without transcript`);
  console.log(`  Index written to ${indexPath}`);
}

scrape().catch((e) => {
  console.error("Fatal:", e);
  process.exit(1);
});