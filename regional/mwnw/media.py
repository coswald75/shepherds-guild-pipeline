"""Audio: download (yt-dlp), transcribe (AssemblyAI, same config as weekly_ingest), and for
full-service livestreams find the sermon and cut it out (two-stage: Haiku coarse on ~45 s
paragraphs, Sonnet fine on sentence windows; v2 prompts from the Sep 27 cut test)."""
from __future__ import annotations
import glob, json, os, shutil, subprocess, time
from pathlib import Path
import anthropic, assemblyai as aai
from .util import log, retry, USAGE

HAIKU = "claude-haiku-4-5-20251001"
SONNET = "claude-sonnet-4-5-20250929"
_cl = None
def cl():
    global _cl
    _cl = _cl or anthropic.Anthropic()
    return _cl


def ffmpeg_bin() -> str:
    exe = shutil.which("ffmpeg")
    if exe: return exe
    try:
        import imageio_ffmpeg  # the Studio has no Homebrew; this wheel ships a static ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:
        raise RuntimeError("no ffmpeg on PATH and imageio-ffmpeg not installed") from e


def mmss(ms: float) -> str:
    s = int(ms // 1000); return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


@retry(tries=4, wait=60, what="yt-dlp download")
def download_youtube(video_id: str, dest_stem: Path) -> Path:
    have = glob.glob(f"{dest_stem}.*")
    have = [h for h in have if not h.endswith((".part", ".ytdl", ".json"))]
    if have: return Path(have[0])
    r = subprocess.run(["yt-dlp", "-q", "--no-progress", "--no-warnings", "--retries", "10", "--fragment-retries", "10",
                        "--extractor-retries", "3", "-f", "bestaudio", "-o", f"{dest_stem}.%(ext)s",
                        f"https://www.youtube.com/watch?v={video_id}"], capture_output=True, text=True, timeout=1800)
    if r.returncode: raise RuntimeError("yt-dlp: " + r.stderr.strip()[-400:])
    return Path([h for h in glob.glob(f"{dest_stem}.*") if not h.endswith((".part", ".ytdl"))][0])


@retry(tries=3, wait=60, what="AssemblyAI")
def transcribe(audio: str, out_json: Path) -> dict:
    """audio = local path or public URL. Caches sentence-level JSON."""
    if out_json.exists(): return json.loads(out_json.read_text())
    aai.settings.api_key = os.environ["ASSEMBLYAI_API_KEY"]
    t = aai.Transcriber().transcribe(audio, aai.TranscriptionConfig(speaker_labels=False, punctuate=True, format_text=True))
    if t.status == aai.TranscriptStatus.error: raise RuntimeError(f"AssemblyAI: {t.error}")
    d = {"id": t.id, "duration": t.audio_duration, "sentences": [{"s": x.start, "e": x.end, "t": x.text} for x in t.get_sentences()]}
    USAGE["aai_seconds"] += t.audio_duration or 0
    out_json.write_text(json.dumps(d)); return d


def _ask(model, prompt, usage, tag, max_tokens=700):
    last = None
    for a in range(4):
        try:
            m = cl().messages.create(model=model, max_tokens=max_tokens, messages=[{"role": "user", "content": prompt}])
            usage.append({"tag": tag, "model": model, "in": m.usage.input_tokens, "out": m.usage.output_tokens})
            t = m.content[0].text; return json.loads(t[t.find("{"):t.rfind("}") + 1])
        except Exception as e:  # noqa: BLE001
            last = e; log.warning(f"{tag} retry {a + 1}: {str(e)[:200]}"); time.sleep(5 * (a + 1))
    raise RuntimeError(f"{tag}: model failed: {last}")


RULES = ("THE SERMON = the main preaching message. INCLUDE the reading of the sermon's own Scripture text (even if someone other "
         "than the preacher reads it immediately before he starts) and any short prayer the preacher prays at the start of the sermon. "
         "EXCLUDE songs, announcements, welcome, offering, Lord's Supper/communion, response songs, the preacher's CLOSING prayer "
         "after the sermon, and the benediction.")


def find_bounds(S: list[dict]) -> dict:
    """Returns {start_ms,end_ms,first_idx,last_idx,first_sentence,last_sentence,preacher,coarse,fine,usage}."""
    usage = []
    paras, cur, st = [], [], None
    for i, x in enumerate(S):
        if st is None: st = i
        cur.append(x["t"])
        if x["e"] - S[st]["s"] > 45000: paras.append((st, i, " ".join(cur))); cur = []; st = None
    if cur: paras.append((st, len(S) - 1, " ".join(cur)))
    txt = "\n".join(f"[{k}] ({mmss(S[a]['s'])}) {p}" for k, (a, b, p) in enumerate(paras))
    c = _ask(HAIKU, "Below is the transcript of a full church worship service livestream, split into numbered ~45-second paragraphs.\n" + RULES +
             '\nReturn ONLY JSON: {"start":<paragraph where the sermon begins>,"end":<paragraph where the sermon ends>,"preacher":<name if stated, else null>,'
             '"title":<sermon title if stated, else null>,"text":<primary Scripture passage if stated, else null>,'
             '"after_sermon":"<what follows the sermon>","notes":"<short>"}\n\n' + txt, usage, "coarse")
    def window(a, b): return "\n".join(f"[{i}] ({mmss(S[i]['s'])}) {S[i]['t']}" for i in range(max(0, a), min(len(S), b)))
    sa = paras[max(0, c["start"] - 6)][0]; sb = paras[min(len(paras) - 1, c["start"] + 3)][1] + 1
    f1 = _ask(SONNET, "These numbered sentences come from a church service livestream transcript, around where the sermon BEGINS.\n" + RULES +
              "\nPick the index of the FIRST sentence that belongs to the sermon. CAREFUL: many preachers open with a story, illustration, or recap BEFORE "
              "asking people to turn to the text; that opening is part of the sermon. So the sermon starts at the first sentence of the preacher's message "
              "right after the previous service element ends (announcements, welcome, song, prayer by someone else, greetings). If the sermon text is read "
              'aloud just before the preacher begins (by him or a reader), start at that reading instead. Return ONLY JSON: {"first":<index>,"why":"<short>"}\n\n'
              + window(sa, sb), usage, "fine_start", 300)
    ea = paras[max(0, c["end"] - 6)][0]; eb = paras[min(len(paras) - 1, c["end"] + 3)][1] + 1
    f2 = _ask(SONNET, "These numbered sentences come from a church service livestream transcript, around where the sermon ENDS.\n" + RULES +
              "\nPick the index of the LAST sentence of the sermon itself, i.e. the sentence right BEFORE the closing prayer begins (e.g. right before "
              "'Let's pray'), or before a song/communion/benediction if he does not pray. The closing prayer, its 'Amen', and anything after are NOT part "
              'of the sermon. Return ONLY JSON: {"last":<index>,"after":"<what comes next>","why":"<short>"}\n\n' + window(ea, eb), usage, "fine_end", 300)
    fi, la = int(f1["first"]), int(f2["last"])
    if not (0 <= fi < la < len(S)): raise RuntimeError(f"bad bounds first={fi} last={la} n={len(S)}")
    mins = (S[la]["e"] - S[fi]["s"]) / 60000
    if not (12 <= mins <= 95): raise RuntimeError(f"implausible sermon length {mins:.0f} min (first={fi}, last={la})")
    return dict(start_ms=max(0, S[fi]["s"] - 500), end_ms=S[la]["e"] + 1000, first_idx=fi, last_idx=la,
                first_sentence=S[fi]["t"], last_sentence=S[la]["t"], preacher=c.get("preacher"), title=c.get("title"),
                text=c.get("text"), coarse=c, fine={"start": f1, "end": f2}, usage=usage, minutes=round(mins, 1))


def cut_mp3(src: Path, start_ms: int, end_ms: int, out: Path, title: str) -> Path:
    r = subprocess.run([ffmpeg_bin(), "-v", "error", "-y", "-ss", str(start_ms / 1000), "-to", str(end_ms / 1000), "-i", str(src),
                        "-ac", "1", "-ar", "44100", "-c:a", "libmp3lame", "-b:a", "48k", "-metadata", f"title={title}", str(out)],
                       capture_output=True, text=True, timeout=900)
    if r.returncode or not out.exists(): raise RuntimeError("ffmpeg: " + r.stderr[-300:])
    return out


def identify_preacher(S: list[dict], hints: str, usage: list) -> dict:
    """Cheap Haiku read of the opening/closing minutes: who preached, title, text. Guests happen."""
    head = " ".join(x["t"] for x in S[:80])[:6000]; tail = " ".join(x["t"] for x in S[-25:])[:1500]
    return _ask(HAIKU, "From this sermon audio transcript (opening and closing) plus the feed metadata, identify the preacher. "
                "Only name someone if the transcript or metadata states it; do not guess. Return ONLY JSON "
                '{"preacher":<full name or null>,"basis":"<where you saw it>","guest":<true if introduced as a guest/visiting preacher>,'
                '"title":<sermon title if stated else null>,"text":<primary passage if stated else null>}\n\n'
                f"METADATA:\n{hints}\n\nOPENING:\n{head}\n\nCLOSING:\n{tail}", usage, "identify", 300)
