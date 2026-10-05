"""SG Midwest/Northwest (MWNW) launch: the eight churches and where each Sunday's sermon comes from.

Source kinds (tried in order per run, first hit wins; a church is processed ONCE per week):
  podcast   - RSS feed, episode matched by date (pubDate Sun..Sun+4d, or a date in title/URL)
  youtube   - channel livestream from that Sunday; the full service is transcribed and the
              sermon is cut out (livecut.py)
  gracelife - Grace Life's WordPress /resource/ pages (MP3 named like Chad-Haygood-9-27-26.mp3)
  pipeline  - Providence: processed by the iMac weekly/catchup jobs; we only look the sermon up.

`sources` maps a run ("sunday" / "monday") to the ordered source list for that run, following
publish_lag_summary.md (Oct 3 2026):
  Star, Roseburg   livestream only (CLF podcast is typically 2-4 days late)
  Bozeman          YouTube first, then the Anchor podcast (as Chris asked); match by date
  Chaska           YouTube live Sunday is reliable; podcast lands Mon 4-10pm (Monday fallback)
  Burnsville       PCO podcast lands Sun 12-2pm
  Grace Life       site MP3 lands Sun ~11:30
  Sioux Falls      Subsplash posts Mon ~2pm (all 13/13 by 4pm) -> Monday only
"""
REGION = "MidwestNorthwest"
REGION_NAME = "Sovereign Grace Midwest/Northwest"
SITE = "https://sermonsteward.com"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"

CHURCHES = [
    dict(key="cog", dir="CrossOfGraceChaska", old_dir="CrossOfGraceChaska",
         # Chaska only — Ricky / El Paso is cogep / CoGElPaso (not in this MWNW list).
         church="Cross of Grace Church Chaska",
         # HELD public title: the church index <title>/H1 keep the DB name until Chris approves the
         # churches.name rename (same hold as site commit f8c61dd). Drop index_name when that lands.
         index_name="Cross of Grace Church",
         city="Chaska", state="MN", site="https://crossgrace.org/", default_preacher="Dan Birkholz",
         church_id="382b4e46-06eb-4989-a567-ad53e5dda454",
         podcast="https://publishing.planningcenteronline.com/393613/podcast_feeds/27836.xml",
         youtube="UCzqtU8ChwpqM2n9Y-WCLl-Q",
         sources={"sunday": ["youtube"], "monday": ["podcast", "youtube"]}),
    dict(key="ccc", dir="CornerstoneBurnsville", old_dir="CornerstoneBurnsville", church="Cornerstone Community Church",
         city="Burnsville", state="MN", site="https://cornerstonemn.church/", default_preacher="Rick Gamache",
         church_id="89a09ea9-6c7c-4375-bcda-1d670b944ec2",
         podcast="https://publishing.planningcenteronline.com/136777/podcast_feeds/22496.xml",
         sources={"sunday": ["podcast"], "monday": ["podcast"]}),
    dict(key="ercsf", dir="EmmausRoadSiouxFalls", old_dir="EmmausRoadSiouxFalls", church="Emmaus Road Church",
         city="Sioux Falls", state="SD", site="https://emmausroadsf.com/", default_preacher="Ryan Chase",
         church_id="8267c227-c0e5-4c0e-95ff-d04be2e857e6",
         podcast="https://podcasts.subsplash.com/wghtjqt/podcast.rss",
         sources={"sunday": [], "monday": ["podcast"]}),
    dict(key="prov", dir="ProvidenceLenexa", church="Providence Community Church", city="Lenexa", state="KS",
         site="https://sovgracekc.org/", default_preacher="Chris Oswald",
         church_id="c121e66b-777d-4568-89d3-9ceea258061b", public=True,
         podcast="https://sermons.sovgracekc.org/feed/",
         # Normally the iMac pipeline ingests Providence ("pipeline" = DB lookup only). For a run
         # that can't wait, MWNW_PROV_SELF_INGEST=1 lets this runner ingest it from the same feed,
         # writing the same podcast_guid the iMac's RSS sync keys on (unique index) and setting
         # decomposed_at, so the iMac sees it as done and never re-inserts or re-decomposes it.
         self_ingest_env="MWNW_PROV_SELF_INGEST",
         sources={"sunday": ["pipeline"], "monday": ["pipeline"]}),
    dict(key="gl", dir="GraceLifeHastings", old_dir="GraceLifeHastings", church="Grace Life Church",
         city="Hastings", state="NE", site="https://www.gracelifene.org/", default_preacher="Chad Haygood",
         church_id="3f0e3d29-bb37-413f-8248-9b00b53890d8",
         gracelife="https://www.gracelifene.org/resource/",
         sources={"sunday": ["gracelife"], "monday": ["gracelife"]}),
    dict(key="clf", dir="CovenantLifeRoseburg", old_dir="CLFRoseburg", church="Covenant Life Fellowship",
         city="Roseburg", state="OR", site="https://clfroseburg.com/", default_preacher="Dave York",
         church_id="5e36c0d3-2369-45d3-8ffa-056cb3d7d6fa",
         youtube="UCiCDYe6GpMD-bRjJnAwvjZQ",
         sources={"sunday": ["youtube"], "monday": ["youtube"]}),
    dict(key="ercb", dir="EmmausRoadBozeman", old_dir="EmmausRoadBozeman", church="Emmaus Road Church",
         city="Bozeman", state="MT", site="https://ercbozeman.com/", default_preacher="Ron Boomsma",
         church_id="fc633bba-809d-4614-8740-c16dcdddcf9d",
         youtube="UCavPMfkbn3qZX-QN0WNMzeQ", podcast="https://anchor.fm/s/c2abfce4/podcast/rss",
         sources={"sunday": ["youtube", "podcast"], "monday": ["youtube", "podcast"]}),
    dict(key="star", dir="CenterChurchStar", old_dir="CenterChurchStar", church="Center Church of Star",
         city="Star", state="ID", site="https://www.centerchurchstar.com/", default_preacher="Jeff Palen",
         church_id="408dfa64-a557-4090-817b-b926a3cec931",
         youtube="UCaNxmLfZpzFAPdEZfoUugDA",
         sources={"sunday": ["youtube"], "monday": ["youtube"]}),
]
BY_KEY = {c["key"]: c for c in CHURCHES}

