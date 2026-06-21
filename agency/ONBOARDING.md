# Neuen Kunden onboarden (Agentur-Modus)

Du betreibst das System, deine Kunden sind **Marken**. Sie loggen sich nie ein —
du produzierst ihre Reels unter ihrer Marke und stellst ihnen eine Rechnung
(Retainer / pro Reel — das läuft komplett außerhalb der Software).

Pro Neukunde brauchst du **einmal** das Setup unten (~30–45 Min, das meiste ist
Brand-Feinschliff). Danach läuft jedes Video dieses Kunden durch dieselbe
Voll-Auto-Pipeline wie deine eigenen.

---

## 0. Voraussetzung (einmalig für die ganze Agentur)
- **Metricool-Plan „Advanced"** (15 Brands) statt „Starter" (1 Brand) — siehe
  `metricool/README.md`. Erst damit kannst du mehrere Kunden parallel posten.

## 1. Marke anlegen (1 Befehl)
```bash
npm run agency:onboard -- --brand <slug> --label "<Anzeigename>" --blog-id <metricool-blog-id>
# Beispiel:
npm run agency:onboard -- --brand mueller-gmbh --label "Müller GmbH" --blog-id 1234567
# Instagram-Marke (statt LinkedIn):
npm run agency:onboard -- --brand mein-account --label "Mein Account" --platforms instagram
```
`--platforms` (Default `linkedin`) bestimmt, auf welche Kanäle diese Marke postet —
landet als `enabled_platforms` in `metricool.json`, `batch_init` aktiviert genau die.
Mehrere: `--platforms instagram,tiktok`.
Das erzeugt:
- `brand-guidelines/<slug>/` (Kopie der `default`-Marke als Startpunkt)
- `brand-guidelines/<slug>/broll/` (leer — für die Clips des Kunden)
- `brand-guidelines/<slug>/metricool.json` (mit der `blog_id` des Kunden)

> Die `blog_id` findest du in der Metricool-UI in der URL, wenn du auf die Brand
> wechselst (`?blogId=...`). Ohne `--blog-id` trägst du sie später in
> `metricool.json` nach.

## 2. Marke an den Kunden anpassen
Bearbeite in `brand-guidelines/<slug>/`:
- **`colors_and_type.css`** — Farben + Schriften des Kunden.
- **Logo** unter `assets/` / `brand/` durch das Kunden-Logo ersetzen.
- **`SKILL.md` + `README.md`** — Ton, Ansprache (du/Sie), Proof-Points (für Captions).
- **`caption-templates/{linkedin,instagram,tiktok,youtube}.md`** — Format/Hashtags des Kunden.

## 3. Metricool des Kunden verbinden
In der Metricool-UI für diese Brand die Kanäle verbinden (LinkedIn/IG/TikTok/YT
per OAuth). `blog_id` muss in `brand-guidelines/<slug>/metricool.json` stehen.

## 3b. Kunden-Zugang anlegen (der Kunde lädt selbst hoch)
```bash
npm run web:client:create -- <email> <brand> [passwort]
# Beispiel (Passwort wird generiert, wenn weggelassen):
npm run web:client:create -- kontakt@mueller-gmbh.ch mueller-gmbh
```
Das legt dem Kunden einen **Login** an (Rolle `client`, fest an seine Marke gebunden).
- Schick dem Kunden **E-Mail + Passwort + den `/login`-Link**.
- Der Kunde loggt sich ein und lädt seine Rohvideos auf **`/inbox`** hoch
  (mit Thema/Anweisung/Länge). Die Uploads laufen automatisch unter **seiner Marke**.
- **Du** musst nichts weiter tun: dein Voll-Auto-Watcher sieht die Kunden-Uploads,
  produziert sie unter `<brand>` (eigener Batch `inbox-<datum>-<brand>`) und legt
  Metricool-Drafts auf dem Kunden-Kanal an.

Der Kunde sieht **nur seine eigenen** Uploads — keine anderen Kunden, keine
Operator-Ansicht.

## 4. B-Roll des Kunden einspielen
- Clips des Kunden nach `brand-guidelines/<slug>/broll/` legen (Dateinamen egal).
- Dann mir sagen: **„Bau den B-Roll-Katalog für `<slug>`"** → ich extrahiere
  Frames, beschreibe sie per Vision, schreibe `catalog.json`.
- Kein eigenes Material? Dann bleibt es Talking-Head + Motion-Graphics (auch ok).

## 5. Erstes Video produzieren
```bash
npm run batch:init -- --batch <batchname> --brand <slug>      # Scaffold + Transkription
npm run batch:pipeline -- --batch <batchname>                  # Schnitt→B-Roll+Zoom→Render→Caption→Schedule→Upload
npm run batch:review -- --batch <batchname> --open             # Dashboard prüfen
npm run metricool:push:draft -- --batch <batchname>            # als Entwürfe in Metricool (sicher)
```
→ Erst als **Draft** prüfen (Video hängt dran? Caption passt?), dann in Metricool
freigeben oder `--live` schedulen.

## 6. (Optional) Voll-Auto pro Kunde
Der Inbox-Watcher (`npm run inbox:auto`) ist aktuell auf **eine** Marke gestellt
(`--brand default`). Für mehrere Kunden zwei saubere Wege:
- **Pro Kunde eine Batch manuell** (Schritt 5) — volle Kontrolle, empfohlen am Anfang.
- **Pro Kunde ein eigener Watcher** mit `--brand <slug>` (eigene Inbox-Quelle pro
  Kunde nötig — die aktuelle Inbox ist ein gemeinsamer Stream; Erweiterung „Brand
  pro Inbox-Upload" ist ein kleiner Folge-Build, wenn du es brauchst).

---

## Abrechnung (außerhalb der Software)
Du verkaufst „fertige Reels / Done-for-you", nicht den Software-Zugang. Übliche
Modelle: Monats-Retainer (z.B. X Reels/Monat) oder Preis pro Reel. Rechnung
stellst du selbst — die Software muss davon nichts wissen.

## Was pro Kunde getrennt ist (und was nicht)
| Getrennt pro Kunde | Geteilt (Agentur-weit) |
|---|---|
| Brand-Ordner, Logo, Farben, Ton | dein Anthropic/ElevenLabs/OpenAI-Key |
| B-Roll (`<brand>/broll/`) | der Mac/Worker, der rendert |
| Metricool-Brand + Kanäle (`blog_id`) | dein Metricool-Account (1 Login, N Brands) |
| Captions, Batches, Reels | die Pipeline-Helper selbst |
