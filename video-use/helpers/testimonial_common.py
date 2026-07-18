"""Shared helpers for the Testimonial (Langform-Interview) pipeline.

A testimonial = one recorded interview (Zoom/Teams, question -> answer) turned into
a ~complete, website-embeddable 16:9 video. NOT cut down to 30/60s like a Reel:

    Intro-Folie -> [Begruessung] -> n x (Fragen-Folie -> Antwort) -> [Fazit] -> [Abschluss] -> Outro-Folie

Two rules drive the whole design (learned the hard way on the first one, WAPA/Suhr):

  1. **Das VIDEO wird kaum geschnitten.** Fuellwoerter ("aehm", "halt") und natuerliche
     Denkpausen bleiben drin — jeder Schnitt im Talking-Head ist ein sichtbarer Sprung
     und kostet bei einem 6-Minuten-Vertrauens-Video mehr, als die Straffung bringt.
     Nur Pausen ueber `max_pause_s` werden zusammengezogen, plus die inhaltlich noetigen
     Ausschnitte (Zwischenrufe, interne Absprachen).
  2. **Der UNTERTITEL wird sauber ausformuliert.** Keine Fuellwoerter, keine
     Wortwiederholungen, richtige Grammatik und Schreibweisen. Der Ton bleibt unangetastet.

Geometrie-Hinweis: Eine Teams/Zoom-Galerie ist ~3,56:1 (zwei Kacheln nebeneinander) und
laesst sich NICHT formatfuellend auf 16:9 bringen, ohne Gesichter zu beschneiden. Deshalb
wird das Sprecher-Band freigestellt und mittig auf einen Marken-Hintergrund gesetzt
(ersetzt die schwarzen Balken). Karten und Antworten teilen denselben Rahmen — dadurch
wirken harte Schnitte dazwischen ruhig und es braucht keine Crossfades.

Phasen-Skripte: testimonial_init.py (Scaffold + Transkript + interview.txt)
                testimonial_build.py (Karten + Clips + Zusammenbau + Freigabe-Push)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

HELPERS = Path(__file__).resolve().parent
REPO_ROOT = HELPERS.parent.parent
TEMPLATES = HELPERS / "composition_templates"
TPL_CARD = TEMPLATES / "testimonial-card.html"
RENDERER = HELPERS / "render_image_post.cjs"
PROJECTS = REPO_ROOT / "projects"

CANVAS_W, CANVAS_H = 1920, 1080
FPS = 30

# -------- Untertitel-Reinigung: generische Regeln ----------------------------
# Diese Listen gelten fuer JEDES Interview. Video-spezifische Eingriffe gehoeren
# als `textfixes` in die testimonial.json, nicht hierher.

FILLER = {"ähm", "äh", "ah", "öh", "öhm", "hm", "mhm", "mm", "mmm", "eh", "hmm", "halt"}
FILLER_PHRASES = [["ich", "sag", "mal"], ["sag", "ich", "jetzt", "mal"], ["in", "anführungsstrichen"]]
# Echte Betonung — nicht als Wiederholung zusammenziehen ("Vielen, vielen Dank").
EMPHASIS = {"vielen", "ganz", "sehr"}
# Woerter, die am Satzanfang nur Fuellsel sind.
HEAD_DROP = {"ja", "genau", "also", "mmm", "mhm", "ähm", "äh", "ah", "öh", "okay", "mm"}
# Funktionswoerter, nach denen ein Komma aus einer Sprechpause stammt, nicht aus Grammatik.
FUNC = {"dass", "ein", "eine", "einen", "einem", "und", "oder", "so", "schon", "mehr", "auch",
        "mit", "um", "für", "an", "in", "auf", "zu", "von", "bei", "dann", "noch", "grade",
        "gerade", "jetzt", "genau", "dieses", "diese", "dieser", "aber"}
# Vor diesen Konjunktionen gehoert das Komma hin — nie entfernen.
SUBORD_STRICT = {"dass", "weil", "ob", "wenn", "damit", "obwohl"}
# "'n" -> ein/eine/einen, abhaengig vom Folgewort.
N_BY_NEXT = {"bisschen": "ein", "kanzlei": "eine", "schlüsselstein": "ein",
             "ganz": "ein", "stressigen": "einen", "schwierige": "eine"}


def norm(t: str) -> str:
    return re.sub(r"[^\wäöüß']", "", t.lower())


def _sentence_end(t: str) -> bool:
    return t.rstrip().endswith((".", "!", "?"))


def apply_spellings(toks: list[dict], spellings: dict[str, str]) -> None:
    """Fix single words (names, brands) in place, keeping punctuation.

    Scribe verhoert Eigennamen zuverlaessig ("VAPA" statt WAPA, "Sowang" statt Suhr).
    Die Tabelle ist pro Interview verschieden und steht deshalb in testimonial.json,
    nicht hier. Schluessel = kleingeschrieben ohne Satzzeichen.
    """
    if not spellings:
        return
    for tk in toks:
        b = re.sub(r"[^\wäöüß]", "", tk["t"].lower())
        if b in spellings:
            tk["t"] = spellings[b] + re.sub(r"^[\wäöüß]+", "", tk["t"])


def clean_tokens(words: list[dict], textfixes: list[dict] | None = None,
                 spellings: dict[str, str] | None = None) -> list[dict]:
    """Spoken words -> clean written German, timings preserved per word.

    words: [{"text","start","end"}, ...] (the words that stay AUDIBLE)
    textfixes: per-project [{"suche": "a b c", "ersetze": "x y z"}] — applied on the
        normalised token stream. Gleiche Wortzahl => jedes Wort behaelt seine eigene Zeit
        (sonst laeuft der Untertitel aus dem Takt); sonst teilen sie sich die Spanne.
    spellings: per-project {"vapa": "WAPA", ...} — Eigennamen/Schreibweisen.
    """
    fixes = [([norm(x) for x in f["suche"].split()], f["ersetze"].split())
             for f in (textfixes or [])]
    toks = [{"t": w["text"], "s": w["start"], "e": w["end"], "drop_after": False} for w in words]

    # 1) Fuellwoerter + Fuell-Phrasen streichen; merken, wo etwas wegfiel.
    res: list[dict] = []
    i = 0
    while i < len(toks):
        hit = False
        for ph in FILLER_PHRASES:
            n = len(ph)
            if [norm(x["t"]) for x in toks[i:i + n]] == ph:
                if res:
                    res[-1]["drop_after"] = True
                i += n
                hit = True
                break
        if hit:
            continue
        b = norm(toks[i]["t"])
        if b in FILLER or b == "ja":
            ends = _sentence_end(toks[i]["t"])
            if res:
                res[-1]["drop_after"] = True
                if ends:
                    # haengende Konjunktion ("... und, aehm, ja.") mitstreichen
                    while res and norm(res[-1]["t"]) in {"und", "aber", "oder", "dass", "weil"}:
                        res.pop()
                    if res:
                        res[-1]["t"] = res[-1]["t"].rstrip().rstrip(",") + "."
            i += 1
            continue
        res.append(toks[i])
        i += 1
    toks = res

    # 2) Projekt-spezifische Textfixes (nach der Fuellwort-Entfernung!)
    res, i = [], 0
    while i < len(toks):
        hit = False
        for src, rep in fixes:
            n = len(src)
            if n and [norm(x["t"]) for x in toks[i:i + n]] == src:
                if len(rep) == n:
                    for j, r in enumerate(rep):
                        res.append({"t": r, "s": toks[i + j]["s"], "e": toks[i + j]["e"], "drop_after": False})
                else:
                    s0, e0 = toks[i]["s"], toks[i + n - 1]["e"]
                    for r in rep:
                        res.append({"t": r, "s": s0, "e": e0, "drop_after": False})
                i += n
                hit = True
                break
        if hit:
            continue
        res.append(toks[i])
        i += 1
    toks = res

    # 3) Wiederholungen zusammenziehen — nur wenn die erste ein Komma traegt
    #    (= Versprecher). "Werkzeuge, die die Mitarbeiter nutzen" bleibt korrekt.
    res, i = [], 0
    while i < len(toks):
        if (i + 3 < len(toks) and norm(toks[i]["t"]) == norm(toks[i + 2]["t"])
                and norm(toks[i + 1]["t"]) == norm(toks[i + 3]["t"])
                and toks[i + 1]["t"].rstrip().endswith(",")
                and norm(toks[i]["t"]) not in EMPHASIS):
            i += 2
            continue
        if (res and norm(toks[i]["t"]) == norm(res[-1]["t"])
                and res[-1]["t"].rstrip().endswith(",")
                and norm(toks[i]["t"]) not in EMPHASIS):
            res[-1] = toks[i]
            i += 1
            continue
        res.append(toks[i])
        i += 1
    toks = res

    # 4) Eigennamen/Schreibweisen + "'n"/"'ne" ausschreiben
    apply_spellings(toks, spellings or {})
    for k, tk in enumerate(toks):
        b = norm(tk["t"])
        if b in ("'n", "'ne"):
            nxt = norm(toks[k + 1]["t"]) if k + 1 < len(toks) else ""
            tk["t"] = tk["t"].replace("'ne", "EINE").replace("'n", "EIN")
            tk["t"] = tk["t"].replace("EINE", "eine").replace("EIN", N_BY_NEXT.get(nxt, "ein"))

    # 5) Kommas entfernen, die von gestrichenen Fuellwoertern uebrig blieben
    for k, tk in enumerate(toks[:-1]):
        if not tk["t"].rstrip().endswith(","):
            continue
        nb = norm(toks[k + 1]["t"])
        b = norm(tk["t"])
        if ((b in FUNC or tk["drop_after"]) and nb not in SUBORD_STRICT) or b in {"und", "oder"}:
            tk["t"] = tk["t"].rstrip().rstrip(",")

    # 6) Grossschreibung am Segmentanfang und nach Satzende
    for k, tk in enumerate(toks):
        if k == 0 or _sentence_end(toks[k - 1]["t"]):
            tk["t"] = tk["t"][:1].upper() + tk["t"][1:]
    return toks


# -------- Schnitt ------------------------------------------------------------

def build_ranges(words: list[dict], max_pause_s: float,
                 lead_pad: float = 0.10, tail_pad: float = 0.14,
                 end_pad: float = 0.45, min_seg: float = 1.20) -> list[list[float]]:
    """Keep-ranges in source time. Only pauses longer than max_pause_s are collapsed.

    Segmente unter min_seg werden wieder zusammengefuehrt (Stakkato-Schnitte vermeiden).
    """
    ranges: list[list[float]] = []
    cur = None
    prev = None
    for w in words:
        if cur is None:
            cur = [w["start"] - lead_pad, w["end"]]
        elif w["start"] - prev["end"] > max_pause_s:
            cur[1] = prev["end"] + tail_pad
            ranges.append(cur)
            cur = [w["start"] - lead_pad, w["end"]]
        else:
            cur[1] = w["end"]
        prev = w
    if cur:
        cur[1] = prev["end"] + end_pad
        ranges.append(cur)
    merged: list[list[float]] = []
    for r in ranges:
        if merged and ((r[1] - r[0]) < min_seg or (merged[-1][1] - merged[-1][0]) < min_seg):
            merged[-1][1] = r[1]
        else:
            merged.append([r[0], r[1]])
    return [[round(a, 3), round(b, 3)] for a, b in merged]


def words_in(all_words: list[dict], windows: list[tuple[float, float]],
             speaker: str | None = None, drop_head_filler: bool = True) -> list[dict]:
    out = []
    for a, b in windows:
        for w in all_words:
            if a <= w["start"] and w["end"] <= b + 0.45:
                if speaker and w.get("speaker_id") != speaker:
                    continue
                out.append(w)
    out.sort(key=lambda w: w["start"])
    if drop_head_filler:
        i = 0
        while i < len(out) - 1 and norm(out[i]["text"]) in HEAD_DROP:
            i += 1
        out = out[i:]
    return out


# -------- Untertitel ---------------------------------------------------------

def _srt_time(t: float) -> str:
    h = int(t // 3600); m = int((t % 3600) // 60); s = t % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")


def build_srt(ranges: list[list[float]], tokens: list[dict], max_words: int = 5) -> str:
    """Cues in OUTPUT time (after the ranges are concatenated)."""
    starts, acc = [], 0.0
    for r in ranges:
        starts.append(acc)
        acc += r[1] - r[0]

    def out_t(t: float) -> float:
        for i, r in enumerate(ranges):
            if r[0] - 0.001 <= t <= r[1] + 0.001:
                return starts[i] + (t - r[0])
        for i, r in enumerate(ranges):
            if t < r[0]:
                return starts[i]
        return acc

    cues, chunk = [], []
    for w in tokens:
        chunk.append(w)
        if len(chunk) >= max_words or re.search(r"[.?!]$", w["t"]):
            cues.append(chunk)
            chunk = []
    if chunk:
        cues.append(chunk)
    lines = []
    for i, c in enumerate(cues, 1):
        s, e = out_t(c[0]["s"]), out_t(c[-1]["e"])
        if e <= s:
            e = s + 0.4
        lines.append(f"{i}\n{_srt_time(s)} --> {_srt_time(e)}\n{' '.join(w['t'] for w in c).strip()}\n")
    return "\n".join(lines)


# -------- Bildgeometrie ------------------------------------------------------

def detect_band(video: Path, probe_at: float = 60.0, seconds: float = 4.0) -> dict:
    """Detect the speaker band (Teams/Zoom letterbox) via cropdetect.

    Returns {"w","h","x","y"}. cropdetect zaehlt eingeblendete Namensschilder auf
    schwarzem Grund als Inhalt mit — deshalb wird die Unterkante gegen die
    Helligkeit geprueft und ggf. zurueckgenommen.
    """
    out = subprocess.run(
        ["ffmpeg", "-ss", str(probe_at), "-t", str(seconds), "-i", str(video),
         "-vf", "cropdetect=limit=24:round=2", "-f", "null", "-"],
        capture_output=True, text=True).stderr
    hits = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", out)
    if not hits:
        return {"w": CANVAS_W, "h": CANVAS_H, "x": 0, "y": 0}
    w, h, x, y = (int(v) for v in hits[-1])
    return {"w": w, "h": h, "x": x, "y": y}


def _zoom_curve(z: dict, dur: float) -> str:
    """Zeitkurve des Zoom-Faktors z(t) ueber einen Antwort-Clip (fuenf Phasen).

    `t` startet pro Antwort bei 0 (setpts nach trim/concat — also genau nach der
    vorangestellten Fragen-Folie):

        0 .. start_s            voller Zwei-Shot (Faktor 1)
        .. +ramp_s              Einfahrt auf Faktor z (sine.inOut)
        .. bis Rueckfahrt       gehalten auf dem Gast
        out_ramp_s lang         Ausfahrt zurueck auf 1.0 (sine.inOut)
        letzte end_pad_s        wieder voller Zwei-Shot, bevor der Redeteil endet

    Die Rueckfahrt wird vom Ende her terminiert (`dur`), damit sie unabhaengig
    von der Antwortlaenge immer `end_pad_s` vor Schluss fertig ist.
    """
    s = float(z.get("start_s", 5.0))
    r = max(0.1, float(z.get("ramp_s", 2.5)))
    rout = max(0.1, float(z.get("out_ramp_s", z.get("ramp_s", 2.5))))
    endpad = float(z.get("end_pad_s", 4.0))
    z1 = float(z.get("z", 1.9))

    tin0, tin1 = s, s + r
    tout1 = dur - endpad           # hier ist die Rueckfahrt fertig
    tout0 = tout1 - rout           # hier beginnt sie
    tout0 = max(tout0, tin1)       # bei knappen Clips: Hold darf 0 werden, kein Overlap
    tout1 = max(tout1, tout0 + rout)

    ein = f"(0.5-0.5*cos(PI*(t-{tin0})/{r}))"
    eout = f"(0.5-0.5*cos(PI*({tout1}-t)/{rout}))"
    return (f"if(lt(t,{tin0}),1,"
            f"if(lt(t,{tin1}),1+({z1}-1)*{ein},"
            f"if(lt(t,{tout0}),{z1},"
            f"if(lt(t,{tout1}),1+({z1}-1)*{eout},1))))")


def frame_filter(band: dict, bg: str, logo_h: int = 64, logo_margin: int = 60,
                 logo_top: int = 96, zoom: dict | None = None,
                 dur: float | None = None, vollbild: dict | None = None) -> str:
    """Speaker band -> centred on the brand backdrop, logo top-right.

    Ohne `zoom`: Band in fester Hoehe mittig auf Creme (Zwei-Shot).

    Mit `zoom`: Beim Heranzoomen waechst der Mitschnitt auch in der HOEHE, statt
    den Kopf in das schmale 540er-Band zu quetschen. Umgesetzt als wachsendes
    Band ueber einer Creme-Basis: die UNTERKANTE bleibt fix (damit der
    Untertitel-Streifen unten frei bleibt), das Band waechst nach oben; die
    Leinwand beschneidet den Ueberstand. Der Gast (Suhr) sitzt links, deshalb
    ist das Band links verankert — beim Zoom fuellt seine Kachel das Bild von
    links, die rechte Kachel (Juliana) laeuft aus dem Rahmen. `dur` ist Pflicht
    (fuer die Rueckfahrt-Terminierung). Bewusst NICHT `zoompan` — das blaeht die
    Framezahl auf (17 s -> ~1,5 h) und laesst den Render OOM-sterben.
    """
    w, h, bx, by = band["w"], band["h"], band["x"], band["y"]
    pad_x = max(0, (CANVAS_W - w) // 2)
    pad_y = max(0, (CANVAS_H - h) // 2)
    logo_in = f"[1:v]scale=-1:{logo_h}[logo];"

    if vollbild:
        # Nur der Gast, formatfuellend: seine Kachel (crop) auf volle Breite
        # skaliert und in den oberen Bereich gesetzt; unten bleibt ein
        # Creme-Streifen (sub_strip) fuer die Untertitel im Marken-Look.
        cr = vollbild.get("crop", {})
        cw, ch = int(cr.get("w", w)), int(cr.get("h", h))
        cx, cy = int(cr.get("x", bx)), int(cr.get("y", by))
        strip = int(vollbild.get("sub_strip", 270))
        vh = CANVAS_H - strip                      # Hoehe der Videoflaeche (oben)
        scaled_h = round(ch * CANVAS_W / cw)       # Kachel auf volle Breite
        yoff = vollbild.get("crop_y_offset")
        if yoff is None:
            yoff = max(0, (scaled_h - vh) // 2)    # mittig; via crop_y_offset justierbar
        return (
            f"split[bgsrc][fg];"
            f"[bgsrc]scale={CANVAS_W}:{CANVAS_H},drawbox=x=0:y=0:w={CANVAS_W}:h={CANVAS_H}:color={bg}:t=fill,"
            f"fps={FPS},format=yuv420p[base];"
            f"[fg]crop={cw}:{ch}:{cx}:{cy},scale={CANVAS_W}:-2,crop={CANVAS_W}:{vh}:0:{int(yoff)},"
            f"fps={FPS},format=yuv420p[vid];"
            f"[base][vid]overlay=x=0:y=0[framed];"
            + logo_in +
            f"[framed][logo]overlay=W-w-{logo_margin}:{logo_top}[bl]"
        )

    if not zoom:
        return (f"crop={w}:{h}:{bx}:{by},"
                f"pad={CANVAS_W}:{CANVAS_H}:{pad_x}:{pad_y}:color={bg},fps={FPS},format=yuv420p[base];"
                + logo_in +
                f"[base][logo]overlay=W-w-{logo_margin}:{logo_top}[bl]")
    zt = _zoom_curve(zoom, float(dur or 0.0))
    bottom = pad_y + h   # feste Unterkante des Mitschnitts (Zwei-Shot-Unterkante)
    return (
        f"split[bgsrc][bandsrc];"
        f"[bgsrc]scale={CANVAS_W}:{CANVAS_H},drawbox=x=0:y=0:w={CANVAS_W}:h={CANVAS_H}:color={bg}:t=fill,"
        f"fps={FPS},format=yuv420p[base];"
        f"[bandsrc]crop={w}:{h}:{bx}:{by},scale=w='{w}*({zt})':h='{h}*({zt})':eval=frame[vid];"
        f"[base][vid]overlay=x={pad_x}:y='{bottom}-overlay_h'[framed];"
        + logo_in +
        f"[framed][logo]overlay=W-w-{logo_margin}:{logo_top}[bl]"
    )


# -------- Config / interview.txt --------------------------------------------

def project_dir(projekt: str) -> Path:
    return PROJECTS / projekt


def load_config(projekt: str) -> dict:
    p = project_dir(projekt) / "testimonial.json"
    if not p.exists():
        sys.exit(f"testimonial.json fehlt in {p.parent} — erst 'npm run testimonial:init' laufen lassen.")
    return json.loads(p.read_text())


def save_config(projekt: str, cfg: dict) -> None:
    (project_dir(projekt) / "testimonial.json").write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2) + "\n")


def parse_ranges_field(value: str) -> list[tuple[float, float]]:
    """'49.30-66.60, 70.0-72.5' -> [(49.3, 66.6), (70.0, 72.5)]"""
    out = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        a, b = part.split("-")
        out.append((float(a), float(b)))
    return out


def parse_interview(path: Path) -> list[dict]:
    """Parse the human-curated interview.txt into ordered blocks.

    [block-name]
    feld: wert
    """
    blocks: list[dict] = []
    cur = None
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^\[(.+?)\]$", line)
        if m:
            cur = {"block": m.group(1).strip()}
            blocks.append(cur)
            continue
        if cur is None or ":" not in line:
            continue
        k, v = line.split(":", 1)
        cur[k.strip().lower()] = v.strip()
    return [b for b in blocks if b.get("status", "ja").lower() != "nein"]


# -------- Karten -------------------------------------------------------------

def emphasise(text: str, highlight: str | None) -> str:
    """Wrap the highlight phrase in the accent span (first match, case-insensitive)."""
    import html as _html
    safe = _html.escape(text)
    if not highlight:
        return safe
    hl = _html.escape(highlight.strip())
    if not hl:
        return safe
    return re.sub(re.escape(hl), lambda m: f"<span class='hl'>{m.group(0)}</span>", safe, count=1,
                  flags=re.IGNORECASE)


def card_html(brand_dir: Path, kind: str, fields: dict) -> str:
    """Fill testimonial-card.html. kind: intro | frage | outro"""
    tpl = TPL_CARD.read_text()
    font = REPO_ROOT / "font_kobin_medium/Korbin-Medium.otf"
    logo = brand_dir / "assets/logo-color.png"
    body = {
        "intro": ("<div class='stage'>"
                  "<div class='intro-eyebrow'>{eyebrow}</div>"
                  "<div class='intro-name'>{name}</div>"
                  "<div class='intro-role'>{rolle}</div>"
                  "<div class='intro-meta'>{meta}</div></div>"),
        "frage": ("<div class='eyebrow'>{eyebrow}</div>"
                  "<div class='stage'><span class='numtag'>{pill}</span>"
                  "<div class='q {cls}'>{text}</div><div class='rule'></div></div>"),
        "outro": ("<div class='eyebrow'>{eyebrow}</div>"
                  "<div class='stage'><div class='outro-q'>{text}</div>"
                  "<div class='outro-cta'>{cta}</div>"
                  "<div class='outro-url'>{url}</div></div>"),
    }[kind].format(**fields)
    return (tpl.replace("{{FONT}}", f"file://{font}")
               .replace("{{LOGO}}", f"file://{logo}")
               .replace("{{BODY}}", body))


def render_card(html_str: str, out_png: Path) -> Path:
    tmp = out_png.with_suffix(".html")
    tmp.write_text(html_str)
    subprocess.run(["node", str(RENDERER), str(tmp), str(out_png), str(CANVAS_W), str(CANVAS_H)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    return out_png


# -------- ffmpeg ------------------------------------------------------------

ENC = ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(FPS),
       "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart"]


def build_clip(src: Path, logo: Path, ranges: list[list[float]], srt: Path,
               band: dict, bg: str, sub_style: str, out: Path,
               zoom: dict | None = None, vollbild: dict | None = None) -> Path:
    parts, labels = [], []
    for i, (s, e) in enumerate(ranges):
        parts.append(f"[0:v]trim=start={s}:end={e},setpts=PTS-STARTPTS[v{i}]")
        parts.append(f"[0:a]atrim=start={s}:end={e},asetpts=PTS-STARTPTS[a{i}]")
        labels.append(f"[v{i}][a{i}]")
    dur = sum(e - s for s, e in ranges)   # exakte Clip-Laenge (fuer die Zoom-Rueckfahrt)
    graph = ";".join(parts + [
        f"{''.join(labels)}concat=n={len(ranges)}:v=1:a=1[cv][ca]",
        f"[cv]{frame_filter(band, bg, zoom=zoom, dur=dur, vollbild=vollbild)}",
        f"[bl]subtitles='{str(srt)}':force_style='{sub_style}'[vo]",
        "[ca]loudnorm=I=-16:TP=-1.5:LRA=11,aformat=sample_rates=48000:channel_layouts=stereo[ao]",
    ])
    gp = out.with_suffix(".filter")
    gp.write_text(graph)
    subprocess.run(["ffmpeg", "-y", "-i", str(src), "-i", str(logo),
                    "-filter_complex_script", str(gp), "-map", "[vo]", "-map", "[ao]",
                    *ENC, str(out)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    return out


def build_card_clip(png: Path, out: Path, dur: float,
                    fade_in: bool = False, fade_out: bool = False) -> Path:
    vf = [f"fps={FPS}", "format=yuv420p"]
    if fade_in:
        vf.append("fade=t=in:st=0:d=0.5")
    if fade_out:
        vf.append(f"fade=t=out:st={dur - 0.6:.2f}:d=0.6")
    subprocess.run(["ffmpeg", "-y", "-loop", "1", "-t", str(dur), "-i", str(png),
                    "-f", "lavfi", "-t", str(dur), "-i", "anullsrc=r=48000:cl=stereo",
                    "-vf", ",".join(vf), *ENC, str(out)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    return out


def concat(clips: list[Path], out: Path) -> Path:
    lst = out.parent / "concat.txt"
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in clips))
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c", "copy", "-movflags", "+faststart", str(out)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    return out


def probe(video: Path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration:stream=codec_type,codec_name",
                        "-of", "json", str(video)], capture_output=True, text=True)
    d = json.loads(r.stdout or "{}")
    codecs = {s.get("codec_type"): s.get("codec_name") for s in d.get("streams", [])}
    return {"duration": float(d.get("format", {}).get("duration", 0.0)), "codecs": codecs}


def selfcheck(video: Path, expected_s: float, tol: float = 2.0) -> list[str]:
    """Pflicht vor jedem Deploy: Tonspur vorhanden + Dauer plausibel."""
    info = probe(video)
    problems = []
    if info["codecs"].get("audio") != "aac":
        problems.append(f"Tonspur fehlt oder ist kein aac: {info['codecs']}")
    if info["codecs"].get("video") != "h264":
        problems.append(f"Videospur unerwartet: {info['codecs']}")
    if abs(info["duration"] - expected_s) > tol:
        problems.append(f"Dauer {info['duration']:.1f}s weicht von erwarteten {expected_s:.1f}s ab")
    return problems
