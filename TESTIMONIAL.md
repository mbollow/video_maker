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

Testimonials haben einen **eigenen Freigabe-Ordner** `Freigabeprozess - Testimonial`
(getrennt von den Social-Video-Posts — es ist ein völlig anderer Prozess/Nutzung).
Pfad überschreibbar via Env `FREIGABE_TESTIMONIAL_DIR`; eigene Nummerierung
`NNN_<projekt>` ab 001. `npm run freigabe:check` liest Video- **und**
Testimonial-Ordner zusammen (je ein Abschnitt).

### Thumbnail (Pflicht, läuft automatisch mit)

Der Nutzer bettet das fertige Testimonial selbst auf der Website ein. Ein Besucher sieht
vor dem Klick **nur das Vorschaubild** — es muss also allein tragen, wer spricht, für
welches Unternehmen und worum es ging. Deshalb baut `testimonial:build` am Ende
automatisch ein Thumbnail und legt es neben das Video in den Freigabe-Ordner
(`thumbnail_vN__<projekt>.png`). Einzeln nachbauen:

```bash
npm run testimonial:thumbnail -- --projekt testimonial-mustermann
```

**Format:** 1920 × 1080 (16:9) PNG — bewusst groß, nicht Daumennagel-Größe.

**Pflichtinhalte, ohne Ausnahme:**
Palstek-Logo · Kundenlogo · Name **und** Rolle des Gesprächspartners ·
Inhalt der Zusammenarbeit (Titel + Untertitel).

**Layout** (an der Kundenfreigabe von 001 festgezurrt, `composition_templates/testimonial-thumbnail.html`):
dunkelblaue Zitatkarte auf `#281d67` mit dezentem Teal-Schein oben rechts, Palstek-Logo
oben links (106 px hoch), Kundenlogo oben rechts, türkise Pille „Kundenstimme", darunter
das Zitat groß (66 px) mit **einer** teal hervorgehobenen Belegstelle, unten links der Kopf
im Kreis (204 px, Teal-Rand) mit Name/Rolle, unten rechts der Produktblock.

**Warum ausgerechnet eine Zitatkarte:** Standbilder aus Online-Aufzeichnungen haben nativ
oft nur ~960 × 540 (Teams-Kachel). Formatfüllend wirken sie matschig. Hier trägt das Zitat,
das Foto ist nur Beleg — das funktioniert auch mit schwacher Bildquelle. Liegt ein
Pressefoto vor, sind großformatige Layouts wieder eine Option.

**Zitat:** ein Satz aus dem Interview, grammatikalisch geglättet (wie die Untertitel).
Am besten der mit dem härtesten Beleg. `zitat_highlight` färbt genau diese Stelle teal —
**eine** Hervorhebung, nicht zwei.

**Kundenlogo mit eigener Transparenz** (Website-Downloads haben die oft): wird vor dem
Freistellen auf Weiß gelegt. Ohne das wird der transparente Rand beim `convert("RGB")`
schwarz, gilt als volle Deckung und das Logo bekommt einen weißen Kasten.
Liefert der Kunde eine **weiße Fassung**, wird sie direkt übernommen — jede
Weiß-Erkennung würde das Logo selbst wegradieren. Zugeschnitten wird dann auf
**sichtbare** Deckung (Alpha > 25): Export-PNGs haben oft Alpha-1-Reste im ganzen
Rand, sonst landet das Logo winzig in einer riesigen leeren Box.

**Kopf im Kreis:** braucht Luft. Eng am Scheitel wirkt beklemmt, zu weit aufgezogen holt
den unruhigen Hintergrund der Aufzeichnung rein. Richtwert: Augen bei ~44 % der
Ausschnitthöhe, Ausschnitt ca. 0,7 × Bildhöhe. Über `portrait_s` (Sekunde im **fertigen**
Video) einen Moment mit offenem, freundlichem Gesichtsausdruck wählen — Kontaktbogen mit
`ffmpeg fps=1/4 … tile=` durchsehen, statt zu raten. Die **Unterkante** von
`portrait_crop` muss über dem Untertitel-Streifen bleiben (bei `sub_strip: 270` also
≤ 810) — darunter schneidet der Helper das Bild ab und der Rest landet als schwarzer
Rand im Kreis.

**Kundenlogo freistellen** (macht der Helper): weißen Hintergrund per **Flood-Fill vom
Bildrand** entfernen, nie global alles Weiße — sonst verschwinden weiße Glanzlichter
*innerhalb* der Grafik. Und nicht nur reines Weiß killen, sonst bleibt ein grauer Saum von
den weichen Kanten; stattdessen die Deckung aus der Helligkeit ableiten und die Schrift in
Zielfarbe (weiß fürs dunkle Layout) neu einfärben. Die farbige Bildmarke bleibt unberührt.

### Sprecher-ID-Box (Pflicht, läuft automatisch mit)

Unten rechts neben den Untertiteln steht dauerhaft eine kleine weiße Karte mit
**Kundenlogo · Name · Rolle** — sichtbar **nur während der Antworten**, auf
Intro-/Fragen-/Outro-Folien aus (dort steht der Name ohnehin auf der Folie).
Kundenwunsch: Der Gast stellt sich einmal am Anfang vor, nach fünf Minuten weiß
niemand mehr, wer da spricht.

Aktivieren über einen `idbox`-Block in der `testimonial.json`:
```json
"idbox": { "enabled": true, "rolle": "WP, StB & Partner" }
```
`name` fällt auf den `[intro]`-Block zurück, `rolle` auf `thumbnail.rolle` bzw.
das Intro, `logo` auf `thumbnail.kunde_logo`. Die Box wird nach dem Zusammenbau
ins Video gebrannt (`testimonial_idbox.py`), gepusht wird die Fassung **mit** Box.

