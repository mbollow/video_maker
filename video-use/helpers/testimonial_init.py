"""Testimonial Phase 1: Scaffold + Transkript + kuratierbare interview.txt.

Nimmt die Roh-Aufzeichnung eines Kunden-Interviews und leitet daraus einen
Vorschlag ab, den der Mensch danach in Ruhe kuratiert:

  1. Projektordner anlegen, Quelle hineinkopieren
  2. Transkription mit Sprecher-Trennung (Scribe, diarize) — Whisper verschluckt Woerter
  3. Bildgeometrie (Sprecher-Band der Teams/Zoom-Galerie) automatisch erkennen
  4. Sprecher-Turns -> Frage/Antwort-Paare -> interview.txt

Wichtig zur Quelle: Wenn mehrere Rohdateien vorliegen (Cloud-Aufzeichnung vs.
Bildschirm-Mitschnitt), nimm die **saubere Meeting-Aufzeichnung** — der Mitschnitt
zeigt die Teams-Bedienleiste. Vorher Anfang+Ende beider Dateien kurz vergleichen,
um Vollstaendigkeit/Versatz zu klaeren.

Usage:
    uv run --project ./video-use python ./video-use/helpers/testimonial_init.py \
        --projekt testimonial-mustermann --quelle "/pfad/zur/aufzeichnung.mp4" \
        [--brand default] [--interviewer-zuerst]
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import testimonial_common as tc  # noqa: E402

MIN_ANSWER_S = 6.0    # kuerzere Gast-Turns sind Einwuerfe ("Ja.", "Sehr gerne."), keine Antworten
MIN_QUESTION_S = 2.0


def transcribe(video: Path, project: Path) -> dict:
    out = project / "transcripts" / f"{video.stem}.json"
    if not out.exists():
        subprocess.run([sys.executable, str(tc.HELPERS / "transcribe.py"), str(video),
                        "--edit-dir", str(project), "--engine", "scribe",
                        "--num-speakers", "2", "--language", "de"], check=True)
    return json.loads(out.read_text())


def speaker_turns(words: list[dict]) -> list[dict]:
    turns, cur = [], None
    for w in words:
        sp = w.get("speaker_id", "?")
        if cur is None or sp != cur["speaker"]:
            cur = {"speaker": sp, "start": w["start"], "end": w["end"], "words": [w["text"]]}
            turns.append(cur)
        else:
            cur["end"] = w["end"]
            cur["words"].append(w["text"])
    for t in turns:
        t["text"] = " ".join(t["words"])
    return turns


def guess_roles(turns: list[dict]) -> tuple[str, str]:
    """Interviewer = shorter turns overall, Gast = the one doing the talking."""
    total: dict[str, float] = {}
    for t in turns:
        total[t["speaker"]] = total.get(t["speaker"], 0.0) + (t["end"] - t["start"])
    if len(total) < 2:
        sys.exit("Diarisierung hat nur einen Sprecher gefunden — --num-speakers pruefen.")
    gast = max(total, key=total.get)
    interviewer = min(total, key=total.get)
    return interviewer, gast


def pair_qa(turns: list[dict], interviewer: str, gast: str) -> list[dict]:
    """Every substantial Gast turn preceded by an Interviewer turn = one Q&A pair."""
    pairs = []
    for i, t in enumerate(turns):
        if t["speaker"] != gast or (t["end"] - t["start"]) < MIN_ANSWER_S:
            continue
        q = None
        for j in range(i - 1, -1, -1):
            if turns[j]["speaker"] == interviewer and (turns[j]["end"] - turns[j]["start"]) >= MIN_QUESTION_S:
                q = turns[j]
                break
            if turns[j]["speaker"] == gast:
                break
        pairs.append({"frage": q, "antwort": t})
    return pairs


def shorten(text: str, limit: int = 150) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def write_interview(path: Path, pairs: list[dict], projekt: str) -> None:
    L = [
        f"# Testimonial — {projekt}",
        "#",
        "# Das ist ein VORSCHLAG aus der automatischen Sprecher-Trennung. Bitte kuratieren:",
        "#   - 'text:' ist die Frage, wie sie auf der FOLIE steht. Kurz und sauber ausformulieren!",
        "#     (Die gesprochene Frage ist als '# gesprochen:' danebengestellt — nur zur Orientierung.)",
        "#   - 'highlight:' faerbt diese Worte im Akzent (tuerkis).",
        "#   - 'antwort:' sind die Sekunden aus der Quelle. Mehrere Bereiche mit Komma trennen.",
        "#   - 'status: nein' laesst einen Block weg.",
        "#   - Bloecke duerfen umsortiert, geloescht und ergaenzt werden.",
        "#",
        "# Anrede: Der Gast wird gesiezt. Nur das Publikum wird geduzt (Outro-CTA).",
        "#",
        "# Danach:  npm run testimonial:build -- --projekt " + projekt,
        "",
        "[intro]",
        "name: <Vorname Nachname>",
        "rolle: <Position · Firma>",
        "meta: im Gespräch mit <Interviewer:in, Firma>",
        "eyebrow: Kundenstimme",
        "",
    ]
    if pairs and pairs[0]["frage"]:
        q = pairs[0]["frage"]
        L += ["# Optional: die Begruessung der Interviewerin (Sekunden anpassen!).",
              "[begruessung]",
              f"quelle: {q['start']:.2f}-{min(q['start'] + 2.5, q['end']):.2f}",
              "status: nein",
              ""]
    for n, p in enumerate(pairs, 1):
        q, a = p["frage"], p["antwort"]
        L.append(f"[frage {n:02d}]")
        if q:
            L.append(f"# gesprochen: {shorten(q['text'])}")
        L += [
            f"text: {shorten(q['text'], 90) if q else '<Frage ausformulieren>'}",
            "highlight: ",
            f"antwort: {a['start']:.2f}-{a['end']:.2f}",
            "status: ja",
            "",
        ]
    L += [
        "# Optional: Schluss-Statement des Gastes (eigene Folie, keine Nummer).",
        "[fazit]",
        "pill: Fazit",
        "text: Und was bleibt, Herr/Frau <Nachname>?",
        "highlight: was bleibt",
        "antwort: ",
        "status: nein",
        "",
        "# Optional: Dank + Verabschiedung. Interne Absprachen NICHT mitnehmen.",
        "[abschluss]",
        "quelle: ",
        "status: nein",
        "",
        "[outro]",
        "eyebrow: Danke, Herr/Frau <Nachname>!",
        "text: Wie steht es um euer Team?",
        "highlight: euer Team",
        "cta: Lernen wir uns kennen. Erstgespraech vereinbaren:",
        "url: palstek-gmbh.de/termin",
        "",
    ]
    path.write_text("\n".join(L))


def main() -> None:
    ap = argparse.ArgumentParser(description="Testimonial Phase 1 — Scaffold + Transkript + interview.txt")
    ap.add_argument("--projekt", required=True, help="Projektname, z.B. testimonial-mustermann")
    ap.add_argument("--quelle", required=True, help="Pfad zur Roh-Aufzeichnung (saubere Cloud-Aufnahme)")
    ap.add_argument("--brand", default="default")
    ap.add_argument("--force", action="store_true", help="interview.txt neu schreiben (ueberschreibt Kuration!)")
    args = ap.parse_args()

    src = Path(args.quelle).expanduser()
    if not src.exists():
        sys.exit(f"Quelle nicht gefunden: {src}")

    proj = tc.project_dir(args.projekt)
    for sub in ("assets", "transcripts", "cards", "work", "renders"):
        (proj / sub).mkdir(parents=True, exist_ok=True)

    dest = proj / "assets" / "source.mp4"
    if not dest.exists():
        print(f"  [init] kopiere Quelle -> {dest}")
        shutil.copy2(src, dest)

    data = transcribe(dest, proj)
    words = [w for w in data["words"] if w.get("type") == "word"]
    turns = speaker_turns(words)
    interviewer, gast = guess_roles(turns)
    pairs = pair_qa(turns, interviewer, gast)
    band = tc.detect_band(dest)
    print(f"  [init] Sprecher: interviewer={interviewer}  gast={gast}")
    print(f"  [init] {len(pairs)} Frage-Antwort-Paare erkannt")
    print(f"  [init] Sprecher-Band erkannt: {band}  (in testimonial.json pruefen/korrigieren)")

    tc.save_config(args.projekt, {
        "projekt": args.projekt,
        "brand": args.brand,
        "quelle": "assets/source.mp4",
        "original": str(src),
        "sprecher": {"interviewer": interviewer, "gast": gast},
        "band": band,
        "hintergrund": "0xF8F6F2",
        "schnitt": {
            "max_pause_s": 1.2,
            "_hinweis": "Nur Pausen laenger als das werden zusammengezogen. Fuellwoerter bleiben im Ton.",
            "ausnahmen": {},
            "_ausnahmen_hinweis": "Pro Block eine eigene Schwelle, z.B. {\"frage 04\": 2.0}, wenn ein Schnitt als Sprung wirkt.",
        },
        "karten": {"intro_s": 4.0, "frage_s": 3.0, "outro_s": 5.0},
        "schreibweisen": {},
        "_schreibweisen_hinweis": "Eigennamen, die Scribe verhoert: {\"vapa\": \"WAPA\", \"sowang\": \"Suhr\"} — Schluessel klein, ohne Satzzeichen.",
        "textfixes": [],
        "_textfixes_hinweis": "Video-spezifische Untertitel-Korrekturen: [{\"suche\":\"a b c\",\"ersetze\":\"x y\"}]",
    })

    iv = proj / "interview.txt"
    if iv.exists() and not args.force:
        print(f"  [init] {iv} existiert bereits — unveraendert gelassen (--force ueberschreibt).")
    else:
        write_interview(iv, pairs, args.projekt)
        print(f"  [init] geschrieben: {iv}")

    print("\nNaechster Schritt: interview.txt kuratieren, dann")
    print(f"  npm run testimonial:build -- --projekt {args.projekt}")


if __name__ == "__main__":
    main()
