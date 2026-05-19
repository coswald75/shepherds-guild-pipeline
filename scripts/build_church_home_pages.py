"""
Generate per-church home/about pages.

Renders one `<repo>/<url_slug>/index.html` per church, with an
"About the church" section and an "About the preacher" section.

The body copy is curated per-church (not generated live) — kept in
CHURCH_COPY below. New churches need a manual entry. The page wrapper
(header, breadcrumb, hero, sermon-archive callout, visit card, footer)
is the shared Sermon Steward chrome.
"""

from __future__ import annotations

import html
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env", override=True)

from sermon_page_renderer import queries as q  # noqa: E402

SERMON_STEWARD_REPO = Path("/Users/dad/shepherds-guild/sermon-steward")

CHURCH_IDS = [
    "c121e66b-777d-4568-89d3-9ceea258061b",  # Providence
    "f1fc9898-fafd-4289-b6af-ce99dfde23d6",  # Cross of Grace
]


# Per-church copy. Keys are `churches.url_slug`. The HTML inside each section
# is rendered inline; keep markup minimal and in line with the page's
# typographic system (<p>, <h3>, <ul>/<li>, <strong>, <em>).
CHURCH_COPY: dict[str, dict] = {
    "ProvidenceLenexa": {
        "hero_tagline": "Display truth and beauty in community.",
        "external_site": {
            "label": "sovgracekc.org",
            "url": "https://sovgracekc.org/",
            "visit_url": "https://sovgracekc.org/visit/",
            "beliefs_url": "https://sovgracekc.org/beliefs/",
            "leadership_url": "https://sovgracekc.org/leadership/",
        },
        "visit": {
            "service_time": "Sundays at 10:00 AM",
            "address_line": "10113 Lenexa Dr · Lenexa, KS",
            "shape_line": "Four songs of worship, then a 35–40 minute expository sermon. Casual dress. Coffee on arrival. Drop-off lane in front for kids and guests who need it.",
        },
        "about_church_html": """
<p>Providence Community Church is a gospel-centered congregation in Lenexa, Kansas. Its mission is to <em>display truth and beauty in community</em> — a phrase that names what most churches assume but few articulate. The gospel produces a way of life that is not only true but lovely; not only doctrinally serious but culturally generative; not only personally formative but communally visible.</p>

<p>The church sits inside the classical tradition that treats truth, beauty, and goodness as joined transcendentals, and the preaching reflects that. Sermons engage what's sometimes called "the great conversation" — the long human inquiry into what is real, what is good, what is worth wanting — and bring scripture into that inquiry as both authority and answer. The church culture pairs a strong commitment to truth with an unembarrassed practice of beauty, feasting, and grateful pursuit of the good life as faithful Christian living.</p>

<h3>What Providence values</h3>
<p>Providence states its values as comparisons rather than slogans — clearer about what is being chosen against:</p>
<ul class="values">
  <li><strong>Humility &gt; Pride</strong> — Humility is an accurate view of God and ourselves; the foundation under every other virtue.</li>
  <li><strong>Courage &gt; Cowardice</strong> — Courage flows from humility, cowardice from pride. The church wants to help people live authentically courageous lives.</li>
  <li><strong>Celebration &gt; Envy</strong> — Envy is treated as a much bigger spiritual problem than usually credited; the cross makes it possible to root for one another.</li>
  <li><strong>Facts &gt; Feelings</strong> — Feelings matter, but when feelings and facts disagree, the work is to bring the feeling into the truth — not the truth into the feeling.</li>
  <li><strong>Honesty &gt; Spin</strong> — Say what you mean and mean what you say. <em>By the open statement of the truth we would commend ourselves to everyone's conscience in the sight of God.</em></li>
  <li><strong>Freedom &gt; Guilt</strong> — The world uses guilt to coerce conformity; the gospel sets people free. Confession leads to cleansing, not condemnation.</li>
</ul>

<p class="kicker">Full statement of faith, leadership team, visitor information, and ways to get involved are at <a href="{external_url}" target="_blank" rel="noopener">{external_label}</a>.</p>
""",
        "about_preacher_html": """
<p>Chris Oswald is in his tenth year of serving as the Senior Pastor at Providence Community Church. During that time he has built a substantial sermon archive with a distinct approach uniquely his own.</p>

<h3>The Gospel of Jesus Christ, Accomplished and Applied</h3>
<p>Chris's preaching anchors in the gospel — what Christ <em>accomplished</em> in his life, his death, his resurrection, and his ongoing reign. Every sermon begins there and returns there. But the preaching never leaves the gospel as an announcement only. It moves, with measurable consistency, into <em>application</em> — into what the gospel makes possible in the life of an actual hearer.</p>

<p>This is where the sanctification emphasis lives. Sermon after sermon, the preaching engages the long obedience, the slow formation, the cost of discipleship, the work of becoming the kind of person the gospel makes possible. That reflects a settled pastoral conviction: the gospel is announced <em>and</em> applied. A sermon that names what Christ has done without naming what it asks of the hearer has stopped too early.</p>

<h3>Expository, series-driven, patient</h3>
<p>Most of Chris's sermons are expository — walking through scripture passage by passage rather than gathering verses around a topic. The preferred unit is the multi-week series. Over the years he has worked through the Gospel of Luke, Galatians, 1 John, Ephesians, Colossians, Exodus, and a long-form arc through the Psalms. The instinct is that the shape of a biblical book matters, the shape of a series matters, and the shape of formation matters — and that a pastor should not arrive at Sunday without a long-arc theological argument already in flight.</p>

<h3>Theologically dense without being academic</h3>
<p>Chris reads broadly, and it shows. Across the corpus his most-quoted sources span two thousand years of Christian thought: the Apostle Paul, C.S. Lewis, Charles Spurgeon, J.I. Packer, Jonathan Edwards, John Piper, Martin Luther, John Calvin, John Owen, Augustine, Sinclair Ferguson, D.A. Carson, John Stott. Wide reading produces preaching that is at home in both the historical Church and contemporary cultural moments — but never as ornament. Quotes serve the argument; they don't replace it.</p>

<h3>Preaching in the Great Conversation</h3>
<p>Chris reads outside the immediate theological tradition too — and he preaches that way. Sermons routinely interact with classical and contemporary voices from philosophy, political theory, history, and the wider Western canon: figures from Plato and Aristotle to Augustine the political theologian, MacIntyre and Charles Taylor and the moderns wrestling with what it means to be a self. The preaching positions the church inside the long human inquiry into what is real, good, and worth wanting — not as an outsider asking permission, but as a participant with something definite to contribute.</p>

<p>What's more distinctive still is his soft spot for <strong>STEM-driven illustrations and metaphors</strong> — analogies pulled from physics, biology, medicine, computer science, and mathematics. A doctrine about union with Christ might land through the language of complex systems; a claim about the conscience through feedback loops; sanctification through the way muscle is actually built. The aim is the same as ever: to make the unseen reality visible by using structures the hearer already trusts.</p>

<h3>Concrete application — four times per sermon, on average</h3>
<p>What distinguishes the application is <em>concreteness</em>. Chris averages four applications per sermon — measurably above the working baseline for expository preachers. More importantly, more than half of those applications are concrete: not "trust God in suffering" but the specific Tuesday-afternoon decision. Personal stories appear in roughly a third of his illustrations; cultural references in another fifth. He is preaching to the congregation he knows, not to a generic "modern listener."</p>

<h3>Doctrine that earns the emotion</h3>
<p>Chris's preaching is mind-engaged before it is heart-engaged — careful, argued, scripturally precise. But he doesn't skip the weight. The rhetorical register sits at roughly <strong>three-quarters Logos and one-third Pathos</strong>: explain the truth, ask what it costs to live in it, and let the listener feel the weight before moving on. The doctrine earns the emotion; the emotion is never manufactured.</p>

<p class="kicker">In short: a pastor's pastor. Theologically serious, pastorally warm, structurally patient, and consistently more concerned with what a sermon <em>does</em> in someone's actual life than with how it sounds in the moment of preaching.</p>
""",
    },
    "CoGElPaso": {
        "hero_tagline": "Gospel renewal in the city, and through the city.",
        "external_site": {
            "label": "crossofgrace.net",
            "url": "https://www.crossofgrace.net/",
            "visit_url": "https://www.crossofgrace.net/about-us",
            "beliefs_url": "https://www.crossofgrace.net/about-us",
            "leadership_url": "https://www.crossofgrace.net/staff-leaders",
        },
        "visit": {
            "service_time": "Sundays at 9:00 & 11:00 AM",
            "address_line": "4700 Leeds Avenue · El Paso, TX 79903",
            "shape_line": "Gospel-centered worship — classic hymns and newer songs, testimony, expository preaching. Kids program through fifth grade. A soft room with live video for moms of infants and toddlers.",
        },
        "about_church_html": """
<p>Cross of Grace Church is a gospel-centered congregation in the heart of historic El Paso, Texas — where the United States meets Mexico and two countries share daily life. The church's heartbeat is <em>gospel renewal in the city, and through the city, in the world.</em> The conviction underneath the work is straightforward: Jesus has changed our lives for the better, and we believe he can change anyone's life.</p>

<p>Sundays at Cross of Grace are unembarrassedly centered on the gospel. Two services — 9:00 and 11:00 — gather the congregation around the good news of Jesus' life, death, and resurrection in every element: singing, testimony, preaching. The music blends classic hymns and newer songs, following Colossians 3:16's pattern of psalms, hymns, and spiritual songs. Kids have their own program through fifth grade, and a soft room with a live video feed serves moms of infants and toddlers.</p>

<p>The distinctive posture is <em>outward.</em> Cross of Grace exists for El Paso. Home groups gather across the city during the week. Mission and outreach are not a separate program — they're built into the church's pattern of life. The leadership is a multi-pastor team: Lead Pastor Ricky Alcantar serves alongside pastors Todd Peterson, Chuck Mosely, Joe Alcantar Jr., and Jonathan Vogan, with younger leaders in formation behind them.</p>

<p class="kicker">Full confession of faith, leadership team, visitor information, and ways to get involved are at <a href="{external_url}" target="_blank" rel="noopener">{external_label}</a>.</p>
""",
        "about_preacher_html": """
<p>Ricky Alcantar serves as the Lead Pastor at Cross of Grace Church in El Paso. He shepherds a multicultural congregation gathered on the US-Mexico border, and his preaching is built for the people he serves and the city he loves.</p>

<h3>The Gospel That Names the Pressure Before It Speaks</h3>
<p>Every Ricky sermon has a recognizable shape. He names the cultural moment first — directly, by data and by example. A viral monologue. A piece of demographic research. An interview on NPR. A Disney scene. A news cycle. The diagnosis is detailed and unflinching. <em>Then</em>, explicitly, the pivot: <em>"And here's the good news from this text."</em> The phrase shows up once or twice per sermon, every time, marking the exact moment the air in the room changes. The world's pressure gets named in full — and then the gospel speaks back, not as if the diagnosis weren't real, but as the one true answer to a real problem.</p>

<h3>A Church for a Specific City</h3>
<p>What anchors Ricky's preaching theologically is <strong>ecclesiology</strong> — the doctrine of the church. Across the corpus, his most-developed theological theme is what it means to be the church <em>together</em>: gathered in Christ, sent on mission, accountable to one another, learning to bear each other's weight. The sermons are not about a generic Christian life. They are about <em>this</em> church living <em>this</em> faith in <em>this</em> city.</p>

<p>And the city is El Paso. The border is not a special topic in Ricky's preaching — it's the air the church breathes. Bilingual jokes, Hispanic-household references, the awareness that the congregation includes mixed marriages and English-only families and lifelong El Pasoans and recent arrivals — none of this is performed. It's just present. Cross of Grace exists for El Paso, and Ricky preaches that way.</p>

<h3>Friends, Brothers, and Sisters</h3>
<p>Where other expositors reach for <em>"you"</em> singular, Ricky reaches for <em>friends, brothers and sisters, moms, young men, church family.</em> The vocative is constant. He treats the room as people he knows and loves — and he treats himself the same way. He is rarely the hero of his own illustrations. He's the man who forgot his glasses, the dad doing school drop-off, the pastor who sometimes hears from members in counseling, <em>"Do you have anything else? Beyond the Bible?"</em> The preaching never positions the speaker above the listener. It positions him alongside them, including in his own ordinary mornings.</p>

<h3>Pop Culture Plus the Apostles</h3>
<p>Ricky reads broadly, and he preaches that way. His most-quoted sources span the Apostle Paul, Charles Spurgeon, Wayne Grudem, Kent Hughes, John Piper, D.A. Carson, John Calvin, G.K. Beale, Sinclair Ferguson, Tim Keller, G.K. Chesterton — and <strong>Johnny Cash</strong>. (Yes — six citations across the corpus, and they earn their keep.) On any given Sunday a sermon might pull from Jeopardy, a Disney movie, a viral monologue, an NPR interview, or the Declaration of Independence — but always serving doctrine, never decorating it. A pop-culture reference in Ricky's preaching is earning the next sentence about Christ.</p>

<h3>Application That Lands on Tuesday Morning</h3>
<p>Ricky applies the text relentlessly — five or six times per sermon, on average, which is meaningfully above the working baseline for expository preachers. More importantly, the applications are concrete. Not <em>"trust God in suffering,"</em> but the specific decision in the school-prep routine. Not <em>"pursue holiness,"</em> but the moment in the counseling office where a young man fails at the thing he was sure he had under control. He is preaching to actual people in actual lives, and the applications never quite let the listener escape into abstraction.</p>

<h3>Doctrine That Feels Like Being Loved</h3>
<p>Ricky's rhetorical register is mind-engaged but with notable emotional warmth — more pathos per sermon than most of his expository peers. When something is hard, he names that it's hard. When obedience costs, he names that it costs. The result is preaching that earns trust before it asks for change — and then asks for change, because the gospel does ask. The doctrine doesn't only argue. It <em>acknowledges</em> — and that acknowledgment is part of what makes the gospel pivot land.</p>

<p class="kicker">In short: a pastor for the people he actually pastors. Cultural diagnostician, gospel announcer, expository builder, son of the border, friend of the room.</p>
""",
    },
}


