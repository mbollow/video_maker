# Posten — die drei Wege (wichtig zu verstehen)

Die Pipeline rendert deine fertigen Reels **lokal** (`batches/<name>/<seq>/renders/
final.mp4`) und baut ein Review-Dashboard (`batches/<name>/review.html`) mit
Video + Captions + vorgeschlagenen Zeiten. Wie die Reels von dort in deine
Social-Kanäle kommen, hängt vom Posting-Weg ab:

| Weg | Braucht | Lädt das Video hoch via | Für wen |
|-----|---------|--------------------------|---------|
| **Manuell** | nichts | du, per Drag & Drop ins Tool | jeder — funktioniert immer |
| **Postiz** (self-hosted) | Docker lokal | lädt die **lokale Datei** direkt hoch | turnkey Auto-Posting ohne weiteres Hosting ✅ |
| **Metricool** (gehostet) | Metricool-Konto **+ öffentliche Video-URL** | eine **öffentlich erreichbare URL** des Reels | wenn du eigenes Media-Hosting hast |

## 1. Manuell (geht immer)
`npm run batch:review -- --batch <name> --open` → das Dashboard zeigt dir jedes
Reel + die Captions. Lad das `final.mp4` einfach selbst in dein Posting-Tool
(LinkedIn/Instagram/…) und kopier die Caption rüber. Kein Setup nötig.

## 2. Postiz — empfohlen für vollautomatisches Posten ✅
Postiz läuft als Docker-Stack **auf deinem eigenen Rechner** und nimmt die
gerenderte Datei direkt entgegen — **keine zusätzliche Hosting-Infrastruktur
nötig**. Setup: `postiz/README.md`. Dann:
```
npm run postiz:up                              # Docker starten
npm run postiz:discover                        # Integration-IDs holen (nach OAuth)
npm run postiz:push:draft -- --batch <name>    # erst als Draft (Pflicht!)
npm run postiz:push      -- --batch <name>     # live schedulen
```

## 3. Metricool — braucht eine öffentliche Video-URL
Metricool plant Posts über eine **öffentlich erreichbare URL** des Videos
(`media: [url]`). Der headless-Push `metricool:push` liest diese URL aus dem
Manifest-Feld `r2_url` jedes Videos.

**Dieses Paket enthält keinen Upload-zu-eigenem-Speicher.** Damit Metricool ein
Video posten kann, brauchst du also entweder:
- **eigenes Media-Hosting** (z. B. ein S3/R2-Bucket, ein Webspace, jede
  öffentliche URL) → die Reel-URL pro Video als `r2_url` ins Manifest schreiben,
  **oder**
- **Metricool manuell** nutzen: das `final.mp4` aus dem Dashboard direkt in der
  Metricool-Oberfläche hochladen (Caption aus dem Dashboard kopieren).

Ohne Media-URL überspringt `metricool:push` Video-Posts (für Instagram/TikTok/
YouTube zwingend; LinkedIn ginge text-only, ergibt für ein Reel aber keinen Sinn).
Für die direkte Metricool-MCP-Steuerung („Push batch X via Metricool") gilt
dasselbe: Metricool braucht eine erreichbare Mediendatei.

---

**Sicherheit:** Der **erste** Push geht IMMER als **Draft** ins Posting-Tool,
nie direkt live. Erst prüfen, dann live schalten.
