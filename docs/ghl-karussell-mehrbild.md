# GoHighLevel: die API meldet bei terminierten Mehrbild-Posts nur eine Folie

**Location-ID:** `3xZs9ttxAS2hmSZkZ2q7` · **API-Version-Header:** `2021-07-28`
**Gemessen am:** 18.08.2026 · **Betroffen:** Instagram, Facebook, LinkedIn (alle getesteten Kanäle)

## Auflösung (19.08.2026) — es ist ein Lesefehler, kein Datenverlust

**Das Karussell wurde auf Instagram und LinkedIn mit allen Folien in richtiger
Reihenfolge veröffentlicht.** Die Messreihe unten bleibt gültig, ihre damalige
Schlussfolgerung war falsch: Die API *meldet* nach dem Terminieren nur ein
Medium, die Folien sind aber vorhanden und werden vollständig ausgeliefert.

Konsequenzen:

- Karussells gehen wie jedes andere Format direkt als `scheduled` raus. Der
  erzwungene Draft-Umweg in `ghl_plan.py` ist entfernt.
- `npm run ghl:check-media` wertet die Medienzahl bei **terminierten**
  Mehrbild-Posts nicht mehr als Fehler — sie ist dort systematisch 1 und würde
  sonst bei jedem Karussell Alarm schlagen.
- Für Drafts und Einzelmedien bleibt die Zahl aussagekräftig.

## Was gemessen wurde

Ein Post mit mehreren Bildern behält als **Draft** alle Medien. Sobald er auf
**`scheduled`** steht, meldet die API nur noch das **erste** — über die API
ebenso wie beim Umstellen in der Oberfläche. Auch ein `PUT` mit der
vollständigen Medienliste ändert die gemeldete Zahl nicht.

Der Widerspruch, der schon damals auffiel und sich jetzt erklärt: Die
GHL-Oberfläche zeigte durchgehend alle Folien (Fall H).

## Messreihe

Testmaterial: 6 PNGs (1080×1350), vorher über `POST /medias/upload-file`
hochgeladen, also GHL-eigene CDN-URLs. Jeder Testpost wurde direkt nach der
Messung wieder gelöscht.

| # | Vorgehen | Medien danach |
|---|----------|---------------|
| A | `POST /social-media-posting/{loc}/posts` mit `status: "draft"` | **6 von 6** |
| B | dito mit `status: "scheduled"` + `scheduleDate` | **1 von 6** |
| C | wie B, Media-Items nur mit `url` + `type` | **1 von 6** |
| D | wie B, Media-Items mit `url` + `type` + `id` | **1 von 6** |
| E | wie B, zusätzlich `scheduleTimeUpdated: true` | **1 von 6** |
| F | als Draft anlegen (6 Medien bestätigt), dann `PUT …/posts/{id}` mit `status: "scheduled"` und allen 6 Medien | **1 von 6** |
| G | gekappten Post per `PUT` mit allen 6 Medien auf `draft` zurücksetzen | **1 von 6** (keine Reparatur möglich) |
| H | Draft in der GHL-Oberfläche über den Composer terminieren | **1 von 6** laut API — die Oberfläche zeigt weiterhin 6 (siehe Widerspruch unten) |

Gemessen jeweils per `GET /social-media-posting/{loc}/posts/{id}` über die
Länge von `results.post.media`.

## Beispiel-Payload (Fall B)

```json
{
  "accountIds": ["<instagram-account-id>"],
  "userId": "<user-id>",
  "summary": "…",
  "type": "post",
  "status": "scheduled",
  "scheduleDate": "2026-08-19T07:55:00.000Z",
  "media": [
    {"url": "https://assets.cdn.filesafe.space/…/01_start.png", "type": "image/png"},
    {"url": "https://assets.cdn.filesafe.space/…/02_02.png",   "type": "image/png"},
    {"url": "https://assets.cdn.filesafe.space/…/03_03.png",   "type": "image/png"},
    {"url": "https://assets.cdn.filesafe.space/…/04_04.png",   "type": "image/png"},
    {"url": "https://assets.cdn.filesafe.space/…/05_05.png",   "type": "image/png"},
    {"url": "https://assets.cdn.filesafe.space/…/06_ende.png", "type": "image/png"}
  ]
}
```

Antwort: `201`, Post angelegt. Direkt anschließendes `GET` liefert `media` mit
**einem** Eintrag.

## Konkrete Fälle aus unserem Account

| Post-ID | Kanal | Beobachtung |
|---|---|---|
| `6a841bf3cb218ddc171ac319` | Instagram | als Draft mit 6 Folien angelegt (08:46), im UI auf `scheduled` gestellt (10:22) → 1 Folie |
| `6a841bf23e51958e1361a68e` | Facebook | identisch |
| `6a841bf3658f6c6fffc8391f` | LinkedIn (Profil) | identisch |
| `6a84337f1bcc4a04d72bf456` | Instagram | neu als Draft mit 6 Folien angelegt (10:27), im **Composer** terminiert (11:00) → 1 Folie |

## Widerspruch zwischen API und Oberfläche

Nach dem Terminieren über den Composer meldet die API für den Post nur noch ein
Medium, die GHL-Oberfläche stellt aber weiterhin alle 6 Folien dar.

- `GET /social-media-posting/{loc}/posts/{id}` → `media` mit 1 Eintrag
- `POST /social-media-posting/{loc}/posts/list` (Suche) → ebenfalls 1 Eintrag
- Die URLs der Folien 2 bis 6 kommen in der **gesamten** Antwort nicht mehr vor
  (Volltextsuche über das JSON), also auch nicht in `instagramPostDetails`,
  `mediaOptimization` o. Ä.
- Als **Draft** liefern dieselben Endpunkte für denselben Post 6 Medien. Der
  Unterschied hängt also am Status, nicht generell an der Serialisierung.
- `parentPostId` (z. B. `54f8ccb6-19ea-4de4-b0c4-bf836157698f`) lässt sich über
  die öffentliche API nicht abrufen (`400`), wir können also nicht prüfen, ob
  der Eltern-Datensatz noch alle Folien hält.

## Frühere Karussells in diesem Account

Keiner unserer bisherigen Karussell-Posts hat je ein `publishedAt` bekommen,
es ist also noch nie eine Bildstrecke über GHL veröffentlicht worden:

| Ordner | Status heute | Medien | publishedAt |
|---|---|---|---|
| 001_faktor-1 (3 Posts) | `in_progress`, gelöscht | 6 / 1 / 6 | – |
| 002_faktor-2 (3 Posts) | `scheduled`, gelöscht | 1 / 1 / 1 | – |

Auffällig: bei 001 hielten zwei der drei Posts im Zustand `in_progress` noch
alle 6 Medien, der dritte nur eines.

## Fragen an den Support

1. Gibt es einen unterstützten Weg, einen Mehrbild-Post (Karussell) zu
   terminieren, sodass alle Folien erhalten bleiben?
2. Falls die API dafür ein eigenes Feld erwartet: welches? `CreatePostDTO` in
   `apps/social-media-posting.json` kennt nur `tiktokPostDetails` und
   `gmbPostDetails`, nichts Vergleichbares für Instagram, Facebook oder LinkedIn.
3. Ist das Verhalten bekannt, und ist eine Korrektur geplant?
4. Welche Darstellung ist maßgeblich für die Veröffentlichung: der über die API
   sichtbare Datensatz (1 Medium) oder die Oberfläche (6 Folien)? Anders gefragt:
   wenn der Post morgen ausgeliefert wird, erscheint dann eine Bildstrecke oder
   ein Einzelbild?
