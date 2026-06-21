# Setup — Anleitung für Claude Code

> Diese Datei befolgst **du, Claude**, wenn der Nutzer sagt **„Lies SETUP.md und
> richte mich ein."** Ziel: Am Ende kann der Nutzer sofort Reels bauen — mit genau
> den Anbindungen, die er für sein Vorhaben braucht, und ohne selbst zu basteln.

Sprich Deutsch, in einfacher Sprache. Der Nutzer ist evtl. kein Entwickler.
Sei **idempotent**: Was schon erledigt ist (Ordner da, `npm install` gelaufen,
`.venv` vorhanden), überspringst du statt zu überschreiben.

---

## Was hier gebaut wird

Ein KI-Video-Studio mit zwei Werkzeugen, die schon mitgeliefert sind:
- **video-use** (`./video-use/`) — Transkription, Schnitt, Untertitel, Self-Eval.
- **Hyperframes** — HTML-basierte Motion-Graphics-Compositions, Render via FFmpeg.

Das Tooling ist **im Ordner enthalten** — du musst nichts von GitHub klonen. Du
installierst nur die System-Tools und die Abhängigkeiten und richtest die Keys ein.

---

## Phase 0 — Plan zeigen (max. 7 Bullets) und auf „OK" warten

Zeig dem Nutzer kurz, was du tun wirst, und warte auf Freigabe:
```
1. Tool-Check (node, python, uv, ffmpeg, git)
2. Fehlendes installieren (ich gebe dir das Kommando für dein OS)
3. npm install + Hyperframes-Skills verlinken
4. video-use einrichten (uv sync)
5. Anbindungs-Interview: welche Keys brauchst du? → .env befüllen
6. Verifikation (hyperframes doctor + Import-Check)
7. Hinweis: als Nächstes dein Reel-Design via DESIGN-INTERVIEW.md
```

---

## Phase 1 — Tool-Check (Pre-flight)

OS automatisch erkennen (`uname` / `process.platform`). Prüfe:

| Tool      | Min-Version | Pflicht? |
|-----------|-------------|----------|
| `node`    | ≥ 22        | ✓ |
| `npm`     | ≥ 10        | ✓ |
| `python3` | ≥ 3.11      | ✓ |
| `uv`      | latest      | ✓ |
| `ffmpeg`  | ≥ 4.x       | ✓ |
| `ffprobe` | ≥ 4.x       | ✓ |
| `git`     | ≥ 2.30      | ✓ (für npm-Pakete) |

Fehlt etwas, gib dem Nutzer **das exakte Install-Kommando für sein OS** und warte
auf Bestätigung:

**macOS:**
```bash
brew install node@22 python@3.12 ffmpeg uv git
```
**Windows (PowerShell):**
```powershell
winget install OpenJS.NodeJS.LTS Python.Python.3.12 Gyan.FFmpeg astral-sh.uv Git.Git
```
**Linux (Debian/Ubuntu):**
```bash
sudo apt update && sudo apt install -y python3.12 ffmpeg git
curl -LsSf https://astral.sh/uv/install.sh | sh
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - && sudo apt install -y nodejs
```

---

## Phase 2 — Hyperframes installieren + Skills verlinken

```bash
npm install
```
Installiert `hyperframes` & Co. aus `package.json`. Danach die mitgelieferten
Skills aus `node_modules/hyperframes/dist/skills/` projekt-lokal verlinken (so
updaten sie mit `npm update` automatisch):

**macOS/Linux:**
```bash
mkdir -p .claude/skills
for name in hyperframes gsap hyperframes-cli; do
  ln -sfn "$(pwd)/node_modules/hyperframes/dist/skills/$name" ".claude/skills/$name"
done
```
**Windows (PowerShell, kein Admin dank Junction):**
```powershell
New-Item -ItemType Directory -Force .claude\skills | Out-Null
foreach ($name in @("hyperframes","gsap","hyperframes-cli")) {
  $t = ".claude\skills\$name"
  if (Test-Path $t) { Remove-Item $t -Recurse -Force }
  New-Item -ItemType Junction -Path $t -Target "node_modules\hyperframes\dist\skills\$name" | Out-Null
}
```
> **Nicht** `npx skills add ...` nutzen — das zieht ungeprüften Code von außen
> und wird vom Auto-Mode blockiert. Die npm-Skills sind gleichwertig.

Danach `./video-use/` ebenfalls als Skill verlinken:
```bash
# macOS/Linux
ln -sfn "$(pwd)/video-use" ".claude/skills/video-use"
```
```powershell
# Windows
$t=".claude\skills\video-use"; if (Test-Path $t){Remove-Item $t -Recurse -Force}
New-Item -ItemType Junction -Path $t -Target "video-use" | Out-Null
```

