# Metricool Setup (gehosteter Posting-Stack)

> **Wichtig (bitte zuerst `../POSTING.md` lesen):** Metricool plant Video-Posts
> über eine **öffentlich erreichbare URL** des Reels. Dieses Paket enthält
> **kein** Upload-zu-eigenem-Speicher — du brauchst für den headless-Push also
> eigenes Media-Hosting, oder du postest über Metricool manuell (Datei aus dem
> Review-Dashboard hochladen). Für **vollautomatisches** Posten ohne extra
> Hosting ist **Postiz** der einfachere Weg (`../postiz/README.md`).

**Metricool** redet über den offiziellen **Metricool MCP-Server** direkt mit
Claude — kein Docker, kein Custom-Code. Setup in ~1 Stunde.

---

## Warum Metricool statt Postiz?

| | Postiz (Fallback) | **Metricool MCP** (Primary) |
|---|---|---|
| Kosten | 0€ (self-hosted) | 20€/mo (Starter) — 53€/mo (Advanced, 15 Brands) |
| Setup-Aufwand | docker compose + OAuth-Walkthrough pro Plattform | **1 Terminal-Command für MCP + OAuth in Metricool UI** |
| TikTok-Verifikation | Du machst sie (24-72h+ Wartezeit) | **Metricool hat sie pre-approved** |
| Instagram Meta-App-Review | Du machst es (2-7 Tage Wartezeit) | **Metricool hat es pre-approved** |
| Pflege | Du wartest Docker / Updates / Postgres | Metricool kümmert sich |
| Multi-Kunden | White-label self-host, eigene Skalierung | **Advanced = 15 Brands native** |
| Plattformen | 4 (manuell) | 11+ (IG, TikTok, YT, LinkedIn, FB, X, Pinterest, Threads, Bluesky, Twitch, ...) |

---

## Schritt 1 — Metricool Account + Plan

1. Account anlegen unter https://metricool.com/signup (14-Tage-Trial enthält Starter-Features)
2. Plan wählen:
   - **Starter** — 20€/mo annual oder 25€/mo monthly — 1 Brand, 5 Channels (deine 4 + 1 Reserve). **Empfohlen für dich allein.**
   - **Advanced** — 53€/mo annual oder 67€/mo monthly — 15 Brands. **Wenn du später Kunden onboarden willst.**
3. Trial nutzen — wenn nach 14 Tagen unzufrieden, kannst du cancelen und auf Postiz wechseln (siehe `postiz/README.md`).

---

## Schritt 2 — Plattformen in Metricool UI verbinden