> Sie war früher ein Handgriff **nach** dem Build — und ging bei jedem Rebuild
> still verloren. Deshalb hängt sie jetzt im Build. Prüfe nach einem Rebuild
> trotzdem einen Talking-Head-Frame, bevor du eine Version verschickst.

### Heranzoomen auf den Gast (optional, KEIN Automatismus)

Es gibt einen Ken-Burns-Zoom, der bei längeren Antworten sanft auf den Gast
heranfährt (der Mitschnitt wächst dabei in der Höhe) und vor Antwortende wieder
in den Zwei-Shot zurückkehrt. **Das ist bewusst ein Versuch pro Video, keine
pauschale Regel.** Ein frisch aufgesetztes Video zoomt **nie von allein**.

- Ausprobieren: `npm run testimonial:build -- --projekt <name> --zoom` — dann dem
  Nutzer zeigen und **auf Feedback warten**. NICHT ungefragt bei jedem Video anwenden.
- Das Framing ist **gast-/videospezifisch** (aktuell links verankert, weil Suhr
  links im Bild sitzt) — pro Video prüfen, ob Sitzposition und Höhenwachstum passen.
- Erst **nach Freigabe** durch den Nutzer den Zoom dauerhaft machen: einen
  `zoom`-Block mit `"enabled": true` (+ Feintuning `start_s`, `ramp_s`,
  `out_ramp_s`, `end_pad_s`, `z`, `min_answer_s`) in die `testimonial.json` des
  Projekts schreiben. Dann greift er auch ohne `--zoom` bei jedem Rebuild dieses
  einen Projekts.

### Bild-Modus: Zwei-Shot ODER Vollbild (pro Video wählen)

Zwei gleichwertige Optionen — **pro Gespräch bewusst entscheiden**, nicht pauschal:

- **Zwei-Shot (Standard):** Das ganze Sprecher-Band (beide Kacheln) mittig auf
  Creme. Richtig, **wenn auch der Interviewer sichtbar spricht** — z. B. Juliana
  stellt spontane Rückfragen oder reagiert on-camera. Dann wirkt der
  konventionelle Schnitt natürlicher. Kein `vollbild`-Block → dieser Modus.
- **Vollbild:** Nur die Kachel des Gasts, formatfüllend (der Interviewer „fällt
  weg"), unten ein Creme-Streifen für die Untertitel. Richtig, **wenn nur der
  Gast spricht** und die Fragen ohnehin als Folie eingeblendet werden (dann ist
  der Interviewer im Bild nur „totes" Beiwerk). So beim Suhr-Video gewählt.

Vollbild aktivieren: einen `vollbild`-Block in die `testimonial.json`:
```json
"vollbild": { "enabled": true,
  "crop": {"w":960,"h":540,"x":0,"y":270},   // Kachel des GASTS im Quellbild
  "sub_strip": 270, "crop_y_offset": 260 }    // Creme-Streifen-Höhe / vertik. Ausschnitt
```
`crop` = die Kachel, in der der Gast sitzt (Suhr = links → x0). Sitzt der Gast
rechts, entsprechend `x` verschieben. `crop_y_offset` justiert die Kopffreiheit.
Vollbild ersetzt den Zwei-Shot; ein Zoom ist dann hinfällig.

---

## Visueller Standard

Eine Teams/Zoom-Galerie ist ~**3,56:1** (zwei Kacheln nebeneinander) und lässt sich
**nicht** formatfüllend auf 16:9 bringen, ohne Gesichter zu beschneiden. Deshalb:

- Sprecher-Band freistellen (`band` in `testimonial.json`, von `init` erkannt) und mittig
  auf **Creme `#f8f6f2`** setzen — das ersetzt die schwarzen Balken.
- **Logo oben rechts** (nie unten — kollidiert mit den Untertiteln), auf Folie und
  Video an **exakt derselben Stelle und in derselben Größe** — sonst springt es bei
  jedem Schnitt. Die Werte stehen einmal in `testimonial_common` (`LOGO_H`,
  `LOGO_MARGIN`, `LOGO_TOP`); die Folien-Vorlage bekommt sie eingesetzt.
  Es wechselt nur die **Variante**: farbig/dunkel auf den weißen Folien,
  **weiß über dem Video** — vor dem Hintergrund des Gasts ist das dunkle Logo sonst
  nicht zu erkennen.
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
| `idbox` | Sprecher-ID-Box: `enabled`, optional `name`, `rolle`, `logo` |
| `thumbnail` | Vorschaubild für den Website-Embed: `kunde_logo` (Datei im Projekt oder URL), `zitat`, `zitat_highlight`, `produkt`, `produkt_sub`, `portrait_s`, optional `portrait_crop`, optional `rolle` (kurze Rolle — die volle aus dem Intro kollidiert mit dem Produktblock) |

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
| `video-use/helpers/testimonial_thumbnail.py` | Vorschaubild (läuft am Ende von `build` mit) |
| `video-use/helpers/composition_templates/testimonial-card.html` | Folien-Template |
| `video-use/helpers/composition_templates/testimonial-thumbnail.html` | Thumbnail-Template |
| `projects/<projekt>/interview.txt` | **kuratiert vom Menschen** |
| `projects/<projekt>/testimonial.json` | Technische Config |

Arbeitsordner (`projects/`) sind git-ignoriert — nur der Programmcode oben wird versioniert.
