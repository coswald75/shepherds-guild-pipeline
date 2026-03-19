/**
 * SermonIndex Transcript Scraper v2
 * Usage: node sermon-scraper.js
 *
 * Pulls transcripts from api.sermonindex.net with pagination support.
 * Fetches up to MAX_TOTAL per contributor across multiple pages.
 * Skips already-downloaded sermons (safe to re-run).
 * Output: sermon-transcripts/{slug}/{sermon-id}.json
 */

const fs = require("fs");
const path = require("path");

const BASE_URL = "https://api.sermonindex.net/v1";
const PAGE_SIZE = 25; // API hard cap per page
const MAX_TOTAL = 100; // Max sermons to fetch per contributor (set high, filter later)
const OUT_DIR = "./sermon-transcripts";
const DELAY_MS = 300; // polite delay between requests

const CONTRIBUTORS = [
  "john-piper",
  "cj-mahaney",
  "tim-keller",
  "john-macarthur",
  "da-carson",
  "rc-sproul",
  "martyn-lloyd-jones",
  "john-stott",
  "david-jeremiah",
];

// ── helpers ────────────────────────────────────────────────────────────────

async function get(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status} for ${url}`);
  return res.json();
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

function sanitize(str) {
  return str.replace(/[\\/:*?"<>|]/g, "_").substring(0, 80);
}

// ── core ───────────────────────────────────────────────────────────────────

async function scrapeContributor(slug) {
  console.log(`\n▶ ${slug}`);

  // 1. Resolve contributor
  let contributor;
  try {
    contributor = await get(`${BASE_URL}/contributors/slug/${slug}`);
  } catch (e) {
    console.error(`  ✗ Could not find contributor: ${e.message}`);
    return;
  }
  const totalAvailable = contributor.sermonCount || 0;
  const toFetch = Math.min(totalAvailable, MAX_TOTAL);
  console.log(`  ✓ ${contributor.fullName} (${totalAvailable} total sermons, fetching up to ${toFetch})`);

  // 2. Fetch sermon lists with pagination
  let allSermons = [];
  let offset = 0;
  let page = 1;

  while (allSermons.length < toFetch) {
    const remaining = toFetch - allSermons.length;
    const limit = Math.min(PAGE_SIZE, remaining);

    // Try offset parameter — if the API doesn't support it, we'll only get page 1
    const listUrl = `${BASE_URL}/sermons?contributorId=${contributor.id}&limit=${limit}&offset=${offset}`;
    let sermonList;
    try {
      sermonList = await get(listUrl);
    } catch (e) {
      console.error(`  ✗ Could not fetch sermon list page ${page}: ${e.message}`);
      break;
    }

    const sermons = sermonList.values || [];
    if (sermons.length === 0) {
      console.log(`  ℹ No more sermons at offset ${offset}`);
      break;
    }

    allSermons.push(...sermons);
    console.log(`  ✓ Page ${page}: got ${sermons.length} sermons (total so far: ${allSermons.length})`);

    // If we got fewer than requested, we've hit the end
    if (sermons.length < limit) break;

    offset += sermons.length;
    page++;
    await sleep(DELAY_MS);
  }

  console.log(`  ✓ ${allSermons.length} sermons to process`);

  // 3. Output directory
  const outDir = path.join(OUT_DIR, slug);
  fs.mkdirSync(outDir, { recursive: true });

  // 4. Fetch each sermon's full detail (includes transcript)
  let fetched = 0;
  let skipped = 0;
  let noTranscript = 0;

  for (const s of allSermons) {
    const filePath = path.join(outDir, `${s.id}.json`);

    // Skip if already downloaded
    if (fs.existsSync(filePath)) {
      skipped++;
      continue;
    }

    await sleep(DELAY_MS);

    let detail;
    try {
      detail = await get(`${BASE_URL}/sermons/id/${s.id}`);
    } catch (e) {
      console.error(`  ✗ Failed to fetch sermon ${s.id}: ${e.message}`);
      continue;
    }

    const record = {
      id: detail.id,
      contributor: detail.contributorFullName,
      contributorSlug: detail.contributorSlug,
      title: detail.title,
      description: detail.description,
      mediaType: detail.mediaType,
      duration: detail.duration,
      bibleReferences: detail.bibleReferences,
      topics: detail.topics,
      views: detail.views,
      createdAt: detail.createdAt,
      transcript: detail.transcript || null,
      audioUrl: detail.audio?.streamUrl || null,
      videoUrl: detail.video?.streamUrl || null,
      srtUrl: detail.video?.srtUrl || detail.audio?.srtUrl || null,
      vttUrl: detail.video?.vttUrl || detail.audio?.vttUrl || null,
    };

    fs.writeFileSync(filePath, JSON.stringify(record, null, 2), "utf8");

    const hasTranscript = !!record.transcript;
    const transcriptLen = record.transcript ? record.transcript.length : 0;

    if (!hasTranscript) {
      noTranscript++;
    }

    console.log(
      `  [${String(fetched + skipped + 1).padStart(3, "0")}] ${sanitize(detail.title)} — ${hasTranscript ? `${transcriptLen} chars` : "NO TRANSCRIPT"}`
    );
    fetched++;
  }

  // 5. Write contributor index
  const indexPath = path.join(outDir, "_index.json");
  const index = {
    slug,
    fullName: contributor.fullName,
    totalSermons: totalAvailable,
    fetched: fetched + skipped,
    withTranscript: fetched + skipped - noTranscript,
    noTranscript,
    scrapedAt: new Date().toISOString(),
    sermons: allSermons.map((s) => ({
      id: s.id,
      title: s.title,
      mediaType: s.mediaType,
      duration: s.duration,
    })),
  };
  fs.writeFileSync(indexPath, JSON.stringify(index, null, 2), "utf8");

  console.log(`  ✓ Done — ${fetched} new, ${skipped} cached, ${noTranscript} without transcript`);
}

// ── main ───────────────────────────────────────────────────────────────────

async function main() {
  console.log("=== SermonIndex Transcript Scraper v2 ===");
  console.log(`Contributors: ${CONTRIBUTORS.length}`);
  console.log(`Max sermons each: ${MAX_TOTAL}`);
  console.log(`Output: ${path.resolve(OUT_DIR)}\n`);

  fs.mkdirSync(OUT_DIR, { recursive: true });

  for (const slug of CONTRIBUTORS) {
    await scrapeContributor(slug);
  }

  console.log("\n=== Complete ===");
}

main().catch((e) => {
  console.error("Fatal:", e);
  process.exit(1);
});
