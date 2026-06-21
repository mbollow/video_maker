# Video-Editing-Workflow — Schritt für Schritt

Referenz für Claude im Lauf einer Session. Detail-Erklärungen zu Commands/Padding-Werten/Bundle-Format-Quirks stehen in `SETUP.md` — diese Datei ist der **Workflow-Faden**.

---

## Edit-Workflow (mit Rohvideo)

### Schritt 1 — Projekt anlegen
```bash
mkdir -p projects/<name>/{assets,clips,transcripts,compositions,previews,renders}
```

### Schritt 2 — Rohvideo
Nutzer legt `raw/<name>/<datei>.mp4` ab. Claude prüft Existenz mit `ls raw/<name>/`.

### Schritt 3 — Transkription via Video-Use
```bash
uv run --project ./video-use python ./video-use/helpers/pack_transcripts.py \
  --edit-dir "projects/<name>" --silence-threshold 0.4
```

Output: `projects/<name>/transcripts/master.json` (Wort-Zeitstempel), `master.srt`.

### Schritt 4 — Versprecher-Detection (PFLICHT)
```bash
ffmpeg -hide_banner -nostats -i raw/<name>/<datei>.mp4 \
  -af "silencedetect=noise=-30dB:duration=0.25" -f null - 2>&1 | grep silence_
```

Vergleichen mit Wort-Zeitstempeln aus `master.json`:
- Wort-Marker mit unnatürlich langer Dauer (einsilbiges Wort >1.5s) → verdächtig.
- Gaps zwischen Wörtern, in denen Silence-Map nicht den ganzen Gap als still markiert → Rest = Stammer/Atmer/Versprecher.

Verdächtige Slices isoliert per Re-Scribe verifizieren (siehe SETUP.md → "Sub-Slice für Versprecher-Verifikation").

### Schritt 5 — Cut-Plan auf Deutsch
Claude legt Plan vor (Plain Language):
- Welche Phrasen rein, welche raus.
- Versprecher-Findings je Range.
- Gewähltes Padding je Range (Mid-sentence 100/80ms, Boundary 200/140ms, **Video-Ende 600-700ms nach echtem Word-End via Re-Scribe**).

Erst nach User-OK rendern.

### Schritt 6 — Letzten Wort-End re-scriben (PFLICHT)
Full-Context Scribe markiert Sentence-Endwörter oft 1-2s zu spät (rechnet Atem-Decay als Word-Tail). Pflicht:
1. Sub-Slice `[full_context.start - 1, full_context.end + 1]` extrahieren.
2. Per Scribe re-transkribieren.
3. **Echten** Word-End nehmen, NICHT den aus Full-Context.
4. Range-End = echter Word-End + **600-700ms**.

### Schritt 7 — EDL bauen + Cut rendern
`projects/<name>/edl.json` muss `_padding_params`-Block enthalten (siehe SETUP.md "EDL-Konvention"). Dann:

```bash
uv run --project ./video-use python ./video-use/helpers/render.py \
  projects/<name>/edl.json -o projects/<name>/clips/edited.mp4
```

### Schritt 8 — Workflow-Branch-Checkpoint (PFLICHT, via AskUserQuestion)

**Frage 1: HTML-Quelle**
- **Claude Design (claude.ai)** → Claude exportiert NUR `projects/<name>/output_transcript.md` + `.json`. Kein anderer Output. Aktiv aufs Bundle warten.
- **Direkt Hyperframes** → Claude baut Storyboard + HTML-Compositions selbst.

**Frage 2 (nur bei Direkt Hyperframes): Brand**
- `brand-guidelines/default/` / eigene Sub-Brand / keine Brand.

### Schritt 9a — Direkt Hyperframes
1. Storyboard auf Deutsch (HTML mit Beats, Anchor-Wörtern, Animation-Typen) → User-OK abwarten.
2. Compositions in `projects/<name>/compositions/` bauen (Multi-Scene: parallele Sub-Agents wo unabhängig).
3. `npx hyperframes preview` → Studio auf `localhost:3002`. Iterieren auf Feedback.
4. `npx hyperframes render` → `projects/<name>/renders/final.mp4`.

