"""Shared helpers for the Karussell (Multi-Slide Image Post) pipeline.

A carousel = one start slide + n inner slides + one end slide, all 1080x1350.
This module mirrors bild_common.py but for the multi-slide format:

  - parse/write the human-edited outline.txt (block format with multi-line text)
  - resolve a Lucide line-icon (name or theme-keyword fallback) to inline SVG
  - assemble the per-slide HTML from the carousel-*.html templates
  - render each slide to PNG via render_image_post.cjs

Photo matching, emphasis-HTML and the render call reuse bild_common; the LLM
calls live in the phase scripts (karussell_outline.py / karussell_build.py).
"""

from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bild_common as bc  # noqa: E402  (norm, match_photo, catalog, _wrap_words, STYLE_CLASS, ...)

REPO_ROOT = bc.REPO_ROOT
HELPERS = bc.HELPERS
TEMPLATES = HELPERS / "composition_templates"
FONTS_DIR = TEMPLATES / "fonts"  # self-hosted variable fonts (deterministic render)
TPL_START = TEMPLATES / "carousel-start.html"
TPL_START_CUTOUT = TEMPLATES / "carousel-start-cutout.html"  # [start] mit foto_cutout: freigestellt auf Verlauf
TPL_INNER = TEMPLATES / "carousel-inner.html"
TPL_END = TEMPLATES / "carousel-end.html"
TPL_OVERVIEW = TEMPLATES / "carousel-overview.html"  # layout: uebersicht (Serien-Teile)
TPL_POSTER = TEMPLATES / "carousel-poster.html"      # layout: poster (Poster-Ausschnitt)
RENDERER = bc.RENDERER
CANVAS_W, CANVAS_H = bc.CANVAS_W, bc.CANVAS_H

ICONS_DIR = HELPERS / "karussell_assets" / "icons"
ICON_CATALOG = HELPERS / "karussell_assets" / "icon-catalog.json"

CAROUSELS_ROOT = REPO_ROOT / "image-carousels"

# Field keys recognised in outline blocks (single-line, except `text`)
FIELD_KEYS = {
    "thema", "eyebrow",  # Vorspann-Meta (gelten für alle Slides)
    "hook", "sub", "titel", "icon", "text", "highlight", "hl_style",
    "bild", "bild_file", "object_pos", "fontscale", "statement",
    "cta", "stock_query", "status", "bild_spiegeln",
    # Sonder-Layouts für Innen-Slides (Serien-Übersicht / Poster-Ausschnitt)
    "layout", "aktiv", "embed_file", "caption", "subhead", "subline", "note",
    "foto_cutout",  # freigestelltes PNG für die Ende-Folie (lokaler Batch-Pfad)
    "foto_file",    # lokales Foto direkt nutzen (Start/Ende), umgeht Katalog/Stock
    "foto_spiegeln",  # Ende-Freisteller horizontal spiegeln (ja/nein)
    "start_fill",   # Start-Cutout-Platzierung: 'full' (randlos) oder 'contain' (default)
}
_FIELD_START_RE = re.compile(r"^(" + "|".join(sorted(FIELD_KEYS)) + r")\s*:", re.IGNORECASE)
_LIST_FIELDS = {"thema", "highlight"}


# ---------- icon resolution --------------------------------------------------

def _icon_slug(name: str) -> str:
    s = (name or "").strip().lower()
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"[^a-z0-9-]", "", s)
    return s


def _load_icon_catalog() -> dict:
    if ICON_CATALOG.exists():
        return json.loads(ICON_CATALOG.read_text())
    return {"default": "lightbulb", "map": {}}


