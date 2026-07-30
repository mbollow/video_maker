#!/bin/bash
# Täglicher Archiv-Lauf (via LaunchAgent com.palstek.freigabe-archive):
# verschiebt Videos, die in GHL wirklich online sind, nach veröffentlicht/
# und räumt alte Versionen auf. Idempotent — nur Online-Gegangenes wird bewegt.
#
# launchd startet mit minimalem Environment; daher PATH explizit setzen.
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

REPO="/Users/marc/PycharmProjects/video_maker"
LOG="$HOME/Library/Logs/freigabe-archive.log"

cd "$REPO" || { echo "$(date '+%F %T') REPO nicht gefunden: $REPO" >>"$LOG"; exit 1; }

{
  echo "===== $(date '+%F %T')  freigabe:archive --execute ====="
  npm run freigabe:archive -- --execute
  echo "----- exit $? -----"
  echo
} >>"$LOG" 2>&1
