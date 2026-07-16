# gf-fotos — Foto-Quelle für Bild-Posts (Single-Image)

Read-only Bibliothek echter Fotos der Geschäftsführerin (Juliana). Quelle für die
**Bild-Post-Pipeline** (`bild:hooks` → `bild:build` → `bild:freigabe:push`).

## Wichtig
- **Die Fotodateien liegen NICHT hier**, sondern in den OneDrive-Ordnern aus der
  Umgebungsvariable **`GF_FOTOS_DIR`** (siehe `.env`). `GF_FOTOS_DIR` darf **mehrere
  Ordner** enthalten, per `|` getrennt (z.B. das echte Foto-Shooting **und** die
  freigegebenen KI-Bilder). Ein einzelner Pfad ohne `|` funktioniert unverändert.
  Die Pipeline sucht eine Datei über alle Quell-Ordner (`bild_common.resolve_photo`).
- Der Shooting-Ordner (`…/Marketing/Bilder/**`) ist **schreibgeschützt** (harte
  `deny`-Regel in `.claude/settings.json`); die Pipeline liest dort nur.
- Hier im Repo liegt nur **`catalog.json`** — die Stichwort-Tags je Foto, mit
  denen Phase 2 das passende Bild zu einem Hook/Spruch auswählt (Match über Tags,
  nicht über Dateinamen). Echte Fotos **und** freigegebene KI-Bilder (`ki_NNN.jpg`)
  sind getaggt und damit gleichberechtigt auswählbar; KI-Einträge tragen
  `"quelle": "ki"`.

## Der Katalog ist die Wunschliste, der Ordner ist die Wahrheit
Beide Richtungen werden zur Laufzeit in `bild_common.load_catalog` abgeglichen:
- **Eintrag ohne Datei** (Bild aus Qualitätsgründen gelöscht) → Eintrag wird
  übersprungen, `match_photo` kann ihn nicht mehr vorschlagen. Kein Abbruch.
  Der Eintrag darf ruhig in der `catalog.json` stehen bleiben.
- **Datei ohne Eintrag** (neues Bild abgelegt, Tags vergessen) → Warnung beim
  Build. Ohne Tags ist ein Bild für `match_photo` unsichtbar und nur per
  `bild_file: <name>` anpinnbar.

**Regel: neue KI-Bilder direkt nach dem Ablegen taggen** — sonst liegen sie da,
ohne je gewählt zu werden.

## catalog.json
- `root_env`: Name der Env-Variable mit dem Wurzelpfad (`GF_FOTOS_DIR`).
- `bilder[]`: je Foto `file` (nur Dateiname) + kontrollierte Tags
  (`szene`, `outfit`, `stimmung`, `aktion[]`, `crop`, `farbe`, `format`, `textraum`).
- `vokabular`: erlaubte Werte je Kategorie (beim Tagging daran halten).
- Optional bei KI-Bildern: `quelle: "ki"` sowie `qualitaet: "maengel"` +
  `qualitaet_hinweis` (rein informativ aus der Sichtung — **beeinflusst die
  Auswahl nicht**, dient als Hinweis, welche Bilder man aussortieren möchte).

## Weitere Bildquellen
- Pexels-Stock — on-demand per API, kein Ordner (`--source stock`).
- **Keine KI-Kennzeichnung** in Caption/Post — bewusste Entscheidung; KI-Bilder
  werden wie echte Fotos behandelt.

## Visueller Standard (Bild-Post)
- Vorlage: `video-use/helpers/composition_templates/static-post.html`
- Foto formatfüllend (4:5, 1080×1350), **Teal-Overlay `#4ebbc2` @ 35 %** (kein Verlauf),
  Logo oben rechts, Hook/Spruch in Montserrat fett, Punchline in dunkler
  `#281d67`-Marker-Box. Muster: `_muster_bildpost.png`.