def resolve_icon_svg(name: str | None, thema_tokens: list[str] | None = None,
                     title: str | None = None) -> str:
    """Return inline SVG markup for the best-matching Lucide icon.

    Priority: explicit `name` → theme-keyword catalog match → title-word match →
    catalog default. Always returns a valid <svg> (never raises)."""
    cat = _load_icon_catalog()
    tried: list[str] = []
    if name:
        tried.append(_icon_slug(name))
    # theme-keyword fallback via catalog map
    mapping = cat.get("map", {})
    for tok in (thema_tokens or []):
        hit = mapping.get(bc.norm(tok))
        if hit:
            tried.append(hit)
    # title-word fallback
    for word in re.split(r"[\s,]+", bc.norm(title or "")):
        if word and word in mapping:
            tried.append(mapping[word])
    tried.append(cat.get("default", "lightbulb"))
    for slug in tried:
        p = ICONS_DIR / f"{slug}.svg"
        if p.exists():
            return _strip_svg_comment(p.read_text())
    # last resort: any icon present
    any_icon = next(iter(sorted(ICONS_DIR.glob("*.svg"))), None)
    return _strip_svg_comment(any_icon.read_text()) if any_icon else ""


def _strip_svg_comment(svg: str) -> str:
    return re.sub(r"<!--.*?-->\s*", "", svg, flags=re.DOTALL).strip()


# ---------- text sanitising --------------------------------------------------

# Gedankenstriche (em/en dash, auch als Bindestrich-mit-Spaces) → Komma.
# Wirkt wie ein KI-Fingerabdruck; die Marke schreibt lieber mit Komma.
# Bindestriche IN Komposita (ohne umgebende Spaces) bleiben unangetastet.
_DASH_RE = re.compile(r"\s*[—–]\s*|\s+-\s+")


def no_dashes(s: str) -> str:
    """Ersetze Gedankenstriche durch Kommas; Kompositum-Bindestriche bleiben."""
    return _DASH_RE.sub(", ", s or "")


# ---------- env / freigabe dir ----------------------------------------------

def _optional_env(key: str) -> str | None:
    """Read a key from .env (root + video-use) or the environment; None if unset.
    Unlike bild_common.env_value this never exits. Expandiert ${VAR}-Referenzen
    zentral über transcribe.env_optional."""
    from transcribe import env_optional
    return env_optional(key)


def freigabe_dir() -> str:
    """Carousel review folder: FREIGABE_KARUSSELL_DIR, else FREIGABE_BILDER_DIR."""
    return _optional_env("FREIGABE_KARUSSELL_DIR") or bc.env_value("FREIGABE_BILDER_DIR")


FREIGABE_DIR_ENV = "FREIGABE_KARUSSELL_DIR"


# ---------- logo variants ----------------------------------------------------

def start_logo(brand: str) -> Path:
    """Logo for the cream start slide (dark two-tone wordmark).

    Prefer the official colour logo shipped in the brand assets
    (logo-color.png / logo-horizontal-color.png). Fall back to a derived
    monochrome-dark logo only when no colour asset exists."""
    assets = bc.brand_logo(brand).parent
    for name in ("logo-color.png", "logo-horizontal-color.png"):
        p = assets / name
        if p.exists():
            return p
    return ensure_dark_logo(brand)


def ensure_dark_logo(brand: str) -> Path:
    """Return a dark (brand-#281d67) logo for light backgrounds (start wordmark).

    The shipped logo-horizontal.png is WHITE (made for the teal badge). On the
    cream carousel background it would be invisible, so we derive a monochrome
    dark version once and cache it next to the white logo."""
    white = bc.brand_logo(brand)
    dark = white.parent / "logo-horizontal-dark.png"
    if dark.exists():
        return dark
    if not white.exists():
        return white  # let the caller surface the missing-logo error
    from PIL import Image
    src = Image.open(white).convert("RGBA")
    r, g, b = 0x28, 0x1d, 0x67
    src.putdata([(r, g, b, a) for (_, _, _, a) in src.getdata()])
    dark.parent.mkdir(parents=True, exist_ok=True)
    src.save(dark)
    return dark


# ---------- outline.txt parse / write ---------------------------------------

def _norm_list(val: str) -> list[str]:
    return [t.strip() for t in re.split(r"[,]+", val) if t.strip()]


