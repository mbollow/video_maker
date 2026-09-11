# Tone of Voice (Vorlage)

Palstek spricht direkt, sachlich und vertrauenswürdig. Kurze, prägnante Sätze setzen auf konkrete Führungsempfehlungen ohne Marketing-Floskeln. Die Sprache ist empathisch, aber nicht weichgespült — sie zeigt, dass Führungskräfte echten Mehrwert und Orientierung bekommen.

**Anrede: Du** — wir duzen konsequent (informell, auf Augenhöhe). Niemals siezen, kein „Ihr“/„Ihre“ als formelle Anrede.

## Wörter, die wir NICHT benutzen
- revolutionär
- Game-Changer
- einzigartig
- disruptiv
- wachstumsstark
- Next-level
- intensiviert

## Eigennamen: „Juliana Wiechert" und „Palstek GmbH"

Die Geschäftsführerin heißt **Juliana Wiechert** — mit *ie*, nicht „Wichert",
„Wichardt" oder „Wichard". Die Firma heißt **Palstek GmbH**, nicht „Palsteck".

**Warum das eine eigene Regel ist:** Beide Namen sprechen die
Transkriptions-Dienste falsch mit, und sie kommen in fast jedem Video vor —
Kunden reden Juliana im O-Ton mit Namen an. Bei Video 016 stand „Frau Wichert"
eingebrannt im Untertitel, und ein falsch geschriebener Nachname fällt genau
den Leuten auf, die sie kennen. Bemerkt wird es erst, wenn das Video fertig ist.

**Wo es automatisch greift:** `video-use/helpers/brand_text.py` (`NAMEN`) wird
von `render.build_master_srt` und `testimonial_build.py` in die Untertitel
gezogen und von `fix_hashtags`/`fix_post` in die Captions. Neue Verhörer dort
ergänzen — nicht pro Projekt in die `edl.json`. Projekt-eigene
`schreibweisen` überschreiben die zentrale Tabelle weiterhin (für Kundennamen).

## CTA-Standard: „Erstgespräch vereinbaren"

Der Handlungsaufruf zum Termin heißt **„Erstgespräch vereinbaren"** — auf der
Website, in Captions, auf End-Cards, Karussell-Endfolien und Bild-Posts.

**So nicht:**
- „kostenlosen Beratungstermin buchen“, „Beratungstermin“, „Beratungsgespräch“
- „Termin buchen“, „Buch dir einen Termin“, „Buch dir dein Erstgespräch“
- Zusätze wie „kostenlos“, „gratis“, „unverbindlich“, „Kostenlos & unverbindlich“

**Warum:** „Beratungstermin buchen“ klingt nach Verkaufsgespräch, und wer den
Preis vorweg betont („kostenlos“, „unverbindlich“), macht das Gespräch selbst
zum Angebot statt zum nächsten Schritt. „Erstgespräch vereinbaren“ beschreibt,
was tatsächlich passiert: zwei Seiten schauen, ob es passt. Dass es nichts
kostet, muss nicht dranstehen — es ist selbstverständlich.

**Formulierungen, die passen:**
- „Erstgespräch vereinbaren: https://palstek-gmbh.de/termin“
- „Lass uns das in einem Erstgespräch anschauen.“
- „Wenn du das für dein Team durchsprechen willst, vereinbare ein Erstgespräch.“
- Instagram, wo kein Link steht: „Erstgespräch vereinbaren, Link in Bio.“

Die URL bleibt unverändert `https://palstek-gmbh.de/termin`.