PAGE_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{church_name} — {hero_tagline} · Sermon Steward</title>
<meta name="description" content="{meta_description}">
<link rel="canonical" href="https://sermonsteward.com/{url_slug}/">
<meta property="og:type" content="website">
<meta property="og:title" content="{church_name}">
<meta property="og:description" content="{meta_description}">
<meta property="og:url" content="https://sermonsteward.com/{url_slug}/">
<meta property="og:site_name" content="Sermon Steward">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg: #fbf8f1;
    --bg-card: #ffffff;
    --ink: #1a1a1a;
    --ink-soft: #4a4a4a;
    --ink-faint: #828282;
    --rule: #e6e1d3;
    --accent: #c4452f;
    --accent-deep: #9a3624;
    --highlight: #fef0c8;
    --sans: 'Inter', system-ui, -apple-system, sans-serif;
  }}
  * {{ box-sizing: border-box; }}
  html, body {{
    margin: 0; padding: 0; background: var(--bg); color: var(--ink);
    font-family: var(--sans); font-size: 17px; line-height: 1.6;
    -webkit-font-smoothing: antialiased;
  }}
  a {{ color: var(--accent); text-decoration: none; }}
  a:hover {{ color: var(--accent-deep); }}
  .site-header {{ padding: 24px 32px; border-bottom: 1px solid var(--rule); }}
  .wordmark {{ font-weight: 800; font-size: 22px; letter-spacing: -0.02em; color: var(--ink); }}
  .wordmark .dot {{ color: var(--accent); }}
  main {{ max-width: 760px; margin: 0 auto; padding: 48px 32px 96px; }}
  .breadcrumb {{ font-size: 13px; color: var(--ink-faint); margin-bottom: 20px; }}
  .breadcrumb a {{ color: var(--ink-soft); text-decoration: underline; text-underline-offset: 3px; }}
  h1 {{
    font-size: clamp(2.2rem, 5vw, 3.2rem); font-weight: 800;
    letter-spacing: -0.03em; line-height: 1.04;
    margin: 0 0 12px;
  }}
  .hero-tagline {{
    font-size: clamp(1.15rem, 2vw, 1.35rem);
    color: var(--accent-deep); font-style: italic;
    margin: 0 0 8px; font-weight: 500;
  }}
  .hero-meta {{ color: var(--ink-soft); font-size: 15px; margin: 0 0 56px; }}
  h2 {{
    font-size: 13px; font-weight: 600; letter-spacing: 0.08em;
    text-transform: uppercase; color: var(--accent);
    margin: 56px 0 18px; padding-bottom: 12px;
    border-bottom: 1px solid var(--rule);
  }}
  h3 {{ font-size: 21px; font-weight: 700; margin: 32px 0 10px; letter-spacing: -0.01em; }}
  p {{ margin: 0 0 16px; color: var(--ink); }}
  ul.values {{ list-style: none; margin: 18px 0 24px; padding: 0; }}
  ul.values li {{ padding: 10px 0; border-bottom: 1px solid var(--rule); }}
  ul.values li:last-child {{ border-bottom: 0; }}
  ul.values strong {{ color: var(--accent-deep); }}
  .kicker {{
    margin-top: 24px; padding: 14px 18px;
    background: #fff; border: 1px solid var(--rule); border-radius: 10px;
    font-size: 15px; color: var(--ink-soft);
  }}
  .card-row {{
    display: grid; gap: 16px;
    grid-template-columns: 1fr 1fr;
    margin-top: 24px;
  }}
  @media (max-width: 640px) {{ .card-row {{ grid-template-columns: 1fr; }} }}
  .card {{
    background: var(--bg-card); border: 1px solid var(--rule);
    border-radius: 12px; padding: 22px 24px;
  }}
  .card-label {{ font-size: 11px; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase; color: var(--accent); margin-bottom: 8px; }}
  .card h4 {{ margin: 0 0 8px; font-size: 18px; font-weight: 700; letter-spacing: -0.01em; }}
  .card p {{ font-size: 15px; margin: 0 0 6px; color: var(--ink-soft); }}
  .card a.btn {{
    display: inline-flex; align-items: center; gap: 6px;
    font-size: 14px; font-weight: 600; margin-top: 8px;
    color: var(--accent);
  }}
  .card a.btn:hover {{ color: var(--accent-deep); }}
  .archive-cta {{
    margin: 40px 0 0;
    background: var(--accent); color: #fff;
    border-radius: 12px; padding: 24px 28px;
    display: flex; align-items: center; justify-content: space-between; gap: 16px;
  }}
  .archive-cta p {{ color: #fff; margin: 0; font-size: 16px; font-weight: 500; }}
  .archive-cta a {{
    color: #fff; font-weight: 700;
    padding: 12px 20px; border: 1px solid rgba(255,255,255,0.4);
    border-radius: 8px; white-space: nowrap;
    transition: background 0.12s;
  }}
  .archive-cta a:hover {{ background: rgba(255,255,255,0.12); color: #fff; }}
  footer {{
    padding: 24px 32px; font-size: 13px; color: var(--ink-faint);
    text-align: center; border-top: 1px solid var(--rule);
  }}
  footer a {{ color: var(--ink-soft); }}
</style>
</head>
<body>

<header class="site-header">
  <a class="wordmark" href="/">Sermon Steward<span class="dot">.</span></a>
</header>

<main>
  <div class="breadcrumb"><a href="/">Sermon Steward</a> · {church_name}</div>
  <h1>{church_name}</h1>
  <p class="hero-tagline">{hero_tagline}</p>
  <p class="hero-meta">{location} · {service_time}</p>

  <h2>About the Church</h2>
  {about_church_html}

  <h2>About the Preacher</h2>
  {about_preacher_html}

  <div class="archive-cta">
    <p>Browse {sermon_count} stewarded sermons from {church_name_short} — every page includes the transcript, discussion guide, daily readings, prayer prompt, family card, couples guide, and memory verse.</p>
    <a href="/{url_slug}/sermons/">Open the sermon archive →</a>
  </div>

  <h2>Visit & Connect</h2>
  <div class="card-row">
    <div class="card">
      <div class="card-label">Visit on Sunday</div>
      <h4>{service_time}</h4>
      <p>{address_line}</p>
      <p>{shape_line}</p>
      <a class="btn" href="{visit_url}" target="_blank" rel="noopener">Plan your visit →</a>
    </div>
    <div class="card">
      <div class="card-label">Church Website</div>
      <h4>{external_label}</h4>
      <p>Statement of faith, leadership team, ministries, contact, and the church's own home on the web.</p>
      <a class="btn" href="{external_url}" target="_blank" rel="noopener">Visit {external_label} →</a>
    </div>
  </div>
</main>

<footer>
  Sermon Steward stewards the preaching of {church_name}. The church itself lives at <a href="{external_url}" target="_blank" rel="noopener">{external_label}</a>.
</footer>

</body>
</html>
"""


def _format_location(address: dict | None) -> str:
    if not address:
        return ""
    bits = []
    if address.get("locality"):
        bits.append(address["locality"])
    if address.get("region"):
        bits.append(address["region"])
    return ", ".join(bits)


def _count_sermons_with_bundle(sb, preacher_ids: list[str]) -> int:
    if not preacher_ids:
        return 0
    candidates = (
        sb.table("sermons")
        .select("id")
        .in_("preacher_id", preacher_ids)
        .not_.is_("main_thesis", "null")
        .not_.is_("date", "null")
        .not_.is_("slug", "null")
        .execute()
        .data
        or []
    )
    ids = [c["id"] for c in candidates]
    if not ids:
        return 0
    artifacts = (
        sb.table("sermon_artifacts")
        .select("sermon_id, artifact_type")
        .in_("sermon_id", ids)
        .execute()
        .data
        or []
    )
    bundle: dict[str, set[str]] = {}
    for row in artifacts:
        bundle.setdefault(row["sermon_id"], set()).add(row["artifact_type"])
    # Require the 6 original pastoral artifacts. Newer sermons also carry
    # imperatives_indicatives + sermon_scraps; older ones don't. Subset
    # check keeps both publishable.
    required = {
        "small_group_questions", "daily_readings", "prayer_prompt",
        "family_card", "couples_guide", "memory_verse",
    }
    return sum(1 for sid in ids if required.issubset(bundle.get(sid, set())))


def main() -> int:
    sb = q.get_supabase()

    churches = (
        sb.table("churches")
        .select("id, name, url_slug, address, service_times")
        .in_("id", CHURCH_IDS)
        .execute()
        .data
        or []
    )

    # Preacher mapping for sermon counts
    preachers = (
        sb.table("preachers")
        .select("id, church_id")
        .in_("church_id", CHURCH_IDS)
        .execute()
        .data
        or []
    )
    preacher_by_church: dict[str, list[str]] = {}
    for p in preachers:
        preacher_by_church.setdefault(p["church_id"], []).append(p["id"])

    rendered = 0
    for c in churches:
        url_slug = c["url_slug"]
        copy = CHURCH_COPY.get(url_slug)
        if not copy:
            print(f"skipping {url_slug} — no curated copy yet")
            continue

        ext = copy["external_site"]
        visit = copy["visit"]
        location = _format_location(c.get("address")) or ""
        sermon_count = _count_sermons_with_bundle(sb, preacher_by_church.get(c["id"], []))
        church_name = c["name"] or url_slug
        # Drop trailing "Church" for the inline mention in CTA copy
        church_name_short = church_name
        for suffix in (" Community Church", " Church"):
            if church_name_short.endswith(suffix):
                church_name_short = church_name_short[: -len(suffix)]
                break

        meta_description = (
            f"{church_name} in {location}. {copy['hero_tagline']} "
            f"Browse the church's full sermon archive, stewarded weekly."
        )

        about_church_html = copy["about_church_html"].format(
            external_url=ext["url"],
            external_label=ext["label"],
        )

        page_html = PAGE_TEMPLATE.format(
            church_name=html.escape(church_name),
            church_name_short=html.escape(church_name_short),
            url_slug=html.escape(url_slug),
            hero_tagline=html.escape(copy["hero_tagline"]),
            location=html.escape(location or "—"),
            service_time=html.escape(visit["service_time"]),
            address_line=html.escape(visit["address_line"]),
            shape_line=html.escape(visit["shape_line"]),
            visit_url=html.escape(ext["visit_url"]),
            external_label=html.escape(ext["label"]),
            external_url=html.escape(ext["url"]),
            sermon_count=sermon_count,
            about_church_html=about_church_html,
            about_preacher_html=copy["about_preacher_html"],
            meta_description=html.escape(meta_description),
        )

        out_dir = SERMON_STEWARD_REPO / url_slug
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "index.html"
        out_path.write_text(page_html, encoding="utf-8")
        print(f"wrote {out_path}  ({sermon_count} sermons in archive)")
        rendered += 1

    print(f"\nTotal home pages written: {rendered}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