def parse_outline(path: Path) -> dict:
    """Parse the human-edited outline.txt into a carousel dict.

    Structure::
        {name, thema, eyebrow, slides: [ {kind, seq, ...fields, text_lines?}, ... ]}

    `text:` starts a multi-line block: every following line up to the next
    `[header]` or next known-field line belongs to the body. Blank lines inside
    the body separate paragraphs; single newlines are kept as line breaks.
    """
    if not path.exists():
        sys.exit(f"outline.txt fehlt: {path}\n"
                 f"Erst Phase 1: npm run karussell:outline -- --batch <name> --thema \"...\"")
    meta = {"thema": "", "eyebrow": ""}
    blocks: list[dict] = []
    cur: dict | None = None
    in_text = False
    last_key: str | None = None  # for continuation lines of single-line fields

    for raw in path.read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        # block header
        m_head = re.match(r"^\[([^\]]+)\]\s*$", s)
        if m_head:
            in_text = False
            last_key = None
            cur = {"_id": m_head.group(1).strip().lower(), "_text_lines": []}
            blocks.append(cur)
            continue
        # inside a text block?
        if in_text:
            if _FIELD_START_RE.match(s):
                in_text = False  # fall through to field handling
            else:
                cur["_text_lines"].append(raw)
                continue
        if s.startswith("#") or not s:
            continue
        m = _FIELD_START_RE.match(s)
        if not m:
            # continuation of the previous single-line field (manual wrap)
            if cur is not None and last_key and last_key not in _LIST_FIELDS:
                cur[last_key] = (str(cur.get(last_key, "")) + " " + s).strip()
            continue
        key = m.group(1).lower()
        val = s[m.end():].strip()
        if cur is None:  # preamble (before first block) → meta
            if key in ("thema", "eyebrow"):
                meta[key] = val
            last_key = key
            continue
        if key == "text":
            in_text = True
            last_key = None
            if val:  # inline text on the same line
                cur["_text_lines"].append(val)
            continue
        cur[key] = _norm_list(val) if key in _LIST_FIELDS else val
        last_key = key

    # classify slides
    slides: list[dict] = []
    for b in blocks:
        bid = b.pop("_id")
        text_lines = b.pop("_text_lines")
        if bid in ("start", "cover", "titel"):
            kind, seq = "start", "start"
        elif bid in ("ende", "end", "outro", "cta"):
            kind, seq = "end", "ende"
        else:
            digits = re.sub(r"\D", "", bid)
            kind, seq = "inner", (f"{int(digits):02d}" if digits else bid)
        rec = {"kind": kind, "seq": seq, **b}
        if text_lines:
            rec["text_lines"] = text_lines
        slides.append(rec)

    # order: start, inner (numeric), end
    def sort_key(sl):
        if sl["kind"] == "start":
            return (0, 0)
        if sl["kind"] == "end":
            return (2, 0)
        try:
            return (1, int(sl["seq"]))
        except ValueError:
            return (1, 999)
    slides.sort(key=sort_key)

    eyebrow = meta.get("eyebrow") or meta.get("thema") or ""
    return {"name": path.parent.name, "thema": meta.get("thema", ""),
            "eyebrow": eyebrow, "slides": slides}


OUTLINE_HEADER = """# Karussell — {name}
# thema/eyebrow gelten für ALLE Slides (Eyebrow oben, identisch).
# Blöcke: [start]  → Titel-Slide (Foto + Hook)
#         [01..0n] → Innen-Slides (Nummer, Icon, Titel, Fließtext)
#         [ende]   → Schluss-Statement (Foto + handschriftlicher CTA)
# Frei bearbeiten: Slides streichen, umschreiben, ergänzen, Reihenfolge über [NN].
# Felder: titel, icon (Lucide-Name), highlight (Wörter für Marker-Box, kommagetrennt),
#         hl_style (box|boxdark|farbe|underline), bild (juliana|stock), thema (Bild/Icon-Match),
#         fontscale (z.B. 1.05). text: = mehrzeilig, Leerzeile = neuer Absatz.

thema: {thema}
eyebrow: {eyebrow}

"""