# Where alerts go when something fails. Override with MWNW_ALERT_TO in .env.
DEFAULT_ALERT_TO = "chris@sovgracekc.org"

# ── Recipients: BEST GUESSES from each church's public website (checked Oct 3 2026). Chris fixes
#    these himself on Tuesday; we copy his pattern after that. Nothing is sent without his approval.
#    "published" = the address is printed on the church site; "general inbox" = not the pastor's own.
RECIPIENTS = {
    "cog":   dict(to=["contact@crossgrace.org"], pastor="Dan Birkholz (Lead Pastor)", basis="published general inbox, crossgrace.org/leadership/; no personal pastor address listed"),
    "ccc":   dict(to=["admin@cornerstonemn.church"], pastor="Rick Gamache (Senior Pastor)", basis="published general inbox, cornerstonemn.church/leadership/; no personal pastor address listed"),
    "ercsf": dict(to=["hello@emmausroadsf.com"], pastor="Ryan Chase (Pastor)", basis="published general inbox, emmausroadsf.com home page; staff pages block automated fetches"),
    "prov":  dict(to=["chris@sovgracekc.org"], pastor="Chris Oswald (Pastor)", basis="published, sovgracekc.org/contact/ (Chris's own church)"),
    "gl":    dict(to=["chad@gracelifene.org"], pastor="Chad Haygood (Pastor)", basis="published personal address, gracelifene.org/learn/who-we-are/leadership/"),
    "clf":   dict(to=["church@clfroseburg.com"], pastor="Dave York (Pastor)", basis="published general inbox, clfroseburg.com home page; no personal pastor address listed"),
    "ercb":  dict(to=["hi@ercbozeman.com"], pastor="Ron Boomsma (Senior Pastor)", basis="published general inbox, ercbozeman.com/leadership/; no personal pastor address listed"),
    "star":  dict(to=["jeff@centerchurchstar.com"], pastor="Jeff Palen (Lead Pastor)", basis="published personal address, centerchurchstar.com/team"),
}
RECIPIENTS_ARE_BEST_GUESS = True   # flip only after Chris confirms the list

# Email body (Chris, Oct 3). P1 is his to write; P2 and P3 are verbatim. No pricing in these emails:
# the MWNW churches are free for at least a year.
P1_PLACEHOLDER = "[Chris writes opening paragraph: permission and opt-out]"
GLOSSARY_URL = "https://sermonsteward.com/hall/glossary"   # 200 on Oct 3 2026 (/glossary is 404)
SPURGEON_URL = "https://sermonsteward.com/SignificantSermons/spurgeon/sermons/compel-them-to-come-in"   # 200 on Oct 3 2026
PLACEHOLDER_PREFIX = "["

# PDF: the existing report has a sample article ghost-written "in the pastor's voice". Only Chris
# and Ricky have voice profiles; everyone else gets a generic SG voice. Off for churches unless
# Chris says otherwise.
INCLUDE_SAMPLE_ARTICLE = False
