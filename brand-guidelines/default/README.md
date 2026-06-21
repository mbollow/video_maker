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
<!-- TODO: Welche Sprache? Du oder Sie? Anglizismen erlaubt? -->
- Beispiel: *Deutsch, „du", Fach-Anglizismen okay.*

## 2. Ton & Voice
<!-- TODO: 3–5 Sätze: Wie klingt deine Marke? Direkt? Verspielt? Sachlich? -->
- Beispiel: *Klar, konkret, anti-Floskel. Kurze Sätze. Belege statt Versprechen.*

## 3. Casing & Typo-Devices
<!-- TODO: Headlines Satz-/Title-Case? Eyebrows UPPERCASE? Punkt am Headline-Ende? -->
- Beispiel: *Headlines Satzcase mit Punkt. Eyebrows UPPERCASE, weites Tracking.*

## 4. Farben
<!-- TODO: Hauptfarbe (Akzent), Ink/Neutral, Hintergrund. In colors_and_type.css eintragen. -->
- Beispiel: *Dunkles Ink + EIN Akzent. Akzent nur sparsam (CTA, ein Wort pro Zeile).*

## 5. Typografie
<!-- TODO: Display-Font + Text-Font (Google Fonts). KEINE gebannte Schrift (docs/motion-philosophy.md). -->
- Beispiel: *Display: kräftige Grotesk. Text: ruhige humanistische Sans.*

## 6. Spacing & Layout
<!-- TODO: enge oder luftige Reels? -->
- Beispiel: *Großzügige Ränder, ein klarer Fokus pro Beat.*

## 7. Motion
<!-- TODO: Overrides zu docs/motion-philosophy.md? Sonst gelten die Defaults. -->
- Beispiel: *Reveals power3.out, Loops sine.inOut, nie linear. Dezent.*

## 8. Overlays & Subtitles
<!-- TODO: Untertitel-Stil (Position, Hervorhebung des Anker-Worts), Lower-Thirds? -->
- Beispiel: *Untertitel unten zentriert, Anker-Wort im Akzent hervorgehoben.*

## 9. Bildsprache / B-Roll
<!-- TODO: Welche Stimmung? Eigene Clips? -->
- Beispiel: *Warme, echte Clips aus dem Alltag. Eigene B-Roll nach `broll/`.*

## 10. Proof-Points (für Captions, NIE erfinden)
<!-- TODO: Belegbare Fakten/Zahlen, die in Captions auftauchen dürfen. -->
- Beispiel: *„seit 2019", „120+ Projekte" — nur was wirklich stimmt.*
