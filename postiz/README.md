# Postiz Self-Hosted Setup

Postiz ist der Posting-Backbone für den Batch-Workflow. Open Source (AGPLv3),
läuft als Docker-Stack lokal auf dem Mac (oder später auf einem VPS).

**Version:** v2.11.3 (stable, ohne Temporal-Komplexität von v2.12+).

---

## 1. Stack starten

```bash
cd postiz
docker compose up -d
```

Warte ~30-60 Sekunden bis Postgres + Redis ready sind, dann öffne:

**http://localhost:5000**

Admin-Account erstellen (E-Mail + Passwort merken — der erste registrierte
Account ist Admin).

---

## 2. JWT Secret setzen (vor Production)

Im `.env` oben (oder direkt in `postiz/.env`):

```
POSTIZ_JWT_SECRET=<32+ random characters>
```

Generieren:

```bash
openssl rand -base64 48
```

Stack neu starten:

```bash
docker compose down && docker compose up -d
```

---

## 3. OAuth pro Plattform

Postiz UI → **Settings → Channels → Add Channel**. Pro Plattform OAuth-Flow
durchklicken. Realistische Wartezeiten:

### 3.1 LinkedIn (1h Setup — geht zuerst live)

- LinkedIn Personal-Profile oder Company-Page
- OAuth-only, kein App-Review
- Nach Authorize: Integration-ID aus Postiz UI kopieren → `.env`:
  ```
  POSTIZ_LINKEDIN_INTEGRATION_ID=...
  ```

### 3.2 YouTube Shorts (1-7 Tage)

- YouTube Channel mit Posting-Eligibility (i.d.R. >1k Subs oder Brand Account)
- Google OAuth Flow
- Channel-Eligibility-Check kann 1-7 Tage dauern bei neuen/kleinen Channels
- Integration-ID nach Auth → `.env`:
  ```
  POSTIZ_YOUTUBE_INTEGRATION_ID=...
  ```

### 3.3 Instagram Reels (2-7 Tage — Meta App-Review)

- **Voraussetzung:** Instagram Business Account + verbundene Facebook Page
- Meta App-Review für Postiz-App: 2-7 Tage (real oft 14+)
- Nach Approval: OAuth-Flow in Postiz, Integration-ID kopieren → `.env`:
  ```
  POSTIZ_INSTAGRAM_INTEGRATION_ID=...
  ```

### 3.4 TikTok (24-72h — Business Verification)

- **KRITISCH:** Mai-2026-Hard-Deadline für komplette Business-Verifikation
- TikTok Business-Account (nicht Personal)
- Verifikation: Pass/ID + Bank-Account + Business-Docs hochladen
- 24-72h Wartezeit best-case, real oft länger
- Nach Approval: OAuth, Integration-ID → `.env`:
  ```
  POSTIZ_TIKTOK_INTEGRATION_ID=...
  ```

---

## 4. API-Key generieren

Postiz UI → **Settings → Developers → Public API → Generate Key**.

In `.env` (Projekt-Root):

```
POSTIZ_API_URL=http://localhost:5000
POSTIZ_API_KEY=<generated>
```

Test:

```bash
curl -H "Authorization: Bearer $POSTIZ_API_KEY" \
  http://localhost:5000/public/v1/integrations | jq
```

Sollte JSON mit deinen verbundenen Channels zurückgeben. Die `id`-Felder
sind die `POSTIZ_<PLATFORM>_INTEGRATION_ID`-Werte für `.env`.

---

## 5. Pro Plattform manuell testposten (PFLICHT vor erstem Batch-Push)

In Postiz UI: für **jede** verbundene Plattform einen einzelnen Testpost
manuell schicken. Wenn das durchgeht, sind die OAuth-Permissions korrekt.

Empfehlung: ein gezielter Testpost zu **Test-Accounts** machen (z.B.
`@deinemarke_test`) statt direkt zu Production-Accounts.

---

## 6. Sandbox-Modus für Pipeline-Erstvalidierung

Der erste Pipeline-Run sollte **nicht** direkt live gehen. Nutze
Draft-Mode:

```bash
uv run --project ./video-use python ./video-use/helpers/postiz_push.py \
  --batch smoketest --draft-mode
```

`--draft-mode` schickt `"type": "draft"` statt `"schedule"` an Postiz —
Posts landen als Drafts und können in der Postiz-UI inspiziert werden,
ohne in die echten Social-Feeds zu gehen.

Wenn die Drafts gut aussehen: ohne `--draft-mode` neu laufen lassen.

---

## 7. VPS-Migration (Optional, später)

Wenn der Mac nicht 24/7 läuft (z.B. wenn Schedule-Slots in der Nacht sind),
Stack auf einen kleinen VPS migrieren:

- **Hetzner CX11** (~5€/Monat, 4 GB RAM) — reicht für Postiz v2.11.3
- `docker-compose.yml` identisch, nur `POSTIZ_MAIN_URL` auf die VPS-Domain ändern
- Reverse-Proxy mit Caddy oder Nginx für HTTPS (Postiz erwartet HTTPS für
  OAuth-Callbacks von Instagram/TikTok)

---

## 8. Troubleshooting

**Container startet nicht / `database connection refused`:**
- Postgres braucht bis ~30s zum Boot. Healthcheck wartet, aber bei langsamen
  Mac-Disks kann `docker compose logs postiz` zeigen "database not ready".
- Lösung: `docker compose restart postiz` nach 60s.

**OAuth-Callback failt mit "redirect URI mismatch":**
- Bei Instagram/TikTok: die OAuth-App auf der Plattform-Seite (Meta Developer,
  TikTok Developer) muss `http://localhost:5000/integrations/oauth/<platform>`
  als zulässigen Redirect haben. Postiz UI zeigt die genaue URL.

**Postiz UI lädt nicht obwohl Container läuft:**
- Port-Konflikt prüfen: `lsof -i:5000`. Falls belegt, in
  `docker-compose.yml` `ports: ["5000:5000"]` auf z.B. `["5050:5000"]` ändern.

**Public-API 401 trotz Bearer-Token:**
- Token muss frisch sein. Alte Tokens werden ungültig wenn Postiz-Stack
  neu deployed wird.

---

## 9. Updates

```bash
docker compose pull
docker compose up -d
```

Achtung: v2.12+ requires Temporal (zusätzlicher Service). Diese Pipeline
lockt absichtlich auf v2.11.3 — Upgrade auf v2.12+ erfordert
docker-compose-Erweiterung und ist nicht getestet.
