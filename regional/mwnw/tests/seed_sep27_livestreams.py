"""Dry-run fixture: seed Star and Roseburg Sep 27 with the livestream-cut test results
(/workspace/regional_offer/livestream_cut) so the review packet shows a real cut without
re-downloading (YouTube is bot-checking the box's datacenter IP). Box-only helper."""
import json, shutil
from pathlib import Path
from regional.mwnw.util import State
from regional.mwnw import media
LC = Path("/workspace/regional_offer/livestream_cut")
for key, name, yt in [("star", "center-church-star", "KyPBY-J9PW4"), ("clf", "covenant-life-roseburg", "WmCsnKm856Y")]:
    s = json.loads((LC / "state" / f"{key}-2026-09-27.json").read_text())
    st = State("2026-09-27", key)
    clip = st.dir / f"{name}-2026-09-27.mp3"; shutil.copy(LC / "clips" / f"{name}-2026-09-27.mp3", clip)
    st.data["source"] = dict(kind="youtube", yt_id=yt, url=f"https://www.youtube.com/watch?v={yt}", title=f"Sunday livestream {yt}", seeded_from="livestream_cut test")
    st.data["cut"] = dict(start_ms=s["start_ms"], end_ms=s["end_ms"], start=media.mmss(s["start_ms"]), end=media.mmss(s["end_ms"]),
                          first_sentence=s["first_sentence"], last_sentence=s["last_sentence"], clip=str(clip),
                          minutes=round((s["end_ms"] - s["start_ms"]) / 60000, 1), first_idx=None, last_idx=None)
    st.save(); print("seeded", key)