---

## Phase 3 — video-use einrichten

video-use liegt schon im Ordner. Nur die Python-Umgebung bauen:
```bash
cd ./video-use && uv sync && cd ..
```

---

## Phase 4 — Anbindungs-Interview (das Herzstück)

**Frag den Nutzer per `AskUserQuestion`, was er vorhat** — daraus ergibt sich,
welche Keys er braucht. Trag NUR die nötigen ein, der Rest bleibt leer.

**Frage 1 — Was willst du tun?** (Mehrfachauswahl)
- *Reels schneiden & rendern* → braucht **ANTHROPIC_API_KEY** + Transkription.
- *Nur erstmal testen* → **ElevenLabs Free-Tier** reicht als Transkription.
- *Fertige Reels automatisch posten* → zusätzlich **Metricool** oder **Postiz**.

**Frage 2 — Transkription:** OpenAI Whisper (günstig, gut für Batches) oder
ElevenLabs Scribe (höhere Qualität, Free-Tier zum Testen)? (mind. eines)

**Frage 3 — nur falls Auto-Posting gewählt:** Metricool (gehostet, einfach) oder
Postiz (self-hosted, Docker)? Sonst diese Frage weglassen.

Für jeden gewählten Dienst nenne dem Nutzer den Link zum Key:
- Anthropic: https://console.anthropic.com/settings/keys
- OpenAI: https://platform.openai.com/api-keys
- ElevenLabs: https://elevenlabs.io/app/settings/api-keys
- Metricool: siehe `metricool/README.md`
- Postiz: siehe `postiz/README.md`

### Keys eintragen — sicher (empfohlen) vs. bequem
Frag per `AskUserQuestion`, wie er die Keys eintragen will:
- **„Ich trage sie selbst ein" (empfohlen)** — du legst `.env` aus `.env.example`
  an (`cp .env.example .env`), öffnest sie im Editor (`open -e .env` / `code .env`
  / `notepad .env`), erklärst, hinter welchen Zeilen welcher Key kommt, und
  **wartest**, bis er „fertig" sagt. Den Key-Wert NIE im Chat zeigen oder loggen.
- **„Ich gebe dir die Keys im Chat"** — du schreibst sie in `.env` (Komfort; Key
  liegt damit auch in der Chat-History).
- **„Später"** — `.env` leer anlegen, am Ende Hinweis geben, wo er nachträgt.

### .env synchronisieren
Die Wahrheit ist die `.env` im Projekt-Root. video-use liest aus seiner eigenen
`.env`. Nach jedem Befüllen synchronisieren:
```bash
cp .env video-use/.env      # macOS/Linux
```
```powershell
Copy-Item .env video-use\.env -Force   # Windows
```
Auf Windows beim direkten Schreiben **`Set-Content -Encoding utf8`** verwenden
(sonst BOM-Probleme mit python-dotenv).

---

## Phase 5 — Verifikation

```bash
npm run doctor                                   # Hyperframes-Selbsttest
uv run --project ./video-use python -c "import sys; print('video-use OK')"
ffmpeg -version | head -1
```
Wenn der Nutzer einen Transkriptions-Key eingetragen hat, biete einen Mini-Test an
(kurzes Sample transkribieren) — optional.

---

## Phase 6 — Abschluss & Übergabe ans Design

Fass kurz zusammen: was installiert ist, welche Keys aktiv sind (NUR Namen, nie
Werte), was noch fehlt. Dann der wichtige nächste Schritt:

> „Setup steht ✅. Als Nächstes legen wir dein **Reel-Design** fest — Farben,
> Schrift, Tonfall, Untertitel-Stil. Sag einfach: **„Lass uns mein Reel-Design
> festlegen"**, dann folge ich `DESIGN-INTERVIEW.md` und baue daraus deine Marke
> unter `brand-guidelines/default/`."

**Wichtig:** Es kommt KEINE fertige Marke mit. `brand-guidelines/default/` ist
eine neutrale Vorlage mit Platzhaltern — das Design entsteht im Interview.

---

## Anti-Patterns (kosten sonst Stunden)
- Kein `npx hyperframes preview/render` auf fremden Bundles (StaticGuard rejected).
- Speaker-Video vor Bundle-Render auf All-Intra-Keyframes konvertieren
  (`-g 1 -keyint_min 1 -sc_threshold 0`), sonst hängt der Speaker.
- `.env` nie committen, Keys nie im Chat zeigen.
- Windows: vor `uv run python ...` immer `PYTHONUTF8=1` setzen.
