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
const MAX_SERMONS = 100; // how many to fetch (set higher for more)

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

// ── extract transcript from individual sermon page ──────────────────────────

function extractSermonData(html, slug) {
  // Extract title - look for <h2> after the topics section
  let title = slug.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  const titleMatch = html.match(
    /## ([^\n]+)/
  );
  if (titleMatch) {
    title = titleMatch[1].trim();
  }

  // Extract scripture reference
  let scriptureRef = null;
  const refMatch = html.match(
    /\[([a-z0-9]+ [\d:–\-]+)\]\(\/scripture\//i
  );
  if (refMatch) {
    scriptureRef = refMatch[1];
  }

  // Extract date
  let date = null;
  const dateMatch = html.match(
    /((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4})/
  );
  if (dateMatch) {
    date = dateMatch[1];
  }

  // Extract description - the paragraph after the scripture link
  let description = null;
  const descMatch = html.match(
    /In (?:the gospel|this (?:sermon|message|opening|passage))[\s\S]*?(?=####\s*Transcript)/i
  );
  if (descMatch) {
    description = descMatch[0].trim().substring(0, 500);
  }

 // Extract transcript - everything after Transcript heading in HTML
  let transcript = null;
  const transcriptMatch = html.match(/Transcript<\/h4>\s*<div[^>]*>([\s\S]*?)(?:<\/div>\s*<div class="mt-|<footer|Stay in Touch)/);
  if (transcriptMatch) {
    transcript = transcriptMatch[1]
      .trim()
      // Clean up markdown formatting
      .replace(/^>\s*/gm, "") // Remove blockquote markers
      .replace(/\*\*/g, "") // Remove bold
      .replace(/\*/g, "") // Remove italic
      .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1") // Convert links to text
      .replace(/\n{3,}/g, "\n\n") // Normalize multiple newlines
      .trim();
  }

  return {
    id: slug,
    contributor: "R.C. Sproul",
    contributorSlug: "rc-sproul",
    title,
    description,
    date,
    bibleReferences: scriptureRef
      ? [{ text: scriptureRef }]
      : [],
    transcript,
    sourceUrl: `${BASE_URL}/sermons/${slug}`,
    source: "ligonier.org",
  };
}

// ── main scraper ────────────────────────────────────────────────────────────

async function scrape() {
  console.log("=== Ligonier.org R.C. Sproul Sermon Scraper ===\n");

  fs.mkdirSync(OUT_DIR, { recursive: true });

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

    // Skip if already downloaded
    if (fs.existsSync(filePath)) {
      skipped++;
      continue;
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

    fs.writeFileSync(filePath, JSON.stringify(data, null, 2), "utf8");

    const hasTranscript = !!data.transcript;
    const transcriptLen = data.transcript ? data.transcript.length : 0;

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