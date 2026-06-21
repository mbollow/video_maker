# Metricool MCP Push Orchestration (Phase 8 Primary)

Diese Anleitung sagt dir (Claude) wie du den **Phase-8-Push eines Batches via
Metricool-MCP** orchestrierst — als Alternative zu `postiz_push.py` (Fallback).

Der Metricool MCP-Server stellt Tools bereit unter dem Namespace
`mcp__metricool__*`. Du rufst sie pro Video × Plattform auf und aktualisierst
das Manifest nach jedem Push.

---

## Voraussetzungen vor dem Push

1. **MCP installiert** (siehe `metricool/README.md`) — verifiziere mit
   `claude mcp list`, "metricool" muss da sein.
2. **Brand verbunden in Metricool UI** — alle 4 Plattformen connected.
3. **`metricool.default_blog_id`** im manifest gesetzt (siehe weiter unten).
4. **Phase 1-7 durch** — alle Videos haben `status=scheduled` und Captions
   sind in `posts.<platform>.caption` befüllt.

---

## Manifest-Felder (Metricool-spezifisch)

Erweitere die `postiz`-Sektion im Manifest um `metricool`:

```json
{
  "postiz": {...},  // bleibt für Fallback
  "metricool": {
    "default_blog_id": 123456,
    "username": "deine-marke",
    "rate_limit_per_hour": 100
  }
}
```

Per-Plattform-Status-Tracking im `posts`-Block:

```json
"posts": {
  "linkedin": {
    ...
    "metricool_post_id": null,
    "metricool_response": null,
    "pushed_via": null  // "metricool" oder "postiz" nach dem Push
  }
}
```

Update `batch_init.py` falls noch nicht gesetzt — beim Init das Schema
ergänzen.

---

## Orchestration-Loop (für jeden Batch)

### Schritt 1 — Verifikation

Rufe `mcp__metricool__list_brands` (oder ähnliches Tool — exakter Name vom
MCP-Server-Tool-Inventar) auf, um zu bestätigen:
- Token funktioniert
- Brand mit erwarteter `blog_id` ist da
- Alle 4 Plattformen sind verbunden

Bei Fehler: stoppe und melde dem User. Nicht auf Postiz-Fallback automatisch
ausweichen — User-Entscheidung.

### Schritt 2 — Pro Video iterieren

Lies `batches/<name>/manifest.json`. Für jedes Video mit `status=scheduled`
oder `status=captioned`:

Für jede Plattform (`linkedin`, `instagram`, `tiktok`, `youtube`):
- Skip wenn `posts.<platform>.enabled == false`
- Skip wenn `posts.<platform>.status == "pushed"`
- Skip wenn kein `caption` oder kein `scheduled_at`
- Ansonsten: push.

### Schritt 3 — Push pro Plattform

Rufe das passende MCP-Tool auf. Erwarteter Tool-Name (in dem Stil):

```
mcp__metricool__schedule_post
  - blog_id: <metricool.default_blog_id>
  - platform: "linkedin" | "instagram" | "tiktok" | "youtube"
  - content: <posts.<platform>.caption>
  - media_path: <absolute path to projects/<batch>__<seq>/renders/final.mp4>
  - scheduled_at: <posts.<platform>.scheduled_at>  // ISO 8601 mit tz
  - draft: false  // true für Erstvalidierung
```

YouTube braucht zusätzlich:
- `title`: `<posts.youtube.title>`

Nach jedem erfolgreichen Call:
- `posts.<platform>.metricool_post_id` = Response-ID
- `posts.<platform>.status` = "pushed"
- `posts.<platform>.pushed_via` = "metricool"
- `posts.<platform>.metricool_response` = trimmed response

Nach jedem Fehler:
- `posts.<platform>.status` = "failed"
- `posts.<platform>.metricool_response` = `{"error": "..."}`
- Nicht abbrechen — andere Plattformen / Videos weiter pushen.

Manifest nach jedem Push speichern (atomic write).

### Schritt 4 — Rate-Limiting

Metricool's Rate-Limit ist nicht öffentlich dokumentiert (Stand 2026-05).
Konservativ: **Sleep 1-2 Sekunden zwischen MCP-Calls.** Bei 429/503: 30s
exponential backoff. Bei dauerhaftem Fail: stoppe und melde User.

### Schritt 5 — Stage-Update + Log

Nach allen Plattformen eines Videos:
- `stages.posted = {"at": <iso>, "platform_summary": {"linkedin": "pushed", "tiktok": "failed", ...}}`
- Wenn ALLE enabled Posts pushed → `status = "posted"`
- Wenn manche failed → `status = "partially_posted"`

Append Log-Line zu `batches/<name>/metricool/push.log`:
```
[2026-05-27T08:42:11+02:00] seq=03 linkedin=ok(post_12345) tiktok=fail(quota) youtube=ok(post_12346) instagram=ok(post_12347)
```

---

## Draft-Mode (Erstvalidierung)

Vor dem ersten Live-Push sollte der User immer Draft-Mode testen:

```
User: "Push batch smoketest via Metricool — draft mode"
```

Du rufst die MCP-Tools mit `draft: true` (falls vom MCP-Server unterstützt)
oder mit `scheduled_at` in der fernen Zukunft (z.B. 2099-01-01) und einer
Status-Markierung "DRAFT" im Caption-Prefix. User inspiziert in Metricool
UI, dann ohne Draft-Flag neu pushen.

---

## Was machst du NICHT

- ❌ Postiz-Skripts (`postiz_push.py`) automatisch fallback aufrufen — User
  muss explizit "via Postiz" sagen wenn er Postiz will.
- ❌ Token / blog_id im Chat loggen — nur in MCP-Config.
- ❌ Nachträglich Captions umschreiben "weil die Plattform was nicht mag" —
  wenn Plattform-spezifische Anpassung nötig, an caption_gen zurückgeben mit
  Steering.
- ❌ Rate-Limit ignorieren — sleep ≥1s zwischen Calls auch wenn Tool das
  zulässt.

---

## Pre-Flight Checklist (vor jedem Phase-8-Push)

- [ ] `claude mcp list` zeigt "metricool"
- [ ] `mcp__metricool__list_brands` returnt erwartete Brand
- [ ] Manifest hat `metricool.default_blog_id` gesetzt
- [ ] Alle Videos im Batch haben `status=scheduled`
- [ ] Alle enabled Posts haben `caption` + `scheduled_at`
- [ ] User hat "OK" zum Push gegeben (Phase 7 abgeschlossen)
- [ ] Bei erstem Push einer neuen Brand: Draft-Mode

Erst wenn alle ✓: loslegen.

---

## Fallback auf Postiz

Wenn der User sagt *"per Postiz pushen"* oder Metricool-MCP nicht verfügbar
ist, verwende `postiz_push.py` (siehe `postiz/README.md`). Die Pipeline ist
agnostisch — beide Stacks lesen dasselbe Manifest.

Markiere im Manifest dann `posts.<platform>.pushed_via = "postiz"`, sodass
Audit-Trail klar ist.
