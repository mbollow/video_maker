# Karussell-Assets

## icons/
Kuratierter Subset von [Lucide](https://lucide.dev) (Line-Icons, **ISC-Lizenz**).
Jedes SVG nutzt `stroke="currentColor"` — die Innen-Slide-Vorlage färbt sie über
`color` (Icon-Teal `#6edbd7`). Neue Motive einfach dazulegen:

```bash
curl -sfL https://unpkg.com/lucide-static@latest/icons/<name>.svg \
  -o video-use/helpers/karussell_assets/icons/<name>.svg
```

## icon-catalog.json
Stichwort → Icon-Name-Fallback. Greift nur, wenn im `outline.txt` kein `icon:`
gepinnt ist und der vom Modell vorgeschlagene Name nicht existiert. Deutsche
Themen-Tokens werden vor dem Match normalisiert (klein, Umlaute → ae/oe/ue/ss).
`default` = Icon, wenn nichts matcht.
