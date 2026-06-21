# VideoMaker

Aus Roh-Videos automatisch fertige Social-Reels bauen — gesteuert über **Claude
Code** in normaler Sprache. Schnitt (Versprecher raus), B-Roll-Cutaways,
Untertitel & Motion-Graphics, Render, plattformgerechte Captions und optional
automatisches Posten.

## Loslegen
Öffne **Claude Code** in diesem Ordner und schicke:
```
Lies SETUP.md und richte mich ein.
```
→ Details in **[START-HIER.md](START-HIER.md)**.

## Die drei Anleitungen, die Claude befolgt
| Datei | Zweck |
|-------|-------|
| `SETUP.md` | Einmal-Einrichtung: Tools prüfen/installieren, **nötige Anbindungen (API-Keys) klären**, `.env` befüllen. |
| `DESIGN-INTERVIEW.md` | Dein **Reel-Design** gemeinsam mit Claude festlegen → `brand-guidelines/default/`. |
| `CLAUDE.md` | Arbeitsregeln & Workflows (Schnitt-Standards, Batch-Modus, Posten). |
| `POSTING.md` | Die drei Wege zum Posten (manuell / Postiz / Metricool) — **vor dem Posten lesen**. |

## Was mitgeliefert ist (und was nicht)
- ✅ Komplettes Tooling: `video-use/` (Schnitt/Transkription) + Hyperframes-Setup, Batch-Pipeline, Caption-Gen, Auto-Posting (Metricool/Postiz).
- ✅ Eine **neutrale Brand-Vorlage** unter `brand-guidelines/default/` (Platzhalter — wird im Design-Interview befüllt).
- ❌ **Kein fremdes Design.** Dein Look entsteht im Interview.
- ❌ Keine Keys/Secrets. Die richtest du beim Setup ein; `.env` bleibt nur bei dir.

## Voraussetzungen
Node ≥ 22, Python ≥ 3.11, uv, ffmpeg, git. Fehlt etwas, gibt dir Claude beim Setup
das passende Install-Kommando für dein Betriebssystem.

## Anbindungen (je nach Vorhaben)
- **Schneiden & rendern:** Anthropic-Key + Transkription (OpenAI Whisper *oder* ElevenLabs Scribe).
- **Posten (optional):** Metricool (gehostet) *oder* Postiz (self-hosted, Docker).

Claude erklärt dir beim Setup, welche du wirklich brauchst.
