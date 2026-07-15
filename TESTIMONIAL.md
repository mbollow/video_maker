# Testimonial-Videos (Langform, für die Website)

Aus einem aufgezeichneten Kunden-Interview (Zoom/Teams, Frage → Antwort) wird ein
**~vollständiges, einbettbares 16:9-Video** — bewusst **nicht** auf 30/60 s gekürzt
wie ein Reel. Jede Frage erscheint als optisch ansprechende Vollbild-Folie vor der
Antwort.

```
Intro-Folie → [Begrüßung] → n × (Fragen-Folie → Antwort) → [Fazit] → [Abschluss] → Outro mit CTA
```

Erstes Beispiel: André Suhr (WAPA Steuerberatung), 5:48 min.

---

## Die zwei Regeln, auf denen alles aufbaut

Sie sind am ersten Testimonial teuer gelernt worden — bitte nicht aufweichen:

**1. Das Video wird kaum geschnitten.**
Füllwörter („ähm", „halt") und natürliche Denkpausen **bleiben drin**. Jeder Schnitt im
Talking-Head ist ein sichtbarer Sprung. Bei einem Reel zahlt sich jede eingesparte
Zehntelsekunde aus — bei einem 6-Minuten-Vertrauensvideo kostet jeder Sprung mehr, als
die Straffung bringt. Geschnitten wird nur:
- Pausen über `max_pause_s` (Standard 1,2 s),
- inhaltlich Nötiges (Zwischenrufe, interne Absprachen) — über getrennte Bereiche in `antwort:`.

**2. Der Untertitel wird sauber ausformuliert.**
Keine Füllwörter, keine Wortwiederholungen, richtige Grammatik und Schreibweisen.
Der **Ton bleibt unangetastet** — gesprochen sagt der Gast weiterhin „'n Kanzlei",
im Untertitel steht „eine Kanzlei".

> Kurz: **sanft schneiden, sauber untertiteln.**

---

## Ablauf

### Phase 1 — Aufsetzen
```bash
npm run testimonial:init -- --projekt testimonial-mustermann \
  --quelle "/pfad/zur/aufzeichnung.mp4" [--brand default]
```
Legt den Projektordner an, transkribiert mit **Sprecher-Trennung** (Scribe, `diarize`),
erkennt das Sprecher-Band automatisch und leitet aus den Sprecher-Turns einen
**Vorschlag** ab: `projects/<projekt>/interview.txt`.

**Zur Quelle:** Liegen mehrere Rohdateien vor (Cloud-Aufzeichnung vs. Bildschirm-Mitschnitt),
nimm die **saubere Meeting-Aufzeichnung** — der Mitschnitt zeigt die Teams-Bedienleiste.
Vorher Anfang **und** Ende beider Dateien kurz transkribieren und vergleichen: Sie können
unterschiedlich lang sein, ohne dass eine unvollständig ist (Vorgespräch!).

### Phase 2 — Kuratieren
`interview.txt` von Hand durchgehen. Das ist der eigentliche redaktionelle Schritt:
- `text:` = die Frage **wie sie auf der Folie steht** — kurz ausformuliert, nicht der
  gesprochene Wortlaut (der steht als `# gesprochen:` daneben).
- `highlight:` = diese Worte werden türkis (`#4ebbc2`).
- `antwort:` = Sekunden aus der Quelle; mehrere Bereiche mit Komma trennen (die Lücke
  dazwischen fliegt raus — so entfernt man Zwischenrufe).
- `status: nein` lässt einen Block weg. Blöcke dürfen umsortiert werden.

### Phase 3 — Bauen
```bash
npm run testimonial:plan  -- --projekt testimonial-mustermann   # nur Schnitt+Untertitel zeigen
npm run testimonial:build -- --projekt testimonial-mustermann   # rendern + Auto-Push
```
Rendert Folien und Clips, setzt zusammen, macht den **Pflicht-Selbstcheck** (aac-Tonspur
vorhanden + Dauer plausibel) und pusht als **nächste Version** (`final_vN+1`) in den
Freigabe-Ordner. `--no-push` ist der Notausgang.

