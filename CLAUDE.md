# Arbeitsregeln für Claude in diesem Projekt

> Neu hier? Wenn noch kein Setup gelaufen ist: **`SETUP.md`** befolgen.
> Wenn noch kein Design existiert: **`DESIGN-INTERVIEW.md`** befolgen.

## Workflow-Reihenfolge
- **Video-Use first** für Schnitt/Transkription, **dann Hyperframes** für Motion Graphics.
- Outputs landen unter `projects/<name>/renders/`. Niemals in Repo-Root oder `raw/`.

## Kommunikation
- **Plan-Bestätigung auf Deutsch** (Plain Language) vor jedem Cut und vor jeder Composition. Erst nach User-OK rendern.
- Bei Korrekturen: gleiche Werkzeuge, gleicher Workflow — kein Raten.
- Ausnahme: Batch-Modus (siehe unten) hat EINEN Review am Ende statt Checkpoints pro Video.

## Brand / Design
- Das Design ist **nicht vorgegeben** — es wird mit dem Nutzer über `DESIGN-INTERVIEW.md` festgelegt und lebt unter `brand-guidelines/default/`.
- Keine Brand genannt → Fallback auf `brand-guidelines/default/`.
- Sagt der Nutzer *„Nutze die Brand `<name>`"* → alle Files in `brand-guidelines/<name>/` lesen (Farben, Typografie, Logo, Tone) und Schnitt-Stil, Farben, Overlays, Subtitles danach ausrichten.
- Weitere Marken (mehrere Kunden) als eigene Ordner via `npm run agency:onboard -- --brand <slug>` anlegen — **nicht** nach `default/`. Checkliste: `agency/ONBOARDING.md`. Jede Marke kann optional `brand-guidelines/<name>/metricool.json` (Zielkanal) und `brand-guidelines/<name>/broll/` (eigene Clips, gewinnt vor shared `assets/broll/`) haben.

## Cut-Standards (PFLICHT)
- Vor jedem Cut: Versprecher-Detection via `pack_transcripts.py --silence-threshold 0.4` + `ffmpeg silencedetect=noise=-30dB:duration=0.25`. Verdächtige Slices isoliert nochmal transkribieren.
- Padding nach Cut-Typ (Mid-sentence 100/80ms, Sentence-boundary 200/130-150ms, Video-Ende **600-700ms** nach **echtem** Word-End via Re-Transkription des letzten Wortes).
- Letztes Wort-End immer per Sub-Slice re-transkribieren — Full-Context markiert Sentence-Endwörter oft 1-2s zu spät.
- `edl.json` enthält Pflicht-Block `_padding_params` — keine Magic-Numbers.

## Render-Workflow (Checkpoint nach dem Cut)
Bevor HTMLs gebaut werden, **per `AskUserQuestion` fragen**, woher die Compositions kommen:
- **Direkt Hyperframes (Standard)** — Claude baut Storyboard + HTML-Compositions selbst, ausgerichtet an der Brand unter `brand-guidelines/<name|default>/`.
- **Claude Design (optional, fortgeschritten)** — der Nutzer gestaltet Compositions auf claude.ai und exportiert ein Bundle; Claude rendert nur. (Brand kommt dort aus dem hochgeladenen Skill — dann die Brand-Frage weglassen.)

Bei „Direkt Hyperframes" zusätzlich nach der Brand fragen (`default` / eigene Sub-Brand / keine).

## Claude-Design-Bundle (Anti-Patterns die Stunden kosten)
- **NICHT** `npx hyperframes preview` / `render` auf Bundles → StaticGuard rejected.
- **NICHT** `?render=1` Query-String → Bundle-Bootstrap nimmt anderen Mount-Pfad. Stattdessen `page.evaluateOnNewDocument(() => { window.__renderMode = true; ... })` **vor** `page.goto()`.
- **NICHT** `page.screencast()` → laggt, dropped frames.
- **PFLICHT vor jedem Bundle-Render:** Speaker-Video auf All-Intra-Keyframes konvertieren (`-g 1 -keyint_min 1 -sc_threshold 0`). Sonst snappt `video.currentTime = t` zum nächsten Keyframe → Speaker hängt.
- Erwarteter Pfad: `projects/<name>/assets/speaker.mp4`.
- Wait-Strategy: `waitUntil: "load"` (NICHT `networkidle0`). Dann auf `window.__renderReady === true` pollen.

## Compositions
- Multi-Scene: parallele Sub-Agents (eine Szene pro Agent) wenn unabhängig.
- Nach jedem Render Self-Eval per `timeline_view`-Pattern, bevor Preview gezeigt wird.
- **B-Roll ist Standard, nicht optional — Cadence ~alle 10s.** Wenn Clips in `assets/broll/` (oder der Brand-eigenen `broll/`) liegen, setzt die Composition-Stage etwa alle 10s einen Cutaway (`round(Dauer/10)`), je 2,5-3,5s, jeder Clip nur 1× pro Reel. Auswahl über `catalog.json` (Stichwort-Match), nicht Dateinamen. Nur eine **leere** Lib rechtfertigt 0 Cutaways.
- **Speaker-Zoom ist Standard.** Dezenter Ken-Burns-Push/-Pull (`scale` 1.0–1.08, `sine.inOut`) auf dem Talking-Head zwischen den Cutaways.

## Secrets / .env
- `.env` **nie committen** (steht in `.gitignore`).
- Projekt-Root-`.env` ist die Wahrheit; nach Änderungen nach `video-use/.env` syncen (`cp .env video-use/.env`).
- Keys nie im Chat-Output zeigen.

