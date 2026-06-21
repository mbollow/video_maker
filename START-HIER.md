# 👋 Willkommen beim VideoMaker

Damit baust du aus einem Roh-Video automatisch fertige **Social-Reels**:
Schnitt (inkl. Versprecher raus) → B-Roll-Cutaways → Untertitel & Motion-Graphics
→ fertiger Render → Captions für jede Plattform → optional automatisch posten.

Du steuerst alles über **Claude Code** in ganz normaler Sprache. Du musst nicht
programmieren.

---

## In 3 Schritten startklar

### 1. Ordner speichern
Du hast diesen Ordner (`videomaker-fuer-freunde`) bekommen. Leg ihn irgendwohin,
wo du ihn wiederfindest (z. B. `~/Projekte/videomaker`).

### 2. Claude Code im Ordner öffnen
Terminal in diesem Ordner öffnen und `claude` starten — oder den Ordner in deiner
IDE mit der Claude-Code-Erweiterung öffnen.

### 3. Diesen einen Satz an Claude schicken
```
Lies SETUP.md und richte mich ein.
```

Claude prüft dann, was auf deinem Rechner schon da ist, installiert den Rest,
**fragt dich, welche Anbindungen (API-Keys) du wirklich brauchst** — abhängig
davon, was du vorhast — und trägt sie sicher ein. Du brauchst vorher nichts zu
installieren und nichts über die Technik zu wissen.

---

## Danach: dein eigenes Reel-Design festlegen

Das Design der Reels ist **nicht** vorgegeben — du legst es **gemeinsam mit
Claude** fest (Farben, Schrift, Tonfall, Untertitel-Stil, Overlays …). Sag dazu:
```
Lass uns mein Reel-Design festlegen. Folge dazu DESIGN-INTERVIEW.md.
```
Claude führt dich durch ein paar Fragen und baut daraus deine Marke unter
`brand-guidelines/default/`. Ab dann sehen alle deine Reels nach *dir* aus.

---

## Dein erstes Reel

Wenn Setup + Design stehen, leg ein Roh-Video ab und sag z. B.:
```
Mach mir aus diesem Video ein Reel: <pfad/zum/video.mp4>
```
oder für mehrere auf einmal (Batch):
```
Ich will mehrere Videos auf einmal verarbeiten — wie geht der Batch-Workflow?
```

---

## Was du (je nach Vorhaben) an Konten brauchst

| Vorhaben | Was du brauchst |
|----------|-----------------|
| Reels schneiden & rendern | Anthropic-API-Key + Transkription (OpenAI **oder** ElevenLabs) |
| Nur mal testen | ElevenLabs Free-Tier reicht |
| Automatisch posten (optional) | Metricool-Konto **oder** self-hosted Postiz |

Claude erklärt dir das beim Setup im Detail und verlinkt, wo du die Keys holst.
Du gibst nur die Keys ein, die du für dein Vorhaben tatsächlich brauchst.

> **Wichtig:** Deine Keys landen in `.env` und bleiben **nur bei dir** — niemals
> teilen, niemals committen. Das ist bereits in `.gitignore` abgesichert.