**Freigabe = Pflicht.** Der Nutzer und Juliana schauen **ausschließlich** im
Freigabe-Ordner, nie in `projects/<…>/renders/`. Rückmeldungen kommen über die
`FREIGABE__….txt` (Zeile 1 `FREIGEGEBEN` / `AENDERN`). Bestehende Versionen werden
**nie** überschrieben.

---

## Visueller Standard

Eine Teams/Zoom-Galerie ist ~**3,56:1** (zwei Kacheln nebeneinander) und lässt sich
**nicht** formatfüllend auf 16:9 bringen, ohne Gesichter zu beschneiden. Deshalb:

- Sprecher-Band freistellen (`band` in `testimonial.json`, von `init` erkannt) und mittig
  auf **Creme `#f8f6f2`** setzen — das ersetzt die schwarzen Balken.
- **Logo oben rechts** (nie unten — kollidiert mit den Untertiteln).
- Untertitel in **`#281d67`** im cremefarbenen Streifen darunter.
- Folien und Antworten teilen denselben Rahmen und dasselbe Logo. Deshalb wirken **harte
  Schnitte** zwischen Folie und Video ruhig — es wechselt nur das Band in der Mitte.
  Keine Crossfades nötig.
- Fragen-Folie: Teal-Pill („Frage 01"), Montserrat/Korbin fett, ein Akzentwort türkis.

## Anrede (Stolperfalle)

Der **Gast wird gesiezt**, das **Publikum wird geduzt**. Auf der Outro-Folie stehen beide
direkt übereinander — und das ist richtig so:

> „Danke, **Herr Suhr**!" … „Wie steht es um **euer** Team?"

Der Palstek-Standard „konsequent duzen" gilt fürs Publikum, **nicht** für den Interviewgast.
Kein Vorname in der Anrede — nur als Namensnennung auf der Intro-Folie.

---

## `testimonial.json` — die Stellschrauben

| Feld | Wofür |
|---|---|
| `sprecher` | Welche `speaker_id` ist Interviewer, welche Gast (von `init` geraten) |
| `band` | Crop des Sprecher-Bands. **Nachprüfen!** `cropdetect` zählt Namensschilder auf Schwarz als Inhalt mit und schätzt die Unterkante dann zu tief. |
| `schnitt.max_pause_s` | Ab wann eine Pause zusammengezogen wird (Standard 1,2) |
| `schnitt.ausnahmen` | Pro Block eine eigene Schwelle, z. B. `{"frage 04": 2.0}` |
| `schreibweisen` | Eigennamen, die Scribe verhört: `{"vapa": "WAPA", "sowang": "Suhr"}` |
| `textfixes` | Mehrwort-Korrekturen im Untertitel: `[{"suche": "a b c", "ersetze": "x y z"}]` |
| `karten` | Standzeiten der Folien in Sekunden |

**Zu `ausnahmen`:** Wenn ein Schnitt als Sprung auffällt, ist fast immer eine Denkpause
knapp über die Schwelle gerutscht. Dann **nicht** die globale Schwelle anheben (das ändert
das ganze Video) — sondern hier gezielt für diesen einen Block. Genau dafür ist das Feld da.

**Zu `textfixes`:** Bei **gleicher Wortzahl** behält jedes Wort seine eigene Zeit — sonst
läuft der Untertitel aus dem Takt. Ersetzungen mit anderer Wortzahl teilen sich die Spanne
und sollten deshalb kurz bleiben.

---

## Dateien

| Datei | Rolle |
|---|---|
| `video-use/helpers/testimonial_common.py` | Motor: Schnitt, Untertitel-Reinigung, Karten, ffmpeg |
| `video-use/helpers/testimonial_init.py` | Phase 1 |
| `video-use/helpers/testimonial_build.py` | Phase 2/3 + Freigabe-Push |
| `video-use/helpers/composition_templates/testimonial-card.html` | Folien-Template |
| `projects/<projekt>/interview.txt` | **kuratiert vom Menschen** |
| `projects/<projekt>/testimonial.json` | Technische Config |

Arbeitsordner (`projects/`) sind git-ignoriert — nur der Programmcode oben wird versioniert.