### Schritt 9b — Claude-Design-Bundle
1. User wirft HTML in den Projekt-Root.
2. Bundle entpacken (autodetect: einziges `*.html` mit `<script type="__bundler/manifest">`). Files nach `projects/<name>/_bundle_assets/<uuid>.<ext>`.
3. **Format-Check vor Patch:** `_bundle_assets/*.jsx` → Format B (3 Patches nötig). Extracted JS mit `var HyperShader` → Format A (kein Patch).
4. **Format B Patches:**
   - App component: `{!renderMode && <TweaksPanel>...}`, Stage-UI ausblenden via `window.__renderMode`.
   - Stage: kein rAF im Render-Mode, `window.__setStageTime(t)` exponieren.
   - Video components: NIEMALS `play()`/`pause()`, nur `video.currentTime = t`.
5. **Speaker-Video Keyframe-Conversion (PFLICHT):**
   ```bash
   ffmpeg -i projects/<name>/clips/edited.mp4 \
     -c:v libx264 -preset fast -crf 18 \
     -g 1 -keyint_min 1 -sc_threshold 0 \
     -pix_fmt yuv420p -r 30 \
     -c:a aac -b:a 192k \
     projects/<name>/assets/speaker.mp4
   ```
6. Wort-Sync gegen `transcripts/master.json` — claude.ai trifft Anchors oft 0.3-1s daneben. In Bundle-Transcript-Asset korrigieren.
7. Tiny dev-server auf `localhost:3030` (mtime-Polling, Reload-Inject, Range-Requests fürs Video) für Asset-Edit-Iterationen. Wenn Bundle 1:1 OK → direkt rendern, kein Preview-Pflichtzwang.
8. Frame-by-frame Render: `chrome-headless-shell` aus `~/.cache/hyperframes/chrome/` + Puppeteer + ffmpeg. **Render-Mode-Globals VOR `page.goto()`** via `evaluateOnNewDocument`, **KEIN `?render=1`**. `waitUntil: "load"`, dann auf `window.__renderReady` pollen.

### Schritt 10 — Self-Eval
`timeline_view`-Pattern: prüfen ob Animation-Beats zu Audio-Beats passen. Erst dann Preview zeigen.

### Schritt 11 — Iteration / Final
Default 1080p (`projects/<name>/renders/final.mp4`). Bei OK → 4K (`final-4k.mp4`, `RENDER_QUALITY=4k`-Default oder Viewport mit DPR 2).

---

## Pure-Animation-Workflow (ohne Rohvideo)

Identisch ab Schritt 8 (Workflow-Branch-Checkpoint), nur ohne Schritte 2-7. Nutzer beschreibt das Video → Claude erzeugt Storyboard → baut Compositions → rendert.

---

## Batch-Workflow (10-50 Videos auf einmal)

Vollständige Doku in **CLAUDE.md → "Batch-Workflow"**. Kurzfassung:

1. Drop alle MP4 in `raw/batches/<batch-name>/<seq>-<slug>.mp4`.
2. `python helpers/batch_init.py --batch <name>` → manifest + Whisper-Transkription (Volumen-Primary, ~$9/Monat statt $330 Scribe).
3. Claude main-session spawnt parallele Sub-Agents (Phase 3 EDL: 4 parallel; Phase 4 Compose+Render: 2-3 parallel) — Cut-Standards wie im Per-Video-Workflow, nur algorithmisch enforced statt per Plan-Bestätigung.
4. `python helpers/caption_gen.py --batch <name>` + `schedule_plan.py --batch <name>` → Captions + Schedule pro Plattform.
5. `python helpers/review_dashboard.py --batch <name> --open` → Browser zeigt alle Videos + Captions + Times.
6. **EIN Review-Checkpoint:** User OK'd alles oder gibt Shorthand-Korrekturen zurück.
7. `python helpers/postiz_push.py --batch <name> --draft-mode` (Erstvalidierung) → bei OK ohne `--draft-mode` live.

**Wichtig:** Per-Video-Plan-Bestätigung wird im Batch-Modus **bewusst übersprungen** (sonst wären 50 Checkpoints/Tag unproduktiv). Cut-Standards bleiben non-negotiable, aber Sub-Agents enforcen sie ohne User-Interaction.
