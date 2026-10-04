"""Shared plumbing: paths, per-week state, retries, HTTP, alerts, spend tracking."""
from __future__ import annotations
import json, logging, os, sys, time, functools, fcntl, contextlib
# yt-dlp / deno / ffmpeg live next to this venv's python; make sure child processes find them
# even when launched without the venv's bin on PATH.
os.environ["PATH"] = os.path.dirname(sys.executable) + os.pathsep + os.environ.get("PATH", "")
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO)); sys.path.insert(0, str(REPO / "scripts"))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(REPO / ".env")
import requests  # noqa: E402
from . import config  # noqa: E402

CT = ZoneInfo("America/Chicago")
log = logging.getLogger("mwnw")
if not log.handlers:
    h = logging.StreamHandler(); h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"))
    log.addHandler(h); log.setLevel(logging.INFO); log.propagate = False
for n in ("httpx", "httpcore", "urllib3"): logging.getLogger(n).setLevel(logging.WARNING)


def week_dir(week: str) -> Path:
    d = REPO / "output" / "mwnw" / week
    d.mkdir(parents=True, exist_ok=True)
    return d


def week_slug(week: str) -> str:
    """2026-10-04 -> 10-4-26 (the regional pages' M-D-YY slug)."""
    d = date.fromisoformat(week)
    return f"{d.month}-{d.day}-{d.strftime('%y')}"


def default_week(now: datetime | None = None) -> str:
    """The most recent Sunday (today if it is Sunday), in Central time."""
    now = now or datetime.now(CT)
    d = now.date()
    return (d - timedelta(days=(d.weekday() + 1) % 7)).isoformat()


class State:
    """output/mwnw/<week>/<key>/state.json: ONE FILE PER CHURCH, so each church's ingest runs on
    its own (own process, own lock, own state) and a late or failing church never blocks another."""
    def __init__(self, week: str, key: str):
        self.week, self.key = week, key
        self.dir = week_dir(week) / key; self.dir.mkdir(exist_ok=True)
        self.path = self.dir / "state.json"
        self.data = json.loads(self.path.read_text()) if self.path.exists() else {"key": key, "week": week, "log": []}

    def save(self):
        tmp = self.path.with_suffix(".tmp"); tmp.write_text(json.dumps(self.data, indent=1, default=str)); tmp.replace(self.path)


def load_all(week: str) -> dict:
    return {c["key"]: State(week, c["key"]).data for c in config.CHURCHES}


@contextlib.contextmanager
def church_lock(week: str, key: str):
    """At most one process per church per week. Returns False (yield) if another holds it."""
    d = week_dir(week) / key; d.mkdir(exist_ok=True)
    f = open(d / ".lock", "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB); got = True
    except BlockingIOError:
        got = False
    try:
        yield got
    finally:
        if got: fcntl.flock(f, fcntl.LOCK_UN)
        f.close()


def run_label(now: datetime | None = None, week: str | None = None) -> str:
    """'sunday' until midnight Sunday night CT, then 'monday' (picks each church's source list)."""
    now = now or datetime.now(CT); week = week or default_week(now)
    return "sunday" if now.date() <= date.fromisoformat(week) else "monday"


def retry(tries=3, wait=10, what="step"):
    def deco(fn):
        @functools.wraps(fn)
        def inner(*a, **kw):
            for i in range(1, tries + 1):
                try:
                    return fn(*a, **kw)
                except Exception as e:  # noqa: BLE001
                    if i == tries: raise
                    log.warning(f"{what} attempt {i}/{tries} failed: {str(e)[:300]}; retrying in {wait * i}s")
                    time.sleep(wait * i)
        return inner
    return deco


@retry(tries=4, wait=5, what="http")
def http_get(url: str, timeout=30, **kw) -> requests.Response:
    r = requests.get(url, headers={"User-Agent": config.UA}, timeout=timeout, **kw)
    r.raise_for_status()
    return r


# ── Spend: count tokens on every Anthropic call made in this process ─────────
PRICES = {"sonnet": (3.0, 15.0), "haiku": (1.0, 5.0)}   # $/M tokens in, out
USAGE = {"sonnet": [0, 0], "haiku": [0, 0], "aai_seconds": 0}

def _install_usage_hook():
    from anthropic.resources.messages import Messages
    if getattr(Messages.create, "_mwnw", False): return
    orig = Messages.create
    def create(self, *a, **kw):
        r = orig(self, *a, **kw)
        try:
            b = USAGE["haiku" if "haiku" in kw.get("model", "") else "sonnet"]
            u = r.usage; b[0] += u.input_tokens + (getattr(u, "cache_read_input_tokens", 0) or 0) + (getattr(u, "cache_creation_input_tokens", 0) or 0); b[1] += u.output_tokens
        except Exception: pass
        return r
    create._mwnw = True; Messages.create = create
_install_usage_hook()

def spend_usd() -> float:
    llm = sum(USAGE[m][0] / 1e6 * PRICES[m][0] + USAGE[m][1] / 1e6 * PRICES[m][1] for m in PRICES)
    return round(llm + USAGE["aai_seconds"] / 3600 * 0.37, 3)


# ── Alerts: Resend (the pipeline's own mail path) to Chris; log-only without a key ──
def alert(subject: str, body: str, *, dry: bool = False) -> bool:
    to = os.environ.get("MWNW_ALERT_TO", config.DEFAULT_ALERT_TO)
    key, sender = os.environ.get("RESEND_API_KEY"), os.environ.get("RESEND_FROM")
    log.error(f"ALERT: {subject}\n{body}")
    alerts = REPO / "output" / "mwnw" / "alerts.log"; alerts.parent.mkdir(parents=True, exist_ok=True)
    with alerts.open("a") as f: f.write(f"{datetime.now(CT):%Y-%m-%d %H:%M %Z} | {subject}\n{body}\n\n")
    if dry or os.environ.get("MWNW_NO_ALERT_EMAIL") or not (key and sender):
        return False
    try:
        r = requests.post("https://api.resend.com/emails", timeout=30,
                          headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                          json={"from": sender, "to": [to], "subject": f"[MWNW] {subject}",
                                "text": body})
        return r.status_code < 300
    except Exception as e:  # noqa: BLE001
        log.error(f"alert email failed: {e}"); return False
