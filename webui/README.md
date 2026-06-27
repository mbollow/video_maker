# Palstek VideoMaker — Web-Oberfläche (lokal, Weg B)

Eine kleine lokale Web-App (Flask) als **Dashboard + Eingang**:
- **📥 Inbox** — Videos hochladen, Batch anlegen, Kontext/Infos hinterlegen
- **📦 Batches** — alle Batches mit Status, Sprung zur jeweiligen Review-Seite
- **🎬 Bibliothek** — alle gerenderten Videos batch-übergreifend, inkl. Captions

> **Weg B:** Die Oberfläche **verarbeitet nicht selbst** (das würde über die API laufen, ~$4/Video).
> Sie sammelt Uploads und zeigt Ergebnisse. Das eigentliche Schneiden/Rendern stößt du über
> **Claude Code** an (läuft über dein Max-Abo, ~gratis): *„verarbeite den Batch &lt;Name&gt;"*.

## Starten

```bash
uv run --with flask python webui/server.py
```

Dann im Browser öffnen: **http://127.0.0.1:8730**

(Beendet wird der Server mit `Ctrl+C` bzw. durch Stoppen des Hintergrund-Tasks.)

## Typischer Ablauf

1. **Inbox** → Videos hochladen → Batch-Name vergeben → optional Kontext eintragen → *Hochladen & Batch anlegen*
   (legt `raw/batches/<name>/` an, optional `_context.md`)
2. **Claude Code** → „verarbeite den Batch <name>" → EDL/Cut/Composition/Render/Caption/Schedule (über Max)
3. **Batches** → Review-Seite öffnen, prüfen; Korrekturen via Claude Code (`03: caption neu`)
4. **Bibliothek** → fertige Videos + Captions ansehen

## Technik

- `server.py` — Flask-App (Routen, Batch-/Library-Scan, Upload, Media-Serving mit Traversal-Schutz)
- `templates/` — Jinja-Templates (base + 3 Seiten), Palstek-gebrandet
- `static/` — CSS (Brand-Tokens), Korbin-Font, Logo
- Liest/schreibt ausschließlich die bestehenden Ordner `raw/batches/`, `batches/`, `projects/`.

Ausbaustufe (später): echter Chat im Browser via Claude Agent SDK, bzw. „Batch starten"-Knopf
über headless Claude Code (Weg C) — beides optional.
