# Projekt-Status — VideoMaker (Palstek)

> Wiedereinstiegs-Anker für (frische) Claude-Sessions. Stand: 2026-06-24.
> Arbeitsregeln stehen in `CLAUDE.md`; dieser File fasst den *aktuellen Stand* zusammen.

## Was das ist
Lokale Pipeline, die aus Roh-Videos fertige Social-Reels macht (Schnitt → Untertitel/Motion-Graphics → Render → Captions → Schedule). Gesteuert über Claude Code. Brand: **Palstek** (Juliana Wiechert, Führung/Mitarbeiterbindung in KMU).

## Einrichtung — fertig ✅
- `.env`: ANTHROPIC / OPENAI / ELEVENLABS Keys (nach `video-use/.env` gesynct)
- **ffmpeg mit libzimg** (`zscale`) gebaut — nötig für HLG→SDR-Tonemapping
- Permissions: `.claude/settings.json` (Bash/Write/Edit erlaubt; `rm`/`git push` gesperrt, `git commit` = ask)
- Brand `brand-guidelines/default/`: Du-Form, Akzent `#4ebbc2`, Sekundär `#281d67`, Korbin-Font, Logo `assets/logo-horizontal.png`, aktive Kanäle **LinkedIn + Instagram**

## Wichtige Entscheidungen / Konventionen
- **Verarbeitung über Max (Weg B):** EDL + Composition über Claude-Sub-Agents (Max, ~gratis) statt API-Skripte (~$4/Video). Trigger: *„verarbeite den Batch &lt;name&gt;"*.
- **HDR-Tonemap:** `render.py` nutzt `clip @ npl=1000` (treue HLG→SDR; npl höher = dunkler).
- **Logo:** weiß, klein, **oben-rechts** als Watermark.
- **CTA-Stil (ab #03):** gesprochenen CTA rausschneiden → **schwarzer End-Screen** mit Text-CTA (~3s).
- **Anrede: Du** (nie „Sie").
- **Nie Projekte löschen/überschreiben** — immer neuer Batch-Name.

## Bisherige Batches (Outputs unter `projects/` + `batches/`, gitignored)
- `test__01` — erstes Test-Reel (HDR/Zoom/Logo iteriert)
- `kosten__01` — Kostenmess-Lauf (vollautomatisch via API ≈ **$4**)
- `2026-06-21_Büsum_im_Park__01–05` — 5 Reels (über Max, **~$0,35** API gesamt); **#03** mit überarbeitetem Hook („Deine Mitarbeiter denken nicht mit?") + schwarzem CTA-End-Screen

## Web-Oberfläche (neu) — `webui/`
- Lokale **Flask-App** (Weg B): **Inbox** (Upload+Batch+Kontext), **Batches** (Übersicht+Review-Links), **Bibliothek** (alle Videos+Captions). Palstek-gebrandet.
- Start: `uv run --with flask python webui/server.py` → http://127.0.0.1:8730
- Details: `webui/README.md`

## Kosten (siehe `KOSTEN-PROTOKOLL.md`)
- ~**$4/Video** bei API-Pipeline; ~**$0,35** für 5 Videos über Max.
- Diese sehr schwere Session = nur **2 %** des Wochen-Max-Kontingents → Max massiv unterausgelastet.
- **Entscheidung:** Max-Abo (100 €, ChatGPT 20 € gekündigt → ~80 € netto) lohnt sich klar; Iteration „gratis".

## Offene / nächste Punkte
- **Weg C:** „Batch starten"-Knopf in der Web-App via **headless Claude Code** (→ läuft über Max). Ausbaustufe.
- Andere Büsum-Videos (01, 02, 04, 05): ggf. auf schwarzen End-Screen-CTA umstellen (wie #03) — auf Wunsch.
- Echter Browser-Chat (Claude Agent SDK) nur, falls Dritte die App self-service nutzen sollen (dann API-Kosten).
- `caption_gen.py`: reproduzierbarer JSON-Bug (seq 02 scheiterte) — bei Gelegenheit fixen.

## Wiedereinstieg
- Status/nächster Schritt einer Batch: `npm run batch:status -- --batch <name>` bzw. `npm run batch:next -- --batch <name>`
- Memory (über Sessions): `~/.claude/projects/-Users-marc-PycharmProjects-video-maker/memory/` (Brand=Du, never-delete-projects)
