# Brand-Vorlage (default)

> **Das ist eine leere Vorlage — noch nicht deine Marke.**
> Befülle sie **gemeinsam mit Claude** über das Design-Interview:
> öffne dieses Projekt in Claude Code und sag *„Lass uns das Reel-Design festlegen"*
> (Ablauf: [`../../DESIGN-INTERVIEW.md`](../../DESIGN-INTERVIEW.md)).
> Claude stellt dir Fragen und trägt die Antworten in genau diese Dateien ein.

Alles, was hier mit `<!-- TODO -->` markiert ist, ist ein Platzhalter. Bis du
sie ersetzt, produziert die Pipeline saubere, aber bewusst neutrale Reels.

---

## Was die Pipeline aus dieser Mappe liest

| Datei | Wird gelesen von | Wofür |
|-------|------------------|-------|
| `colors_and_type.css` | Composition/Render | Farben, Fonts, Radien, Motion-Tokens der Reels |
| `SKILL.md` + `README.md` + `tone.md` | `caption_gen.py` | Stimme/Ton + Proof-Points für die Captions |
| `caption-templates/*.md` | Caption-Stage | Format-Konventionen je Plattform |
| `metricool.json` | `batch_init` / Push | An welchen Kanal/Account gepostet wird |
| `broll/` | Composition-Stage | eigene B-Roll-Clips für Cutaways |
| `assets/` | Compositions | Logo / Bilder |

---

## 1. Sprache
- Markenname: Palstek GmbH (Geschäftsführerin Juliana Wiechert)
- Sprache: Deutsch
- Anrede: Du
- Zielgruppe: Geschäftsführer und Führungskräfte in KMU. Fach‑Anglizismen dürfen verwendet werden, solange sie fachlich korrekt und verständlich bleiben.

## 2. Ton & Voice
- Empathische Nahbarkeit trifft souveräne Fachkompetenz.
- Klar, direkt und fachlich souverän, mit einer Prise Humor.
- Spannung entsteht in der Sache, nicht in der Lautstärke.
- Fokus auf handfeste Erkenntnisse und praxisnahe Beobachtungen.

## 3. Casing & Typo-Devices
- Headlines Satzcase oder Title Case, lieber keine VERSALIEN.
- Dezente Eyebrows möglich, aber nicht schrill.
- Punkt am Ende von Aussagen ist ok; keine unnötigen Abkürzungen.

## 4. Farben
- Akzent: #4ebbc2
- Sekundär: #281d67
- Basis: Weiß, Schwarz, Grau
- Gesamt: ruhige, professionelle Farbwelt mit einem klaren, freundlichen Akzent.

## 5. Typografie
- Display-Font / Text-Font: Korbin Medium (lokal, siehe Pfad font_kobin_medium)
- Stil: modern, klar, gut lesbar bei Headlines und Kurztexten.

## 6. Spacing & Layout
- Layout: eher luftig, aber mit klarem Fokus pro Beat. Gebe jedem Textblock und jeder Karte Raum, damit die Botschaft bei schnellen Reels sofort lesbar bleibt.
- Ränder: großzügig, aber keine zu großen Abstände, damit die Aufmerksamkeit nicht zu sehr verloren geht.

## 7. Motion
- Motion-Ausprägung: dezent, professionell, rhythmisch. Keine hektischen Effect-Splats.
- Primär: `power3.out`, `sine.inOut`, `back.out(1.4)` für Reveals und Anker-Worte. `linear` vermeiden.
- Standard: sanfte Text-Fades, Akzent-Underlines und subtile Push/Pull-Bewegung auf dem Speaker.

## 8. Overlays & Subtitles
- Subtitle-Position: unten, zentriert, max. 2 Zeilen. Der wichtigste Begriff kann im Akzent hervorgehoben werden.
- Lower-Thirds: optional, auf dunklem, leicht transparentem Hintergrund mit `brand-500`-Akzentlinie.
- Anker-Worte: groß, markant, aber nicht bunt. Ein Farbakzent genügt.

## 9. Bildsprache / B-Roll
- Stimmung: sachlich-echt, professionell und nahbar. Keine übertriebenen Stock-Bilder.
- Eigene Clips: wenn vorhanden, immer bevorzugen. Bringe echte Business-Szenen oder Gesprächsmomente ein.
- B-Roll-Standard: bei vorhandenen Clips ca. alle ~10 s einen Cutaway, jede Szene 2,5–3,5 s.

## 10. Proof-Points (für Captions, NIE erfinden)
- Belegbare Fakten, die in Captions auftauchen dürfen:
  - „Psychologisch fundierte Führung“
  - „stabilere Teams“
  - „weniger Ausfälle und Fluktuation“
  - „Praxisnahe Führungstipps für KMU“
  - „konkrete Handlungsschritte statt Buzzwords“
