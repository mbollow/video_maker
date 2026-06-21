# Motion Philosophy

## Aesthetic
Modern, hochwertig, clean, dynamisch. Kein generischer "Tutorial-Look". Animation dient der Aussage — nie Selbstzweck.

## Easings
- `power3.out` für **Reveals** (Text-Entrances, Logo-In, Counter-Snap).
- `sine.inOut` für **Loops** (Ambient-Drifts, Background-Pans, Atemzug-artige Pulse).
- `expo.out` für **schnelle Akzente** (Hover-Reactions, Quick-Cuts).
- `back.out(1.4)` für **playful Snap** (Tag-Reveals, Sticker-Drops) — sparsam.
- **NIEMALS `linear`.** Linear ist tot — sofortiger Anti-Hint, dass die Animation lieblos ist.

## Anchor-Word-Sync
Jede Animation, die auf ein Wort reagiert, landet **mit** dem Wort — Toleranz ±100ms. Dafür:
1. ElevenLabs Scribe liefert Wort-Zeitstempel in `master.json`.
2. Anchor-Word im Transkript markieren (z.B. "innovation" bei Sekunde 12.34).
3. Animation-Trigger exakt auf den Wort-Start setzen, nicht auf einen Sentence-Start.

Wenn Sync >100ms daneben ist: fühlt sich nach Voice-Over-Layer an, nicht nach Composition. Korrigieren, nicht rationalisieren.

## Easing-Variety
Mindestens **3 verschiedene Easings pro Szene**. Ein einziges Easing über alle Elemente flattens die Komposition.

## Timing-Defaults
- Hero-Word-Reveal: 0.6-0.8s mit `power3.out`.
- Subtitle-In: 0.4s mit `expo.out`, fade-in parallel.
- Background-Pan: 8-12s mit `sine.inOut` (yoyo).
- Layout-Shift / Block-Transition: 0.5-0.7s mit `power3.inOut`.

## Banned Fonts
Diese Fonts wirken billig oder "Default-AI" — niemals verwenden:

Inter, Roboto, Open Sans, Lato, Poppins, Outfit, Sora, Fraunces, Playfair Display, Cormorant Garamond, Syne, Cinzel, Nunito, Source Sans, PT Sans, Arimo.

**Stattdessen** Brand-Typografie aus `brand-guidelines/<name>/typography.md` lesen. Wenn die Brand keine spezifische Wahl trifft: kuratierte Display-Faces wie Söhne, Neue Haas Grotesk, Migra, GT America, Reckless, Editorial New, FK Display.

## Render-Defaults
- **1920×1080 / 30fps** für Standard (Web, Embedded).
- **1080×1920 / 30fps** für Shorts (TikTok, Reels, YouTube Shorts).
- **3840×2160 / 60fps** wenn explizit gewünscht (4K-Bundle-Render: Viewport `1920×1080 @ deviceScaleFactor: 2`).
- Codec: H.264, CRF 18, `yuv420p`, AAC 192kbps Audio.

## Self-Eval nach Render
`timeline_view`-Pattern: nach jedem Render prüfen ob Animation-Beats zu Audio-Beats passen. Visuell auf Beat-Drift achten (Animation läuft Wort hinterher → falsch synced; Animation läuft Wort voraus → Trigger zu früh gesetzt). Erst dann dem Nutzer zeigen.
