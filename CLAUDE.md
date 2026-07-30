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

## Reel-Standard: Hook / Overlay / Untertitel / Logo (PFLICHT)
Operativ verankert in `video-use/helpers/prompts/composition_subagent.md`, `composition_templates/talking-head-reel.html`, `render.py:build_master_srt`.
- **Hook (Pflicht, nie optional):** ab **Frame 0** sichtbar (CSS `opacity:1`, KEIN Entrance-Tween — sonst ist Frame 0 leer), bleibt **~3 s** (Exit ~2,95 s, hidden 3,35 s). Auf **Vollton-Overlay `#281D67` @ 50 %** (`rgba(40,29,103,0.5)`, KEIN Verlauf). Linksbündig, **ohne Eyebrow/Kicker**. Schrift **Montserrat, fett**, große & **pro Zeile variierende** Größen (z. B. 64/96/108 px); Mix aus weiß / teal / **weiß auf hellblauer Marker-Box** (`.hl-mark`, bg `#4ebbc2`) auf der Punchline. Wording knackig/leicht provokant; Paraphrase der gesprochenen Eröffnung erlaubt.
- **Volluntertitel (Pflicht):** jedes gesprochene Wort im unteren Drittel, `font-size: 48px`, **auch unter** Anchors/List-Cards (mittig vs. unten → keine Kollision). Einzige Hide-Window = Hook-Fenster `[[0, 3.3]]`. Cues aus `master.srt`, das in **3–4-Wort-Gruppen** baut (Umbruch nur an Satzende `.?!`).
- **Logo immer oben rechts** (`top:70px; right:70px`) — nie unten/mittig (kollidiert mit Untertiteln).
- **Transkription via Scribe** (`batch:init … --engine scribe`) — Whisper verschluckt Wörter.
- **Nach JEDEM Render:** `ffprobe`-Check (Audiospur **aac** vorhanden + Dauer plausibel) VOR Deploy — ein degradierter Software-Render kam mal ohne Tonspur / als Standbild raus.

## Freigabe / Versionierung
- **Nach jeder Änderung an einem Video automatisch als nächste Version** (`final_vN+1`) per `freigabe:push` in den Freigabe-Ordner schieben — nicht erst auf Rückfrage. Der Nutzer schaut **ausschließlich** im Freigabe-Ordner, **nie** in `projects/<…>/renders/`.

## Social-Veröffentlichung — GoHighLevel (GHL, im Test)
Helper `video-use/helpers/ghl_*.py`, `npm run ghl:discover|plan|push|push:draft`. Postiz/Metricool bleiben parallel (evtl. späterer Rückbau).
- **LinkedIn:** immer Julianas **persönliches Profil**, NIE die Palstek Company Page.
- **Captions je Plattform:** LinkedIn = formeller Text; **Instagram + Facebook = Instagram-Text** (beide Meta).
- **Captions-Wahrheit = die `captions*.txt` im Freigabe-Ordner** (handgepflegt nach Review), NICHT das Manifest. `ghl_plan.py` liest den Text direkt aus dem Ordner (neueste `captions_vN`). **PFLICHT & automatisch:** vor jedem GHL-Upload spiegelt `ghl_sync_captions.py` (`npm run ghl:sync-captions`) die neueste Ordner-Caption ins Manifest (läuft als erster Schritt in `ghl_plan.py`) — so bleibt das Manifest (zentrales Record, Web-Sync) mit dem handgepflegten Text konsistent. Manifest-Captions nie als Quelle behandeln.
- **Scheduling:** Default **10:00 Europe/Berlin**, nächste freie **Mo/Mi/Fr**; Belegung **pro Kanal/Zeitfenster** (Cross-Posting zur selben Zeit ok, ein Kanal nie doppelt). **Draft-first.**
- **Doppel-Upload-Schutz:** git-getrackter Ledger `ghl_publish_log.json` (SHA-256 pro Video × Kanal). Media-Name in GHL = SharePoint-Ordnername. Autor via `GHL_USER_ID` (nicht der auto-geerntete Alt-Post-Ersteller). Secrets in `.env`: `GHL_PRIVATE_INTEGRATION_TOKEN`, `GHL_LOCATION_ID`, `GHL_USER_ID`.

## Brand-/Inhalts-Konventionen (Palstek / `default`)
- **Du-Ansprache** konsequent (nie „Sie").
- **Buchungs-/CTA-URL:** `https://palstek-gmbh.de/termin` (End-Card + Captions).
- **Bestehende Projekte/Videos/Renders nie löschen oder überschreiben** — immer neuer Batch-/Versionsname.
- **Kernaussagen on-screen** farblich einblenden (Anchors/List-Cards), nicht nur als Untertitel.
- **Standard-Eyebrow/Kicker:** „Wirksamer Tipp für Führungskräfte" (nicht „Führung in KMU"). End-Card greift das Video-Thema als Frage über dem Buchungs-CTA auf.
- **Render `-q standard`** (mobile-first Publikum), nicht `-q high`.
- **Denoise via DeepFilterNet** (`helpers/denoise.py`), nicht `afftdn`; isolierte venv.

