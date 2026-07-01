# gf-fotos — Foto-Quelle für Bild-Posts (Single-Image)

Read-only Bibliothek echter Fotos der Geschäftsführerin (Juliana). Quelle für die
**Bild-Post-Pipeline** (`bild:hooks` → `bild:build` → `bild:freigabe:push`).

## Wichtig
- **Die Fotodateien liegen NICHT hier**, sondern im OneDrive-Ordner aus der
  Umgebungsvariable **`GF_FOTOS_DIR`** (siehe `.env`). Dieser Pfad ist
  **schreibgeschützt** (harte `deny`-Regel in `.claude/settings.json` auf
  `…/Marketing/Bilder/**`). Die Pipeline liest dort nur.
- Hier im Repo liegt nur **`catalog.json`** — die Stichwort-Tags je Foto, mit
  denen Phase 2 das passende Bild zu einem Hook/Spruch auswählt (Match über Tags,
  nicht über Dateinamen).

## catalog.json
- `root_env`: Name der Env-Variable mit dem Wurzelpfad (`GF_FOTOS_DIR`).
- `bilder[]`: je Foto `file` (nur Dateiname) + kontrollierte Tags
  (`szene`, `outfit`, `stimmung`, `aktion[]`, `crop`, `farbe`, `format`, `textraum`).
- `vokabular`: erlaubte Werte je Kategorie (beim Tagging daran halten).

## Spätere Bildquellen (noch nicht aktiv)
- `gf-ki/` — KI-generierte Juliana-Bilder (separater Ordner; triggert die
  KI-Kennzeichnung in der Caption). Wird nachgerüstet.
- Pexels-Stock — on-demand per API, kein Ordner.

## Visueller Standard (Bild-Post)
- Vorlage: `video-use/helpers/composition_templates/static-post.html`
- Foto formatfüllend (4:5, 1080×1350), **Teal-Overlay `#4ebbc2` @ 35 %** (kein Verlauf),
  Logo oben rechts, Hook/Spruch in Montserrat fett, Punchline in dunkler
  `#281d67`-Marker-Box. Muster: `_muster_bildpost.png`.