## Plattform
- Windows: Skill-Junctions per `New-Item -ItemType Junction`. Falls nicht möglich, per absolutem Pfad importieren.
- Windows: `PYTHONUTF8=1` vor jedem `uv run python ./video-use/helpers/...`.
- Windows: `grade: "auto"` in EDL ist broken — `grade: null` als Workaround.

---

## Batch-Workflow (mehrere Videos auf einmal)

Explizite **Ausnahme** zur „Plan-Bestätigung vor jedem Cut"-Regel. NUR aktiv, wenn der Nutzer explizit eine Batch startet (`batch_init.py --batch <name>`), nicht für Einzel-Videos.

### Wann
- Nutzer legt mehrere Videos in `raw/batches/<name>/` ab, oder sagt „batch" / „alle gleichzeitig".

### Single-Review statt Per-Video-Checkpoints
- Pro Video keine Plan-Bestätigung — Cut-Standards werden algorithmisch enforced (`prompts/edl_subagent.md`).
- **EIN Review am Ende** (Dashboard `batches/<name>/review.html`): Thumbnails + Captions + Schedule-Times. Nutzer OK't alles oder gibt Korrektur-Liste in Shorthand zurück.

### Phasen
1. **Drop:** MP4 nach `raw/batches/<name>/<seq>-<slug>.mp4`.
2. **Bootstrap:** `npm run batch:init -- --batch <name> --brand <brand>` (Scaffold + Whisper-Transkription).
3. **EDL:** 4 parallele Sub-Agents mit `video-use/helpers/prompts/edl_subagent.md` → je ein `edl.json`.
4. **Compose + Render:** 2-3 parallele Sub-Agents mit `composition_subagent.md`; rendern + Thumbnail.
5. **Caption + Schedule:** `npm run batch:caption` + `npm run batch:schedule`.
6. **Review:** `npm run batch:review -- --batch <name> --open`, dann ein `AskUserQuestion`.
6b. **Freigabe extern (optional):** `npm run freigabe:push -- --batch <name>` lädt pro Video einen Ordner ins OneDrive-synchronisierte SharePoint (`Freigabeprozess – Video/NNN_<linkedin-hook>/` mit `original – <kamera>.mov`, `final_vN__<titel>.mp4`, `captions__<titel>.txt`, `FREIGABE__<titel>.txt`). Kollegin (Juliana) trägt in der `FREIGABE…txt` Zeile 1 `FREIGEGEBEN`/`AENDERN` ein + Notizen. Rückmeldungen einlesen: `npm run freigabe:check` → klassifiziert nach Status; bei `AENDERN` Notizen in Korrektur-Shorthand übersetzen und re-cutten (Re-Push legt `final_v2__<titel>.mp4` an, überschreibt nie die `FREIGABE…txt`). Siehe `FREIGABEPROZESS.md`.
7. **Push (optional):** Metricool oder Postiz — **immer zuerst als Draft.**

Oder alles am Stück: `npm run batch:pipeline -- --batch <name>` (EDL→Cut→Compose→Caption→Schedule, stoppt vor dem Posten).

### Hard Rules im Batch-Modus
- Cut-Standards bleiben unverändert (Silencedetect + Re-Transkription + Padding pro Sub-Agent).
- Sub-Agent-Context-Isolation: jeder bekommt nur eigenes Video + Brand-Files.
- Caption-Generation darf nie Claims erfinden — nur Transkript + Brand-Proof-Points.
- **Erster Push immer als Draft** (Metricool `--draft` / Postiz `--draft-mode`). Posts landen als Drafts im Posting-Tool, nicht live.

### Korrektur-Shorthand (nach Review)
```
03: re-cut shorter           → Video durch Phase 3 (neue EDL)
07: linkedin 2026-05-28 09:15 → Manifest-Schedule updaten
12: skip tiktok              → posts.tiktok.enabled = false
05: caption neu              → nur Phase 5 für dieses Video
```
Parser: `npm run batch:apply -- --batch <name>` (Shorthand via stdin).

### Wichtige Helper / NPM-Shortcuts
```bash
npm run batch:init     -- --batch <name> --brand <brand>   # Scaffold + Transkription
npm run batch:next     -- --batch <name>                   # Was kommt jetzt?
npm run batch:status   -- --batch <name> -v                # Fortschritt
npm run batch:pipeline -- --batch <name>                   # EDL→…→Schedule am Stück
npm run batch:caption  -- --batch <name>
npm run batch:schedule -- --batch <name>
npm run batch:review   -- --batch <name> --open
npm run batch:apply    -- --batch <name>                   # Korrekturen (stdin)
npm run batch:cleanup  -- --batch <name> --apply           # Storage-Rotation (zeit-basiert)
# Externe Freigabe via SharePoint (Juliana):
npm run freigabe:push  -- --batch <name>                   # Videos → OneDrive-Freigabeordner (Phase 6b)
npm run freigabe:check                                     # Rückmeldungen einlesen (Status + Notizen)
# Posten (optional, draft-first):
npm run metricool:push:draft -- --batch <name>             # Metricool (gehostet)
npm run postiz:push:draft    -- --batch <name>             # Postiz (self-hosted)
# Einzel-Helfer:
npm run video:concat   -- --input-dir <ordner> --brand <slug>   # mehrere Clips → ein Reel
npm run podcast:split  -- --input <folge.mp4> --brand <slug>    # Podcast → mehrere Reels
npm run agency:onboard -- --brand <slug> --label "Name"          # neue Marke anlegen
```

### Beim Resume einer Batch (frische Session)
1. `npm run batch:next -- --batch <name>` ausführen.
2. Output sagt, was zu tun ist (Command oder Sub-Agent-Spawn mit Prompt-Pfad + seqs).
3. Bei agentic actions: parallele Agent-Calls mit dem genannten Prompt + seq pro Sub-Agent.
4. Nach jedem Schritt erneut `batch:next`.