## Bild-Posts (Single-Image, neben den Video-Reels)
Eigene Pipeline für statische Ein-Bild-Posts (echtes Juliana-Foto + Hook/Spruch-Overlay). Spiegelt den Batch-Workflow.
- **Phasen:** `npm run bild:hooks -- --batch <name> [--count N] [--thema "…"] [--append] [--provokativ]` → kuratierbare `image-posts/<name>/hooks.txt` (Hook **und** Spruch; `typ/text/thema/status`-Felder, nur `status: ja` wird gebaut) → `npm run bild:build -- --batch <name>` (Foto-Match über Tags, KI-Layout+Captions, Render) → **Auto-Push** in den Freigabe-Ordner.
- **Freigabe = Pflicht & automatisch:** `bild:build` pusht am Ende selbst in `FREIGABE_BILDER_DIR` (`--no-push` nur als Notausgang). Wie bei Videos schaut der Nutzer/Juliana **ausschließlich** im Freigabe-Ordner, **nie** in `image-posts/<…>/renders/`. Rückmeldungen: `npm run bild:freigabe:check`. Re-Build → `bild_vN+1` daneben, `FREIGABE.txt` nie anfassen.
- **Visueller Standard:** Vorlage `composition_templates/static-post.html`, 1080×1350, **Teal-Overlay `#4ebbc2` @ 35 %** (abweichend vom Reel-Hook `#281d67@50%`), Logo oben rechts, Montserrat fett, Hook-Punchline in dunkler `#281d67`-Marker-Box (Spruch zentriert ohne Marker), **keine CTA aufs Bild** (CTA nur in Caption). Render via `render_image_post.cjs` (puppeteer-core + Chrome).
- **Foto-Quelle:** read-only OneDrive (`GF_FOTOS_DIR`, `|`-getrennte Liste: echtes Shooting + `Juliana_Bilder_KI`), hart schreibgeschützt via `deny`-Regel auf `…/Marketing/Bilder/**`. Tags in `brand-guidelines/<brand>/gf-fotos/catalog.json` (Match über Stichwörter, nicht Dateinamen). Bilder (Fotos + Renders) sind git-ignoriert; nur `catalog.json`/README werden versioniert.
- **Tagging ist Pflicht, sofort:** Neue KI-Juliana-Bilder werden **direkt nach dem Ablegen** im `catalog.json` getaggt (visuell sichten, Vokabular einhalten, `quelle: "ki"`). Ein ungetaggtes Bild ist für `match_photo` unsichtbar — es liegt im Ordner, wird aber nie gewählt. `load_catalog` warnt beim Build über Dateien ohne Eintrag. Umgekehrt: **Einträge ohne Datei** (vom Nutzer aussortierte Bilder) werden zur Laufzeit übersprungen, nicht als Fehler behandelt — der Katalog-Eintrag darf stehen bleiben, nichts muss nachgepflegt werden.
- **Bildquellen:** `--source juliana|stock` (Stock via Pexels, `PEXELS_API_KEY`). Pro Post in `hooks.txt` überschreibbar: `bild: stock|juliana`. **Faustregel:** provokante *Problem*-Hooks → Stock (Juliana wirkt sonst, als „hätte sie das Problem"); Vorstellungs-/Erfolgs-Posts → Juliana. Feintuning-Felder: `highlight: Wort1, Wort2` (in `#4ebbc2`), `fontscale: 1.15`, `stock_query: <engl. Suche>` (pinnt das Motiv). Text-Edits behalten das Bild (`--new-image` erzwingt Neuwahl); Captions bleiben (`--regen-captions` erzwingt neu).
- **„hellblau"/„türkis" = immer `#4ebbc2`** (Marken-Akzent); dunkles Blau-Lila = `#281d67`.
- **Später:** `gf-ki/` (KI-Juliana-Bilder + automatische KI-Kennzeichnung in Caption).

## Testimonial-Videos (Langform für die Website)
Kunden-Interview (Zoom/Teams) → **~vollständiges 16:9-Video zum Einbetten**, NICHT auf 30/60 s gekürzt. Details: **`TESTIMONIAL.md`**. Helper `testimonial_*.py`, Template `composition_templates/testimonial-card.html`, Ablauf `npm run testimonial:init|plan|build`.
- **Zwei Regeln (teuer gelernt, nicht aufweichen):** **(1) Video sanft schneiden** — Füllwörter und Denkpausen bleiben im Ton; nur Pausen > `max_pause_s` (1,2 s) und inhaltlich Nötiges (Zwischenrufe, interne Absprachen) raus. Jeder Schnitt im Talking-Head ist ein sichtbarer Sprung und kostet bei Langform mehr, als die Straffung bringt. **(2) Untertitel sauber ausformulieren** — ohne Füllwörter/Wiederholungen, richtige Grammatik + Schreibweisen; der Ton bleibt unangetastet.
- **Wirkt ein Schnitt als Sprung:** NICHT die globale Schwelle anheben, sondern `schnitt.ausnahmen` für genau diesen Block setzen.
- **Quelle:** die saubere Cloud-/Meeting-Aufzeichnung schlägt den Bildschirm-Mitschnitt (Teams-UI). Bei mehreren Rohdateien Anfang **und** Ende beider kurz transkribieren — unterschiedliche Längen heißen nicht, dass eine unvollständig ist (Vorgespräch).
- **Bild:** Galerie ist ~3,56:1 → nicht formatfüllend croppbar. Sprecher-Band freistellen, mittig auf Creme `#f8f6f2`, Logo oben rechts, Untertitel `#281d67` darunter. Folien + Antworten teilen den Rahmen → harte Schnitte wirken ruhig, keine Crossfades.
- **Anrede:** Gast **siezen**, Publikum **duzen** (Outro-CTA). Kein Vorname in der Anrede — nur als Namensnennung auf der Intro-Folie.
- **Freigabe:** `testimonial:build` pusht selbst als `final_vN+1` (`--no-push` = Notausgang). Versionen nie überschreiben.

## Karussell-Posts (Multi-Slide, optisch eigenständig)
Mehrteilige Bildstrecken (Start → n Innen-Slides → Ende), **bewusst anders** als die Ein-Bild-Posts. Spiegelt den Bild-Post-Workflow (Entwurf → kuratieren → bauen → Auto-Push). Helper `karussell_*.py`, Templates `composition_templates/carousel-{start,inner,end}.html`, Render via `render_image_post.cjs`.
- **Modell:** ein Karussell = ein `--batch <name>` (= ein Freigabe-Ordner). Arbeitsordner `image-carousels/<name>/` (`outline.txt`, `renders/`, `manifest.json`).
- **Phasen:** `npm run karussell:outline -- --batch <name> --thema "…" [--slides N] [--provokativ]` → editierbare `outline.txt` (Voll-Entwurf: Start-Hook, 5–6 Innen-Slides mit Titel/Icon/Fließtext, Ende-Statement+CTA — Erzählbogen Problem→Kosten→Reframe→…→Frage). Kuratieren (streichen/umschreiben/Reihenfolge über `[NN]`), dann `npm run karussell:build -- --batch <name>` (Foto-Match Start/Ende, KI-Zeilensplit+Captions, Render aller Slides, **Auto-Push**).
- **Freigabe = Pflicht & automatisch:** `karussell:build` pusht selbst (`--no-push` nur Notausgang) nach `FREIGABE_BILDER_DIR` — **ein Ordner pro Karussell** `NNN_<thema>/` mit allen Slides im Versions-Unterordner `v1/` (`01_start.png … 99_ende.png`), `captions__…txt`, `FREIGABE__…txt`. Re-Build → `v2/` daneben; captions/FREIGABE einmalig, nie überschrieben. Rückmeldungen wie bei Bildern: `npm run bild:freigabe:check`. Nutzer/Juliana schauen **nur** im Freigabe-Ordner.
- **Visueller Standard (verbindlich, an handgemachten Referenzen ausgerichtet):** 1080×1350, Hintergrund **Creme `#f8f6f2`** (nicht reinweiß), Montserrat, Akzent-Teal `#4ebbc2`, Icon-Teal `#6edbd7`, dunkel `#281d67`. Thema-**Eyebrow** oben, über alle Slides **identisch**. **Start:** offizielle Zweifarb-Logo-Wortmarke zentriert (`brand-guidelines/<brand>/assets/logo-color.png` = Navy-Knoten-„P" + „alstek" + Teal-Tagline; kommt aus dem read-only Marketing-Logo-Ordner, Fallback = aus weißem Logo erzeugtes `logo-horizontal-dark.png`) + Foto unten + Marker-Box-Hook. **Innen:** Teal-Badge-Logo (weiß) oben links, große blasse Nummer, **Lucide-Line-Icon** oben rechts, Titel + Fließtext-Absätze. **Ende:** Statement zentriert + Foto unten links + handschriftlicher CTA (Caveat) + Pfeil.
- **Icons:** vendored Lucide-Subset unter `video-use/helpers/karussell_assets/icons/` (ISC), Match über `icon-catalog.json` (Stichwort→Icon) bzw. `icon:`-Feld im `outline.txt`. Neue Motive per `curl …/lucide-static@latest/icons/<name>.svg`.
- **„hellblau"/„türkis" = `#4ebbc2`**, dunkles Blau-Lila = `#281d67` (wie bei Bild-Posts).

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

### Single-Freigabe statt Per-Video-Checkpoints
- Pro Video keine Plan-Bestätigung — Cut-Standards werden algorithmisch enforced (`prompts/edl_subagent.md`).
- **EIN Feedback-Kanal für alle:** Am Ende JEDES Batches werden die Videos in den Freigabe-Ordner kopiert (`freigabe:push`, Pflicht-Endschritt). Feedback — egal ob von der Kollegin (Juliana) ODER vom Nutzer selbst — läuft **ausschließlich** über die jeweilige `FREIGABE…txt` in diesem Ordner. Keine zweiten Wege (kein separates Shorthand-Review-Dashboard als Eingang). Rückmeldungen einlesen mit `freigabe:check`, Korrekturen abarbeiten, neue Version re-pushen.

### Phasen
1. **Drop:** MP4 nach `raw/batches/<name>/<seq>-<slug>.mp4`.
2. **Bootstrap:** `npm run batch:init -- --batch <name> --brand <brand>` (Scaffold + Whisper-Transkription).
3. **EDL:** 4 parallele Sub-Agents mit `video-use/helpers/prompts/edl_subagent.md` → je ein `edl.json`.
4. **Compose + Render:** 2-3 parallele Sub-Agents mit `composition_subagent.md`; rendern + Thumbnail.
5. **Caption + Schedule:** `npm run batch:caption` + `npm run batch:schedule`.
6. **Freigabe (Pflicht-Endschritt jedes Batches):** `npm run freigabe:push -- --batch <name>` kopiert pro Video einen Ordner ins OneDrive-synchronisierte SharePoint (`Freigabeprozess – Video/NNN_<linkedin-hook>/` mit `original – <kamera>.mov`, `final_vN__<titel>.mp4`, `captions__<titel>.txt`, `FREIGABE__<titel>.txt`). **Das ist der Review-Schritt** — kein separates `AskUserQuestion`/Dashboard mehr als Eingang. Nutzer **und** Juliana geben Feedback in der `FREIGABE…txt` (Zeile 1 `FREIGEGEBEN`/`AENDERN` + Notizen). Einlesen: `npm run freigabe:check` → bei `AENDERN` Notizen in Korrektur-Shorthand übersetzen, re-cutten, re-pushen (legt `final_vN+1__<titel>.mp4` daneben an, fasst die `FREIGABE…txt` nie an). Siehe `FREIGABEPROZESS.md`. (`batch:review`/`review.html` ist nur noch ein optionaler Voransicht-Helfer, kein Feedback-Eingang.)
7. **Push (optional, erst nach `FREIGEGEBEN`):** Metricool oder Postiz — **immer zuerst als Draft.**

Oder alles am Stück: `npm run batch:pipeline -- --batch <name>` (EDL→Cut→Compose→Caption→Schedule→**Freigabe-Push**, stoppt vor dem Social-Posten).

### Hard Rules im Batch-Modus
- Cut-Standards bleiben unverändert (Silencedetect + Re-Transkription + Padding pro Sub-Agent).
- Sub-Agent-Context-Isolation: jeder bekommt nur eigenes Video + Brand-Files.
- Caption-Generation darf nie Claims erfinden — nur Transkript + Brand-Proof-Points.
- **Erster Push immer als Draft** (Metricool `--draft` / Postiz `--draft-mode`). Posts landen als Drafts im Posting-Tool, nicht live.

### Korrektur-Shorthand (interne Notation für Feedback aus `freigabe:check`)
Feedback kommt als Freitext in den `FREIGABE…txt`; beim Einlesen via `freigabe:check` in dieses Shorthand übersetzen und abarbeiten:
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
# Testimonial (Langform-Interview -> Website-Embed, siehe TESTIMONIAL.md):
npm run testimonial:init  -- --projekt <name> --quelle <datei>   # Scaffold + Transkript + interview.txt
npm run testimonial:plan  -- --projekt <name>                    # Schnitt + Untertitel pruefen
npm run testimonial:build -- --projekt <name>                    # rendern + Freigabe-Push
```

### Beim Resume einer Batch (frische Session)
1. `npm run batch:next -- --batch <name>` ausführen.
2. Output sagt, was zu tun ist (Command oder Sub-Agent-Spawn mit Prompt-Pfad + seqs).
3. Bei agentic actions: parallele Agent-Calls mit dem genannten Prompt + seq pro Sub-Agent.
4. Nach jedem Schritt erneut `batch:next`.