In Metricool UI:
- **Brand anlegen** (z.B. "Deine Marke")
- **Plattformen verbinden** (Connections / Channels):
  - LinkedIn → OAuth ~1h
  - Instagram Business → OAuth via Metricool (Metricool's Meta-App ist pre-approved, kein Wait)
  - TikTok Business → OAuth via Metricool (pre-approved, kein Wait)
  - YouTube Channel → OAuth via Metricool

**Wichtig:** Du brauchst Instagram als **Business Account** und musst es vorher mit einer Facebook Page verbinden (Meta-Requirement, unabhängig von Metricool). TikTok braucht **Business-Account-Switch** (kostenlos, in TikTok-App in 5 Min).

Insgesamt ~1-2h für alle 4 Plattformen, statt Tage/Wochen Approval-Wait.

---

## Schritt 3 — API-Token holen

In Metricool UI:
**Settings → API & Integrations → User Token**

Notiere:
- `METRICOOL_USER_TOKEN` (Bearer-ähnlicher Token-String)
- `METRICOOL_USER_ID` (numerische ID, sichtbar in URL nach Login)
- Pro Brand: `blogId` (sichtbar wenn du auf eine Brand wechselst — die URL enthält `?blogId=...`)

Die `blogId` brauchst du pro Brand. Für Single-Brand-Setup eine. Für Multi-Brand (Resale): eine pro Kunde.

---

## Schritt 4 — MCP-Server in Claude Code installieren

**Ein einziger Command im Terminal**:

```bash
claude mcp add-json "metricool" '{
  "command": "uvx",
  "args": ["mcp-metricool"],
  "env": {
    "METRICOOL_USER_TOKEN": "<dein-token>",
    "METRICOOL_USER_ID": "<deine-user-id>"
  }
}'
```

Verifizieren:
```bash
claude mcp list
# sollte "metricool" aufführen
```

Bei nächstem Claude-Code-Start sind die Metricool-Tools verfügbar (`mcp__metricool__*`).

---

## Schritt 5 — Erstvalidierung (1 Test-Post)

In Claude-Chat:
> *"List meine Metricool-Brands"*

Claude ruft das MCP-Tool `mcp__metricool__list_brands` auf und zeigt deine Brands + blogIds.

Dann z.B.:
> *"Schedule einen Test-Post mit Text 'Hallo Welt' auf LinkedIn für 5 Minuten in der Zukunft"*

Claude ruft `mcp__metricool__schedule_post` mit den richtigen Parametern auf. Falls erfolgreich → siehst du den Draft in Metricool UI (Calendar-View).

Erst wenn das durchgeht: produktive Batches pushen.

---

## Schritt 6 — Pipeline-Integration

Nach dem MCP-Setup ändert sich am Batch-Workflow **nichts** außer dem letzten Schritt (Phase 8):

```bash
# Phasen 1-7 wie bisher:
npm run batch:init -- --batch <name>
# ...sub-agents, caption, schedule, review...

# Phase 8 NEU: statt postiz_push.py einfach Claude bitten
# In Claude-Chat:
"Push batch <name> via Metricool"
```

Claude liest das Manifest und ruft die MCP-Tools per Video × Plattform. Status wird ins Manifest zurückgeschrieben (`posts.<platform>.status = pushed`, `metricool_post_id = ...`).

Detaillierte Orchestration-Anleitung für Claude: `video-use/helpers/prompts/metricool_push_orchestration.md`.

---

## Plan-Wechsel später

**Solo → Multi-Kunden (Resale):**
- Upgrade Starter → Advanced (53€/mo)
- Neue Brand in Metricool UI pro Kunde anlegen
- Pro Kunde eine `blogId`
- Manifest's `metricool_blog_id` Feld pro Batch setzen (siehe orchestration prompt)
- Ein einziger MCP-Server bedient alle Kunden

**Wenn Metricool zu teuer wird oder Vendor-Lock-In stört:**
- Postiz steht weiterhin parat (`postiz/docker-compose.yml`)
- Sub-Agent-Prompts + Pipeline 1:1 identisch
- Switch in ~30 Min: postiz hochfahren, OAuth-Setups + `postiz_push.py` aktivieren

---

## Troubleshooting

**`claude mcp list` zeigt metricool nicht:**
- Claude Code neu starten (Cmd+Q dann erneut öffnen)
- `claude mcp` Befehl-Verfügbarkeit prüfen (Claude-Code-Version ≥ 0.5+)

**MCP-Tool-Calls returnen 401/403:**
- Token in `claude mcp` Config falsch / abgelaufen
- `claude mcp remove metricool` und mit korrektem Token neu hinzufügen

**`mcp__metricool__schedule_post` failt mit "blogId required":**
- blogId aus Metricool-URL kopieren (sichtbar wenn Brand selektiert ist)
- Im Manifest pro Batch hinterlegen unter `metricool.default_blog_id`

**Media-Upload failt:**
- Videos müssen MP4 sein (was unsere Pipeline rendert ✓)
- Max 4GB pro File (1080×1920/30fps Reels sind typisch <100MB)
- Plattform-Limits (TikTok 287MB von Mobile-Upload, mehr von Desktop) — Metricool macht meist seamless transcode

---

## Cost-Tracking

| Use-Case | Plan | Kosten/Monat |
|---|---|---|
| Solo (eine Marke) | Starter | 20€ annual / 25€ monthly |
| + Add-on: X/Twitter posting | Starter + Add-on | + 5€ pro X-Account |
| 5 Kunden | Advanced | 53€ annual / 67€ monthly |
| 15 Kunden | Advanced | 53€ annual / 67€ monthly (max plan limit) |
| 15+ Kunden | Custom | Quote von Metricool |

Vergleich: Postiz self-hosted bleibt 0€, aber kostet ~5h Setup + ~30 min/Monat Wartung + die TikTok/Instagram-Wartezeiten.
