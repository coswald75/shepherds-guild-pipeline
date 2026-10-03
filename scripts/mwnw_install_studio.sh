#!/bin/bash
# Install the MWNW launch runner on the Mac Studio. Idempotent. Does NOT touch
# com.shepherdsguild.selfserve or any other existing job, and never sends email.
#   usage:  cd ~/shepherds-guild/pipeline && git fetch && git checkout mwnw-launch && bash scripts/mwnw_install_studio.sh
#   remove: bash scripts/mwnw_install_studio.sh --uninstall
set -euo pipefail
PIPE="$(cd "$(dirname "$0")/.." && pwd)"
LA="$HOME/Library/LaunchAgents"
JOBS="com.shepherdsguild.mwnw.tick com.shepherdsguild.mwnw.status"
if [ "${1:-}" = "--uninstall" ]; then
  for j in $JOBS; do launchctl bootout "gui/$(id -u)/$j" 2>/dev/null || true; rm -f "$LA/$j.plist"; done
  echo "MWNW jobs removed (venv .venv-mwnw left in place; rm -rf it if wanted)."; exit 0
fi
cd "$PIPE"
[ -f .env ] || { echo "missing $PIPE/.env"; exit 1; }
for k in ANTHROPIC_API_KEY ASSEMBLYAI_API_KEY VOYAGE_API_KEY SUPABASE_URL; do
  grep -q "^$k=" .env || { echo "missing $k in .env"; exit 1; }
done
TZNOW="$(date +%Z)"; case "$TZNOW" in CST|CDT) ;; *) echo "WARNING: Studio timezone is $TZNOW, not Central. The status job fires at 21:00 local; jobs set TZ=America/Chicago for the code itself.";; esac
PY="${PYTHON:-}"; [ -n "$PY" ] || for c in .venv/bin/python python3.12 python3; do command -v "$c" >/dev/null 2>&1 && { PY="$c"; break; }; done
[ -d .venv-mwnw ] || "$PY" -m venv .venv-mwnw
.venv-mwnw/bin/pip install -q --upgrade pip
.venv-mwnw/bin/pip install -q -r requirements.mwnw.txt
.venv-mwnw/bin/python -m playwright install chromium
.venv-mwnw/bin/yt-dlp --version; .venv-mwnw/bin/deno --version | head -1
.venv-mwnw/bin/python -c "import imageio_ffmpeg; print('ffmpeg', imageio_ffmpeg.get_ffmpeg_exe())"
mkdir -p logs "$LA"
for j in $JOBS; do
  sed "s#__PIPE__#$PIPE#g" "launchd/$j.plist" > "$LA/$j.plist"
  plutil -lint "$LA/$j.plist"
  launchctl bootout "gui/$(id -u)/$j" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$LA/$j.plist"
done
echo "Smoke test (dry, no DB writes):"
.venv-mwnw/bin/python -m regional.mwnw church cog --dry || true
launchctl list | grep mwnw
echo "Installed. Logs: $PIPE/logs/mwnw-*.log, status: $PIPE/output/mwnw/<week>/status.txt"