def _indent_text(lines: list[str]) -> str:
    return "\n".join(("  " + l if l.strip() else "") for l in lines)


def write_outline(path: Path, name: str, carousel: dict) -> None:
    parts = [OUTLINE_HEADER.format(name=name, thema=carousel.get("thema", ""),
                                   eyebrow=carousel.get("eyebrow", carousel.get("thema", "")))]
    for sl in carousel.get("slides", []):
        kind = sl.get("kind")
        if kind == "start":
            parts.append("[start]\n")
            parts.append(f"hook: {_oneline(sl.get('hook'))}\n")
            if sl.get("sub"):
                parts.append(f"sub: {_oneline(sl['sub'])}\n")
            if sl.get("highlight"):
                parts.append(f"highlight: {_join(sl['highlight'])}\n")
            parts.append(f"bild: {sl.get('bild', 'juliana')}\n")
            parts.append(f"thema: {_join(sl.get('thema', []))}\n\n")
        elif kind == "end":
            parts.append("[ende]\n")
            parts.append(f"statement: {_oneline(sl.get('statement'))}\n")
            if sl.get("highlight"):
                parts.append(f"highlight: {_join(sl['highlight'])}\n")
            parts.append(f"cta: {_oneline(sl.get('cta') or 'Folge mir, wenn du deine Führung bewusst gestalten willst.')}\n")
            parts.append(f"bild: {sl.get('bild', 'juliana')}\n")
            parts.append(f"thema: {_join(sl.get('thema', []))}\n\n")
        else:
            parts.append(f"[{sl.get('seq')}]\n")
            parts.append(f"titel: {_oneline(sl.get('titel'))}\n")
            parts.append(f"icon: {_oneline(sl.get('icon'))}\n")
            if sl.get("highlight"):
                parts.append(f"highlight: {_join(sl['highlight'])}\n")
            parts.append(f"thema: {_join(sl.get('thema', []))}\n")
            body = sl.get("text_lines") or _paras_to_lines(sl.get("text", ""))
            parts.append("text:\n" + _indent_text(body) + "\n\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(parts), encoding="utf-8")


def _join(v) -> str:
    return ", ".join(v) if isinstance(v, list) else str(v or "")


def _oneline(v) -> str:
    """Collapse whitespace/newlines so a single-line field stays on one line."""
    return " ".join(str(v or "").split())


def _paras_to_lines(text: str) -> list[str]:
    """Turn a possibly \\n-joined text field into outline body lines."""
    if not text:
        return []
    out: list[str] = []
    for para in re.split(r"\n\s*\n", text.strip()):
        for ln in para.splitlines():
            out.append(ln.strip())
        out.append("")  # paragraph separator
    if out and out[-1] == "":
        out.pop()
    return out


# ---------- body / statement / hook HTML ------------------------------------

def paragraphs_from_lines(text_lines: list[str]) -> list[list[str]]:
    """Group body lines into paragraphs (split on blank lines); keep in-paragraph
    line breaks as separate entries."""
    paras: list[list[str]] = []
    cur: list[str] = []
    for raw in text_lines:
        if raw.strip() == "":
            if cur:
                paras.append(cur)
                cur = []
        else:
            cur.append(raw.strip())
    if cur:
        paras.append(cur)
    return paras


def _wrap_words(escaped_line: str, words: list[str], style: str) -> str:
    """Like bild_common._wrap_words, but extends the match to the WHOLE word
    (trailing word chars + one punctuation) so a highlight of „Muster" also boxes
    „Musters" cleanly instead of leaving a stray „s"."""
    for ph in words:
        ph = ph.strip()
        if not ph:
            continue
        pat = re.compile(re.escape(html.escape(ph)) + r"\w*[.,!?;:]?", re.IGNORECASE | re.UNICODE)
        escaped_line = pat.sub(lambda m: bc._emph_span(m.group(0), style), escaped_line)
    return escaped_line


def build_body_html(text_lines: list[str], words: list[str] | None, style: str) -> str:
    """Body paragraphs; each source line becomes a <br>-joined line, chosen words
    wrapped in the emphasis style."""
    words = [w for w in (words or []) if w and w.strip()]
    out: list[str] = []
    for para in paragraphs_from_lines(text_lines):
        # Zeilen eines Absatzes zu Fließtext verbinden (mit Leerzeichen), nicht mit
        # hartem <br>: der Browser bricht per Breite um, `text-wrap: pretty` (CSS)
        # verhindert Einzelwort-Zeilen. Manuelle Umbrüche = nur Autoren-Bequemlichkeit.
        line_html = [_wrap_words(html.escape(no_dashes(l)), words, style) for l in para]
        inner = " ".join(line_html)
        # Widow-Schutz: die letzten zwei Wörter mit geschütztem Leerzeichen binden,
        # damit kein Einzelwort allein in der Schlusszeile landet. Übersprungen, wenn
        # der Absatz mit einem Highlight-<span> endet (dort säße das Leerzeichen im Tag).
        if not inner.endswith("</span>"):
            inner = re.sub(r" (\S+)$", r"&nbsp;\1", inner)
        out.append('<p class="para">' + inner + "</p>")
    return "\n      ".join(out)


def build_lines_html(lines: list[str], words: list[str] | None, style: str) -> str:
    """Centered .lx lines (for start hook / end statement) with word emphasis."""
    words = [w for w in (words or []) if w and w.strip()]
    out: list[str] = []
    for l in [no_dashes(x.strip()) for x in lines if x and x.strip()]:
        inner = _wrap_words(html.escape(l), words, style) if words else html.escape(l)
        out.append(f'<div class="lx">{inner}</div>')
    return "\n      ".join(out)


def build_overview_list_html(items: list[str], active: int, *, now_label: str = "Heute") -> str:
    """Render the series-overview list (.item rows). `active` is 1-based; the
    matching row gets the filled highlight box + a small „Heute"-pill."""
    rows: list[str] = []
    for i, label in enumerate([no_dashes(x.strip()) for x in items if x and x.strip()], start=1):
        cls = "item active" if i == active else "item"
        now = f'<span class="now">{html.escape(now_label)}</span>' if i == active else ""
        rows.append(
            f'<div class="{cls}"><span class="n">{i}</span>'
            f'<span class="t">{html.escape(label)}</span>{now}</div>'
        )
    return "\n      ".join(rows)


# ---------- render -----------------------------------------------------------

def render_slide(*, template: Path, out_png: Path, replacements: dict[str, str],
                 assets: dict[str, Path]) -> None:
    """Fill a carousel template and render it to PNG.

    `replacements` are inline string substitutions (eyebrow, html, icon svg, …).
    `assets` maps a placeholder to a file Path that is copied into the temp work
    dir under a safe local name so the file:// HTML resolves cleanly.
    """
    tmpl = template.read_text()
    work = Path(tempfile.mkdtemp(prefix="karussell_"))
    try:
        filled = tmpl
        # Self-hosted fonts: kopiere sie in den Render-Ordner und löse {{FONTS_DIR}}
        # relativ auf (gleiche Origin wie das HTML → kein CORS, deterministisch).
        if "{{FONTS_DIR}}" in filled and FONTS_DIR.exists():
            fdst = work / "fonts"
            fdst.mkdir(exist_ok=True)
            for pat in ("*.ttf", "*.otf"):
                for f in FONTS_DIR.glob(pat):
                    shutil.copy2(f, fdst / f.name)
            filled = filled.replace("{{FONTS_DIR}}", "fonts")
        for ph, src in assets.items():
            local = f"asset_{_icon_slug(ph)}{src.suffix or '.png'}"
            shutil.copy2(src, work / local)
            filled = filled.replace(ph, local)
        for ph, val in replacements.items():
            filled = filled.replace(ph, val)
        (work / "slide.html").write_text(filled, encoding="utf-8")
        out_png.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["node", str(RENDERER), str(work / "slide.html"), str(out_png),
             str(CANVAS_W), str(CANVAS_H)],
            check=True, cwd=str(REPO_ROOT),
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)
