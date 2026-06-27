# Kosten-Protokoll — ein Video A bis Z

**Ziel:** echten $-Aufwand für die Erzeugung + Nachbearbeitung **eines** Videos messen.

## Lauf 1

- **Batch-Name:** `kosten`  → Projekt `projects/kosten__01/` (test__01 bleibt unberührt)
- **Start:** 2026-06-22 21:39 CEST

### Baseline (BITTE VOR dem Lauf eintragen)
Aktueller Stand, damit wir die Differenz bilden können:

| Quelle | Wo ablesen | Stand VORHER |
|---|---|---|
| Anthropic | console.anthropic.com → Usage (Cost, heute/Monat) | _________ $ |
| OpenAI (Whisper) | platform.openai.com → Usage | _________ $ |

### Pro-Schritt-Log (gemessen)
- **Video:** IMG_5371 (Hochformat, 88s Quelle) → Reel 58,4s
- **Lauf:** 21:53:03 → 22:04:02 ≈ **11 Min** (vollautomatisch via `batch:pipeline`, keine Konversation)

| Schritt | Dienst/Modell | Messgröße | grob $ |
|---|---|---|---|
| Transkription | OpenAI Whisper | 88s = **1,47 Audio-Min** | ~$0,009 |
| EDL / Schnitt | Anthropic **Opus** | Console-Delta | (ablesen) |
| Cut + Render | ffmpeg/Chromium, lokal | ~1 CPU-Burst | **$0** |
| Composition | Anthropic **Opus** | Console-Delta | (ablesen) |
| Caption (4 Plattf.) | Anthropic **Sonnet** | Console-Delta | (ablesen) |
| Schedule | lokal (keine API) | — | **$0** |

> Alle Anthropic-Schritte (EDL + Composition + Caption) liefen über den API-Key
> → **Summe steht als Console-Delta**. Whisper separat im OpenAI-Dashboard.

### Ergebnis (GEMESSEN)
| Quelle | Verbrauch | Kosten des Videos |
|---|---|---|
| **Anthropic** (EDL + Composition + Caption) | 846.882 in / 33.664 out Tokens | **$4,03** |
| **OpenAI** (Whisper) | 1,47 Audio-Min | ~$0,01 (Dashboard läuft 1 Tag nach) |
| Render (lokal) | CPU-Burst | $0 |
| **GESAMT pro Video (Pipeline pur)** | | **≈ $4,04** |

**Abrechnungs-Klärung (wichtig):** Nutzer ist auf **Claude Max**. Damit ist
der Claude-Code-/Konversations-Aufwand (inkl. der von Claude gestarteten
Sub-Agents) **pauschal über das Abo abgedeckt** und erscheint **nicht** in der
API-Console. Die $4,03 sind also **rein die Pipeline-Skripte** (EDL + Composition
+ Caption über den API-Key) — mein Gesprächs-/Tuning-Anteil ist NICHT enthalten.

**Erkenntnis:**
- Vollautomatischer Durchlauf (keine Nachbearbeitung) ≈ **$4 pro Video**.
- Dominanter Kostentreiber: die **agentischen Schleifen** (EDL + Composition auf Opus) — 847k Input-Tokens kommen durch das mehrfache Kontext-Senden über viele Tool-Runden zustande. Prompt-Caching dämpft den Preis (sonst wären es ~$4,20+ allein für Input).
- **Whisper + Render sind praktisch gratis.**
- **Hand-Tuning** (HDR/Zoom/Logo-Runden wie bei test__01) kommt **on top** — über den Konversations-Anteil, stark variabel.

**Spar-Hebel (falls relevant):**
- EDL + Composition auf **Sonnet** statt Opus → grob ~⅓–½ der Kosten, etwas geringere Schnitt-/Layout-Qualität.
- `--effort medium` bei den Agenten → weniger Tokens.

### Notizen
- „Pipeline" (Schnitt/Caption/Composition) läuft über den **API-Key → Anthropic Console**.
- Der **Render** kostet keine Tokens (lokale Rechenleistung).
- Der **Konversations-Anteil** (mit Claude Code) ist separat → `/cost`.
- Für eine möglichst saubere Zahl: Lauf mit **wenig** Hin-und-Her fahren.
