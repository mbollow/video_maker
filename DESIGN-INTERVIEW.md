# Reel-Design festlegen — Anleitung für Claude Code

> Diese Datei befolgst **du, Claude**, wenn der Nutzer sagt **„Lass uns mein
> Reel-Design festlegen."** Ziel: Aus ein paar Fragen entsteht die persönliche
> Marke des Nutzers — kein fremdes Design wird übernommen.

Sprich Deutsch, locker, in kurzen Runden (nicht alle Fragen auf einmal). Nach
jeder Antwort schreibst du das Ergebnis direkt in die Vorlage-Dateien unter
`brand-guidelines/default/` (dort stehen `<!-- TODO -->`-Platzhalter, die du
ersetzt). Am Ende zeigst du eine Vorschau und holst Freigabe.

**Grundsatz:** Diese Marke gehört dem Nutzer. Erfinde keine Behauptungen/Zahlen —
Proof-Points kommen vom Nutzer. Wo er „such du was Passendes aus" sagt, schlägst
du etwas vor und lässt es bestätigen.

---

## Die Marke lebt in diesen Dateien (Pipeline liest sie automatisch)

| Datei | Wofür |
|-------|-------|
| `colors_and_type.css` | Farben + Schrift-Tokens (Composition/Untertitel lesen das) |
| `README.md` | ausführliche Marken-Beschreibung (Ton, Casing, Bildsprache) |
| `SKILL.md` | Kurzfassung für die Agents (Voice, Regeln) |
| `caption-templates/{linkedin,instagram,tiktok,youtube}.md` | Caption-Stil je Plattform |
| `metricool.json` | Zielkanäle + Zeitzone (nur fürs Posten) |
| `broll/` | eigene Cutaway-Clips (optional) |

---

## Das Interview (Runde für Runde)

### Runde 1 — Wer & Sprache
1. **Markenname / Label** (was soll als Absender gelten?)
2. **Worum geht's** in 1–2 Sätzen? (Thema, Zielgruppe)
3. **Anrede:** Du oder Sie? Sprache (Deutsch/Englisch/…)?

→ In `README.md`/`SKILL.md`: Marken-Essenz, Sprache, Anrede eintragen.

### Runde 2 — Tonfall
4. **Wie klingst du?** (z. B. direkt & knapp / warm & nahbar / sachlich-fundiert /
   verspielt). Gib 2–3 Beispiel-Adjektive.
5. **Beispielsätze:** Hast du 1–2 typische Sätze von dir? (Hook/Pain/Versprechen)
6. **Emojis:** ja/sparsam/nie? **Casing** der Headlines (Satzbau vs. Versalien)?

→ In `README.md` „Voice & tone", „Casing", „Sample lines" befüllen; in `SKILL.md`
   die Kurzregeln.

### Runde 3 — Farben & Schrift
7. **Farben:** Hast du Markenfarben (Hex)? Sonst schlage ich dir eine Palette vor
   (1 dunkler Grundton + 1 Akzent + Neutrale) und du sagst ja/nein.
8. **Schrift:** Lieber kräftig/modern oder klassisch/seriös? Konkrete Fonts oder
   soll ich passende Google-Fonts vorschlagen?

→ In `colors_and_type.css` die **bestehenden Token-Namen** mit echten Werten
   füllen (Variablennamen NICHT umbenennen — sonst bricht das Composition-Template).

### Runde 4 — Reel-Look
9. **Untertitel-Stil:** Position (unten/Mitte), Hervorhebung aktiver Wörter (Farbe/
   Bold), Hintergrund-Box ja/nein?
10. **Overlays:** dezent (nur Untertitel) oder mehr Motion (Eyebrows, Lower-Thirds,
    Zahlen-Pop-ups)?
11. **Motion-Intensität:** ruhig/dezent vs. dynamisch? (steuert Zoom/Transitions)
12. **B-Roll:** Hast du eigene Clips? Wenn ja, wohin legen → `brand-guidelines/
    default/broll/`, danach „Bau den B-Roll-Katalog". Wenn nein: reiner
    Talking-Head mit dezentem Speaker-Zoom.

→ In `README.md`/`SKILL.md` Abschnitte „Subtitles", „Overlays", „Motion",
   „Bildsprache" befüllen.

### Runde 5 — Plattformen & Posten (optional)
13. **Wo postest du?** (LinkedIn/Instagram/TikTok/YouTube) → `metricool.json`
    `enabled_platforms` + Zeitzone setzen.
14. **Caption-Stil je Plattform:** Hashtags ja/nein, Länge, CTA? → die 4
    `caption-templates/*.md` anpassen (Proof-Points/CTAs kommen vom Nutzer).

---

## Abschluss

1. **Vorschau bauen:** Lege optional eine kleine Vorschau-HTML an, die die
   gewählten Farben/Schrift/Untertitel zeigt, und zeig sie dem Nutzer (oder rendere
   ein 5-Sekunden-Testreel, falls schon ein Sample-Video da ist).
2. **Freigabe holen** (auf Deutsch, Plain Language). Korrekturen → betroffene
   Felder anpassen, erneut zeigen.
3. **Fertig:** Ab jetzt nutzen alle Reels automatisch diese Marke (Fallback
   `brand-guidelines/default/`).

---

## Mehrere Marken? (optional, für Agentur/mehrere Kunden)
Eine zusätzliche Marke anlegen:
```
npm run agency:onboard -- --brand <slug> --label "Name" --platforms linkedin
```
Das scaffoldet `brand-guidelines/<slug>/` aus der Vorlage — dann dasselbe Interview
für diese Marke. Beim Schneiden später sagen: „Nutze die Brand `<slug>`."
Checkliste: `agency/ONBOARDING.md`.
