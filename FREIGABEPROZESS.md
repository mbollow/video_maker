# Freigabe-/QS-Prozess über SharePoint

Halb-manueller Freigabe-Workflow: geschnittene Videos werden zur Review an eine
Kollegin (Juliana) gegeben, ohne dass sie Zugriff auf den Mac braucht. Läuft
über einen **OneDrive-synchronisierten SharePoint-Ordner** — keine API, keine
Cloud-Integration nötig.

## Überblick

```
 [Mac, lokal]                    [SharePoint / OneDrive]              [Juliana]
 freigabe:push   ──hochladen──▶  Freigabeprozess – Video/   ──ansehen──▶  schaut
                                   NNN_<titel>/                            original
                                   original – <kamera>.mov                 + final
                                   final_vN__<titel>.mp4                   trägt Status
                                   FREIGABE__<titel>.txt ◀──ausfüllen──    + Notizen ein
 freigabe:check  ◀──einlesen───  FREIGABE*.txt (Status)
 re-cut + push   ──final_v2──▶   ...
```

## Zielordner

Standard (überschreibbar via Umgebungsvariable `FREIGABE_DIR`):

```
/Users/marc/Library/CloudStorage/OneDrive-FreigegebeneBibliotheken–PalstekGmbH/
  Palstek GmbH - Gäste - General/Social_Media_Prototyp/Freigabeprozess – Video
```

Der Zusatz „– Video" trennt den Video-Track von einem späteren Track für
Bild-Posts (z.B. `Freigabeprozess – Bild`).

Voraussetzung: Diese SharePoint-Bibliothek muss per OneDrive auf den Mac
synchronisiert sein (erscheint dann als normaler lokaler Ordner).

## Ordner pro Video

```
Freigabeprozess – Video/
  007_dein-bester-mitarbeiter-hat-gekuendigt/
    original – IMG_5402 2.mov            # Original, Name = Kameradatei
    final_v1__dein-bester-mitarbeiter.mp4 # der Cut (v2, v3 … bei Re-Cut)
    captions__dein-bester-mitarbeiter.txt # LinkedIn + Instagram (inkl. Hashtags)
    FREIGABE__dein-bester-mitarbeiter.txt # Status + Anmerkungen (Juliana füllt aus)
    .meta.json                           # versteckter Pointer (batch/seq) — ignorieren
```

- **Nummer global fortlaufend** über alle Batches (`007` = das 7. je hochgeladene Video).
- **Beschreibung** aus dem LinkedIn-Hook (erste Caption-Zeile), damit man am
  Ordnernamen sofort sieht, worum es geht.
- **Dateinamen** tragen denselben Kurztitel als Suffix, damit man sie in VLC /
  Texteditor nicht verwechselt (nicht 12× „FREIGABE.txt"). Die Original-Datei
  behält stattdessen ihren **Kameranamen**, damit die Quelle erkennbar bleibt.

## So füllt Juliana die `FREIGABE.txt` aus

Die Datei hat in Zeile 1 immer `STATUS: OFFEN`. Juliana ersetzt `OFFEN` durch:

- **`FREIGEGEBEN`** — alles passt, Video kann raus.
- **`AENDERN`** — etwas soll geändert werden; Anmerkungen einfach drunter schreiben.

Speichern, fertig. (Toleriert auch `ÄNDERN`, `OK`, `fertig` etc.)
Will sie am Text feilen, darf sie `captions.txt` direkt bearbeiten.

## Befehle

```bash
# Hochladen (Phase 6b im Batch-Workflow):
npm run freigabe:push -- --batch <name>
npm run freigabe:push -- --batch <name> --dry-run   # zeigt nur, was passieren würde

# Rückmeldungen einlesen:
npm run freigabe:check                # alle Batches
npm run freigabe:check -- --batch <name>
npm run freigabe:check -- --json      # maschinenlesbar
```

`freigabe:check` gruppiert nach Status und zeigt bei `AENDERN` die Notizen
verbatim plus die `[batch/seq]`-Referenz. Claude übersetzt die Anmerkungen ins
Korrektur-Shorthand (siehe `CLAUDE.md`), re-cuttet und pusht erneut.

## Sicherheitsregeln (im Skript erzwungen)

- **`FREIGABE…txt` und `captions…txt` werden nie überschrieben** — sonst gingen
  Julianas Notizen verloren. Neue Caption-Versionen landen als `captions_vN__…txt`.
  (Erkennung per Glob `FREIGABE*.txt` / `captions*.txt` — auch alte, suffixlose
  Namen werden noch gefunden.)
- **Jeder neue Schnitt = `final_vN__…mp4` daneben**, der alte bleibt erhalten.
- **Es wird nie etwas gelöscht** (weder Ordner noch alte Fassungen).
- Re-Push eines unveränderten Videos macht nichts (`(aktuell, nichts zu tun)`).
