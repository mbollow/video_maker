"""Shared helpers for the Bild-Post (Single-Image) pipeline.

Photo matching against catalog.json tags, hooks.txt parse/write, HTML assembly
from the static-post.html template, and the headless render call.

Kept deliberately dependency-light; the LLM calls live in the phase scripts.
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

from transcribe import _load_env_key  # noqa: E402  (reads .env, exits if missing)
from freigabe_push import slugify_hook  # noqa: E402  (reuse the proven slugifier)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HELPERS = Path(__file__).resolve().parent
TEMPLATE = HELPERS / "composition_templates" / "static-post.html"
RENDERER = HELPERS / "render_image_post.cjs"

DEFAULT_OVERLAY = "rgba(78,187,194,0.35)"  # #4ebbc2 @ 35% — Bild-Post-Standard
CANVAS_W, CANVAS_H = 1080, 1350


# ---------- env / paths ------------------------------------------------------

def env_value(key: str) -> str:
    """Read a value from .env (root + video-use). Exits with a clear error if missing."""
    return _load_env_key(key)


def gf_fotos_dir() -> Path:
    return Path(env_value("GF_FOTOS_DIR"))


def brand_logo(brand: str) -> Path:
    return REPO_ROOT / "brand-guidelines" / brand / "assets" / "logo-horizontal.png"


# ---------- catalog + photo matching ----------------------------------------

# theme token -> set of catalog tag values it should match
TOPIC_MAP: dict[str, set[str]] = {
    "fuehrung":     {"selbstbewusst", "glasfassade", "anzug-navy", "ganzkoerper"},
    "autoritaet":   {"selbstbewusst", "glasfassade", "anzug-navy"},
    "auftreten":    {"selbstbewusst", "glasfassade", "anzug-navy"},
    "executive":    {"selbstbewusst", "anzug-navy", "glasfassade"},
    "vertrauen":    {"freundlich", "indoor-warm"},
    "naehe":        {"freundlich", "indoor-warm"},
    "nahbar":       {"freundlich", "indoor-warm"},
    "empathie":     {"freundlich", "indoor-warm"},
    "augenhoehe":   {"freundlich", "indoor-warm"},
    "mensch":       {"freundlich", "indoor-warm"},
    "klarheit":     {"fokussiert", "schreibtisch"},
    "fokus":        {"fokussiert", "schreibtisch", "laptop"},
    "produktivitaet": {"fokussiert", "schreibtisch", "laptop"},
    "struktur":     {"fokussiert", "schreibtisch"},
    "entscheidung": {"selbstbewusst", "fokussiert"},
    "kommunikation": {"telefon", "freundlich"},
    "gespraech":    {"telefon", "freundlich"},
    "feedback":     {"telefon", "freundlich"},
    "dialog":       {"telefon", "freundlich"},
    "veraenderung": {"sonnenbrille", "outdoor-urban"},
    "mut":          {"sonnenbrille", "outdoor-urban", "selbstbewusst"},
    "persoenlich":  {"sonnenbrille", "outdoor-urban"},
    "reflexion":    {"nachdenklich", "treppe"},
    "nachdenken":   {"nachdenklich", "treppe"},
    "frage":        {"nachdenklich", "treppe"},
    "alltag":       {"kaffee", "schreibtisch"},
    "pause":        {"kaffee"},
}

_UMLAUT = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}


def norm(s: str) -> str:
    s = (s or "").lower().strip()
    for k, v in _UMLAUT.items():
        s = s.replace(k, v)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    return s


def theme_tokens(thema) -> list[str]:
    if isinstance(thema, list):
        raw = thema
    else:
        raw = re.split(r"[,\s]+", str(thema or ""))
    return [norm(t) for t in raw if norm(t)]


def expand_tokens(tokens: list[str]) -> set[str]:
    out: set[str] = set()
    for t in tokens:
        out.add(t)
        if t in TOPIC_MAP:
            out |= TOPIC_MAP[t]
    return out


def load_catalog(brand: str) -> dict:
    path = REPO_ROOT / "brand-guidelines" / brand / "gf-fotos" / "catalog.json"
    if not path.exists():
        sys.exit(f"catalog.json fehlt: {path}")
    return json.loads(path.read_text())


def _photo_tagset(p: dict) -> set[str]:
    vals = [p.get("szene"), p.get("outfit"), p.get("stimmung"),
            p.get("crop"), p.get("farbe"), p.get("format")]
    vals += list(p.get("aktion") or [])
    return {norm(v) for v in vals if v}


def _object_pos(p: dict) -> str:
    crop = p.get("crop")
    if crop == "ganzkoerper":
        return "50% 22%"
    if crop == "nahaufnahme":
        return "50% 30%"
    return "50% 32%"


def match_photo(thema, catalog: dict, used: set[str]) -> dict | None:
    """Pick the best-matching, not-yet-used photo for a theme. Returns the
    catalog entry augmented with `object_pos` and `score`, or None if the
    library is empty."""
    bilder = [b for b in catalog.get("bilder", []) if b.get("file") not in used]
    if not bilder:
        # all used → allow reuse rather than fail
        bilder = catalog.get("bilder", [])
    if not bilder:
        return None
    want = expand_tokens(theme_tokens(thema))

    def score(p: dict) -> float:
        s = float(len(want & _photo_tagset(p)))
        if p.get("textraum"):
            s += 0.5
        if p.get("format") == "hoch":
            s += 0.3
        return s

    best = max(bilder, key=score)
    chosen = dict(best)
    chosen["object_pos"] = _object_pos(best)
    chosen["score"] = score(best)
    return chosen


# ---------- hooks.txt parse / write -----------------------------------------

HOOKS_HEADER = (
    "# Bild-Posts — Batch {batch}\n"
    "# typ: hook (knackig/provokant)  |  spruch (zitatartig, auf den Punkt)\n"
    "# Frei bearbeiten: streichen, umschreiben, ergänzen. Nur status: ja wird gebaut.\n"
    "# thema steuert die Foto-Auswahl (Stichwörter), z.B. fuehrung, vertrauen, fokus.\n\n"
)


def _hook_block(idx: int, e: dict) -> str:
    thema = e.get("thema")
    thema_str = ", ".join(thema) if isinstance(thema, list) else str(thema or "")
    return (
        f"[{idx:02d}]\n"
        f"typ: {e.get('typ', 'hook')}\n"
        f"text: {e.get('text', '').strip()}\n"
        f"thema: {thema_str}\n"
        f"status: ja\n\n"
    )


def write_hooks_txt(path: Path, batch: str, entries: list[dict]) -> None:
    parts = [HOOKS_HEADER.format(batch=batch)]
    parts += [_hook_block(i, e) for i, e in enumerate(entries, start=1)]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(parts), encoding="utf-8")


def append_hooks_txt(path: Path, entries: list[dict]) -> int:
    """Append entries after the highest existing [NN] index. Returns first new index."""
    existing = parse_hooks_txt(path)
    start = (max((int(e["seq"]) for e in existing), default=0)) + 1
    blocks = "".join(_hook_block(start + k, e) for k, e in enumerate(entries))
    with path.open("a", encoding="utf-8") as fh:
        fh.write(blocks)
    return start


_FIELD_RE = re.compile(r"^(typ|text|thema|status|bild|highlight|fontscale|stock_query|hl_style)\s*:\s*(.*)$", re.IGNORECASE)


def parse_hooks_txt(path: Path) -> list[dict]:
    """Parse the human-edited hooks.txt into entries. Robust to extra blank
    lines and comments; an entry starts at a [NN] header."""
    if not path.exists():
        sys.exit(f"hooks.txt fehlt: {path}\nErst Phase 1 laufen lassen: npm run bild:hooks -- --batch <name>")
    entries: list[dict] = []
    cur: dict | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("#"):
            continue
        m_head = re.match(r"^\[(\d+)\]", s)
        if m_head:
            if cur:
                entries.append(cur)
            cur = {"seq": f"{int(m_head.group(1)):02d}"}
            continue
        if cur is None:
            continue
        m = _FIELD_RE.match(s)
        if m:
            key, val = m.group(1).lower(), m.group(2).strip()
            if key in ("thema", "highlight"):
                cur[key] = [t.strip() for t in re.split(r"[,]+", val) if t.strip()]
            else:
                cur[key] = val
    if cur:
        entries.append(cur)
    # default fields
    for e in entries:
        e.setdefault("typ", "hook")
        e.setdefault("status", "ja")
        e.setdefault("thema", [])
        e.setdefault("text", "")
    return entries


def is_active(entry: dict) -> bool:
    return norm(entry.get("status", "ja")) in {"ja", "yes", "j", "x", "true"} and bool(entry.get("text", "").strip())


# ---------- HTML assembly + render ------------------------------------------

# Benannte Emphasis-Stile → CSS-Klasse (siehe static-post.html)
STYLE_CLASS = {
    "box": "hl-box",           # Teal-Box, weiße Schrift (Standard)
    "boxdark": "hl-boxdark",   # dunkle #281d67-Box, weiße Schrift
    "farbe": "hl-farbe",       # Wort nur teal eingefärbt
    "underline": "hl-underline",  # Teal-Unterstrich
    "italic": "hl-italic",     # kursiv + teal
    "fett": "hl-fett",         # extra-fett + teal
}
DEFAULT_STYLE = "box"


def _emph_span(inner_html: str, style: str) -> str:
    cls = STYLE_CLASS.get(style, STYLE_CLASS[DEFAULT_STYLE])
    return f'<span class="hl {cls}">{inner_html}</span>'


def _wrap_words(escaped_line: str, words: list[str], style: str) -> str:
    """Betone gewählte Wörter im gewünschten Stil (folgendes Satzzeichen inklusive)."""
    for ph in words:
        ph = ph.strip()
        if not ph:
            continue
        pat = re.compile(re.escape(html.escape(ph)) + r"[.,!?;:]?", re.IGNORECASE)
        escaped_line = pat.sub(lambda m: _emph_span(m.group(0), style), escaped_line)
    return escaped_line


def build_emphasis_html(lines: list[str], typ: str,
                        words: list[str] | None = None, style: str = DEFAULT_STYLE) -> str:
    """Baue die On-Image-Zeilen.

    - words gesetzt → Wort-Betonung im gewählten Stil (einheitliche .lx-Zeilen)
    - hook ohne words → klassische Punchline (letzte Zeile) im gewählten Stil
    - spruch ohne words → schlichte Zeilen
    """
    lines = [l.strip() for l in lines if l and l.strip()]
    if not lines:
        return ""
    words = [w for w in (words or []) if w and w.strip()]
    out: list[str] = []
    if words:
        for l in lines:
            out.append(f'<div class="lx">{_wrap_words(html.escape(l), words, style)}</div>')
    elif typ == "hook":
        head, last = lines[:-1], lines[-1]
        for i, h in enumerate(head[:2]):
            out.append(f'<div class="{"l1" if i == 0 else "l2"}">{html.escape(h)}</div>')
        out.append(f'<div class="l3">{_emph_span(html.escape(last), style)}</div>')
    else:  # spruch ohne Betonung
        cls = ["l1", "l2", "l3"]
        for i, l in enumerate(lines):
            out.append(f'<div class="{cls[min(i, 2)]}">{html.escape(l)}</div>')
    return "\n      ".join(out)


def render_post(*, photo_src: Path, logo_src: Path, hook_html: str, typ: str,
                out_png: Path, overlay: str = DEFAULT_OVERLAY,
                object_pos: str = "50% 30%", font_scale: float = 1.0) -> None:
    """Fill the template and render a 1080x1350 PNG via render_image_post.cjs.

    Works in a temp dir with local copies of photo+logo so the file:// HTML
    resolves cleanly regardless of special characters in the source path.
    """
    tmpl = TEMPLATE.read_text()
    work = Path(tempfile.mkdtemp(prefix="bildpost_"))
    try:
        shutil.copy2(photo_src, work / "photo.jpg")
        shutil.copy2(logo_src, work / "logo.png")
        filled = (tmpl
                  .replace("{{PHOTO_SRC}}", "photo.jpg")
                  .replace("{{LOGO_SRC}}", "logo.png")
                  .replace("{{OVERLAY_RGBA}}", overlay)
                  .replace("{{OBJECT_POS}}", object_pos)
                  .replace("{{TYP_CLASS}}", f"typ-{typ}")
                  .replace("{{FONT_SCALE}}", f"{font_scale:g}")
                  .replace("{{HOOK_HTML}}", hook_html))
        (work / "post.html").write_text(filled, encoding="utf-8")
        out_png.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["node", str(RENDERER), str(work / "post.html"), str(out_png),
             str(CANVAS_W), str(CANVAS_H)],
            check=True, cwd=str(REPO_ROOT),
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)
