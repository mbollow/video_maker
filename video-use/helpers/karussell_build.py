"""Phase 2 of the Karussell pipeline: render the slides + captions.

Reads the curated outline.txt, matches start/end photos, asks the Anthropic API
ONCE for balanced line-splits (hook/statement) + platform captions, renders every
slide (start / 01..0n / ende) to PNG, writes manifest.json and auto-pushes to the
review folder.

Usage:
    npm run karussell:build -- --batch recency-effekt
    python helpers/karussell_build.py --batch <name> --only start,03 --force
"""

from __future__ import annotations

import argparse
import html as _html
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import karussell_common as kc  # noqa: E402
import bild_common as bc  # noqa: E402
import bild_stock  # noqa: E402
from bild_hooks import read_brand_voice  # noqa: E402
from bild_build import read_caption_templates  # noqa: E402
from caption_gen import call_anthropic, extract_json  # noqa: E402
from transcribe import _load_env_key  # noqa: E402

DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_CTA = "Folge mir, wenn du deine Führung bewusst gestalten willst."


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _emph_b(text: str, words) -> str:
    """Escape `text` and wrap each highlight word in <b> (teal via template CSS)."""
    out = _html.escape(kc.no_dashes(text or ""))
    for w in (words or []):
        w = (w or "").strip()
        if not w:
            continue
        out = re.sub(re.escape(_html.escape(w)) + r"\w*",
                     lambda m: f"<b>{m.group(0)}</b>", out, flags=re.IGNORECASE)
    return out


def generate_json(prompt: str, *, model: str, api_key: str) -> dict:
    """Anthropic call → JSON with one repair retry (mirrors bild_build)."""
    try:
        return extract_json(call_anthropic(prompt, model=model, api_key=api_key, max_tokens=3000))
    except Exception:
        repair = prompt + (
            "\n\nDeine vorherige Antwort war kein valides JSON. Gib AUSSCHLIESSLICH "
            "valides JSON zurück — keine geraden Anführungszeichen (\") in Texten, "
            "jede caption einzeilig."
        )
        return extract_json(call_anthropic(repair, model=model, api_key=api_key, max_tokens=3000))


def build_prompt(*, carousel: dict, brand_voice: str, templates: dict[str, str],
                 with_captions: bool) -> str:
    start = next((s for s in carousel["slides"] if s["kind"] == "start"), {})
    end = next((s for s in carousel["slides"] if s["kind"] == "end"), {})
    inner = [s for s in carousel["slides"] if s["kind"] == "inner"]
    # compact carousel context for captions
    ctx = [f"THEMA: {carousel.get('thema','')}", f"HOOK: {start.get('hook','')}"]
    for s in inner:
        body = s.get("text") or " ".join(l.strip() for l in s.get("text_lines", []))
        ctx.append(f"[{s['seq']}] {s.get('titel','')}: {body}".strip())
    ctx.append(f"SCHLUSS: {end.get('statement','')}")
    ctx_str = "\n".join(ctx)

    cap_block = ""
    cap_out = ""
    if with_captions:
        cap_block = f"""
Erzeuge zusätzlich Captions für den GESAMTEN Karussell-Post:
- linkedin: formellerer Fließtext (Du-Ansprache), fasst den Bogen an, endet mit CTA
  https://palstek-gmbh.de/termin. Hashtags moderat.
- instagram: gleicher Text auch für Facebook; lockerer, Emojis ok, mehr Hashtags,
  CTA Link in Bio / palstek-gmbh.de/termin.
WICHTIG - Perspektive: Der Post läuft auf Julianas PERSÖNLICHEM Profil. Schreibe
durchgehend in der ICH-Form aus ihrer Sicht. Sie spricht NIE in der dritten Person
über sich selbst (also nicht „Juliana zeigt", „im Profil von Juliana", sondern
„ich zeige", „hier in meinem Profil", „folge mir", „schreib mir").
Nenne das Poster konsequent „Experten-Poster". Weise am Ende darauf hin, dass es das
komplette Experten-Poster mit allen 6 Faktoren zum Ausdrucken per DM gibt.
Erfinde KEINE Fakten, nur die Aussagen des Karussells + Marken-Proof-Points.
Keine geraden Anführungszeichen (") in Caption-Texten; jede caption EINZEILIG.
KEINE Gedankenstriche (— oder –); nutze stattdessen Kommas (wirkt sonst KI-generiert).

## MARKEN-STIMME
{brand_voice}

## LINKEDIN-TEMPLATE
{templates.get('linkedin','')}

## INSTAGRAM-TEMPLATE
{templates.get('instagram','')}
"""
        cap_out = (',\n  "linkedin": {"caption": "...", "hashtags": ["#..."]}'
                   ',\n  "instagram": {"caption": "...", "hashtags": ["#..."]}')

    return f"""Du bereitest die On-Image-Zeilen eines Karussell-Posts der Marke Palstek auf
(Führungskräfte-Coaching, DACH, Du-Ansprache).

KARUSSELL-INHALT (Wortlaut NICHT ändern):
{ctx_str}

Aufgabe:
- start_lines: zerlege den HOOK in 2-4 ausgewogene Display-Zeilen (nur umbrechen, keine Wörter ändern).
- end_lines: zerlege das SCHLUSS-Statement in 2-4 ausgewogene, mittig wirkende Zeilen.
{cap_block}
## OUTPUT — reines JSON, kein Fence, kein Kommentar:
{{"start_lines": ["...", "..."],
  "end_lines": ["...", "..."]{cap_out}}}
"""


def empty_post(enabled: bool) -> dict:
    return {"enabled": enabled, "caption": None, "hashtags": [], "status": "pending"}


def load_or_init_manifest(path: Path, carousel: dict, batch: str, brand: str) -> dict:
    if path.exists():
        return json.loads(path.read_text())
    return {
        "schema_version": "1.0", "kind": "carousel", "batch_name": batch,
        "brand": brand, "brand_path": f"brand-guidelines/{brand}",
        "freigabe_dir_env": "FREIGABE_KARUSSELL_DIR",
        "thema": carousel.get("thema", ""), "eyebrow": carousel.get("eyebrow", ""),
        "created_at": now_iso(), "updated_at": now_iso(),
        "slides": [],
        "posts": {"linkedin": empty_post(True), "instagram": empty_post(True)},
    }


def save_manifest(path: Path, manifest: dict) -> None:
    manifest["updated_at"] = now_iso()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def upsert_slide(manifest: dict, rec: dict) -> None:
    for i, s in enumerate(manifest["slides"]):
        if s["seq"] == rec["seq"]:
            manifest["slides"][i] = {**s, **rec}
            return
    manifest["slides"].append(rec)


def pick_photo(slide: dict, *, source: str, catalog: dict, used: set[str],
               pexels_key, used_stock_ids: set, stock_dir):
    """Return (photo_src_path, object_pos, photo_meta) for a start/end slide."""
    src = bc.norm(slide.get("bild", "")) or source
    if src not in ("juliana", "stock"):
        src = source
    pos_override = (slide.get("object_pos") or "").strip() or None
    if src == "juliana":
        pinned = (slide.get("bild_file") or "").strip()
        if pinned:
            # bestimmtes Foto erzwingen (z.B. schöneres Lächeln; auch KI-Bild ki_NNN.jpg)
            entry = next((b for b in catalog.get("bilder", []) if b.get("file") == pinned), None)
            default_pos = bc._object_pos(entry) if entry else "50% 30%"
            path = bc.resolve_photo(pinned)
            if not path:
                raise RuntimeError(f"Foto nicht in den GF_FOTOS_DIR-Quellen gefunden: {pinned}")
            used.add(pinned)
            object_pos = pos_override or default_pos
            meta = {"source": "juliana", "file": pinned, "object_pos": object_pos,
                    "beschreibung": (entry or {}).get("beschreibung", "")}
            return path, object_pos, meta
        photo = bc.match_photo(slide.get("thema"), catalog, used)
        if not photo:
            raise RuntimeError("kein Foto im Katalog")
        path = bc.resolve_photo(photo["file"])
        if not path:
            raise RuntimeError(f"Foto nicht in den GF_FOTOS_DIR-Quellen gefunden: {photo['file']}")
        used.add(photo["file"])
        object_pos = pos_override or photo["object_pos"]
        meta = {"source": "juliana", "file": photo["file"],
                "object_pos": object_pos, "score": photo.get("score"),
                "beschreibung": photo.get("beschreibung", "")}
        return path, object_pos, meta
    # stock
    query = slide.get("stock_query") or " ".join((slide.get("thema") or [])[:2]) or slide.get("hook") or slide.get("statement") or "leadership"
    pick = bild_stock.fetch_stock(query, pexels_key, used_stock_ids, stock_dir)
    if not pick:
        raise RuntimeError(f"kein Stock-Treffer für '{query}'")
    used_stock_ids.add(pick["id"])
    object_pos = pos_override or "50% 30%"
    meta = {"source": "stock", "provider": "pexels", "id": pick["id"], "query": query,
            "photographer": pick.get("photographer"), "url": pick.get("url"),
            "src_url": pick.get("src_url"), "object_pos": object_pos}
    return pick["path"], object_pos, meta


def main() -> None:
    ap = argparse.ArgumentParser(description="Render a carousel from its outline.txt")
    ap.add_argument("--batch", required=True)
    ap.add_argument("--brand", default="default")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--only", default=None, help="Nur diese Slides, z.B. start,03,ende")
    ap.add_argument("--force", action="store_true", help="(kompat.) alle Slides neu bauen")
    ap.add_argument("--regen-captions", action="store_true",
                    help="Captions neu generieren (Standard: vorhandene behalten)")
    ap.add_argument("--source", choices=["juliana", "stock"], default="juliana",
                    help="Bildquelle für Start/Ende (pro Slide via 'bild:' überschreibbar)")
    ap.add_argument("--no-push", action="store_true", help="Auto-Push in Freigabe überspringen")
    args = ap.parse_args()

    batch_dir = kc.CAROUSELS_ROOT / args.batch
    outline_path = batch_dir / "outline.txt"
    manifest_path = batch_dir / "manifest.json"

    carousel = kc.parse_outline(outline_path)
    slides = carousel["slides"]
    if not slides:
        sys.exit("outline.txt enthält keine Slides.")
    only = {s.strip() for s in args.only.split(",")} if args.only else None

    logo_white = bc.brand_logo(args.brand)
    if not logo_white.exists():
        sys.exit(f"Logo fehlt: {logo_white}")
    logo_dark = kc.start_logo(args.brand)
    catalog = bc.load_catalog(args.brand)
    brand_voice = read_brand_voice(args.brand)
    templates = read_caption_templates(args.brand)
    api_key = _load_env_key("ANTHROPIC_API_KEY")

    manifest = load_or_init_manifest(manifest_path, carousel, args.batch, args.brand)
    manifest["thema"] = carousel.get("thema", manifest.get("thema", ""))
    manifest["eyebrow"] = carousel.get("eyebrow", manifest.get("eyebrow", ""))
    eyebrow = manifest["eyebrow"]

    have_caps = bool(manifest.get("posts", {}).get("linkedin", {}).get("caption"))
    with_captions = args.regen_captions or not have_caps

    # stock only if needed
    needs_stock = args.source == "stock" or any(
        bc.norm(s.get("bild", "")) == "stock" for s in slides if s["kind"] in ("start", "end"))
    pexels_key = _load_env_key("PEXELS_API_KEY") if needs_stock else None
    stock_dir = Path(tempfile.mkdtemp(prefix="karussell_stock_")) if needs_stock else None
    used_stock_ids: set = set()

    print(f"Baue Karussell „{carousel.get('thema','')}\" ({len(slides)} Slides, model={args.model}) ...")
    data = generate_json(build_prompt(carousel=carousel, brand_voice=brand_voice,
                                      templates=templates, with_captions=with_captions),
                         model=args.model, api_key=api_key)
    start_lines = data.get("start_lines") or []
    end_lines = data.get("end_lines") or []

    used_photos: set = set()
    errors = 0
    for sl in slides:
        seq = sl["seq"]
        if only is not None and seq not in only:
            continue
        try:
            style = (sl.get("hl_style") or "box").strip().lower()
            words = sl.get("highlight") or []
            try:
                fs = float(str(sl.get("fontscale", "1")).replace(",", "."))
            except (ValueError, TypeError):
                fs = 1.0
            out_png = batch_dir / "renders" / f"{seq}.png"
            rec = {"seq": seq, "kind": sl["kind"], "render": None}

            if sl["kind"] == "start":
                lines = start_lines or [sl.get("hook", "")]
                hook_html = kc.build_lines_html(lines, words, style)
                if sl.get("sub"):
                    import html as _h
                    hook_html += f'\n      <div class="sub">{_h.escape(sl["sub"])}</div>'
                foto_rel = (sl.get("foto_file") or "").strip()
                if foto_rel:
                    photo_src = (batch_dir / foto_rel).resolve()
                    if not photo_src.exists():
                        raise RuntimeError(f"foto_file nicht gefunden: {foto_rel}")
                    obj_pos = (sl.get("object_pos") or "").strip() or "50% 30%"
                    pmeta = {"source": "local", "file": foto_rel, "object_pos": obj_pos}
                else:
                    photo_src, obj_pos, pmeta = pick_photo(
                        sl, source=args.source, catalog=catalog, used=used_photos,
                        pexels_key=pexels_key, used_stock_ids=used_stock_ids, stock_dir=stock_dir)
                kc.render_slide(template=kc.TPL_START, out_png=out_png,
                                replacements={"{{EYEBROW}}": eyebrow, "{{HOOK_HTML}}": hook_html,
                                              "{{OBJECT_POS}}": obj_pos, "{{FONT_SCALE}}": f"{fs:g}"},
                                assets={"{{LOGO_SRC}}": logo_dark, "{{PHOTO_SRC}}": photo_src})
                rec.update({"lines": lines, "photo": pmeta, "highlight": words, "style": style})

            elif sl["kind"] == "end":
                lines = end_lines or [sl.get("statement", "")]
                stmt_html = kc.build_lines_html(lines, words, style)
                # Ende-Folie zeigt eine FREIGESTELLTE Person auf Teal-Welle.
                # Bevorzugt ein vorbereitetes Cutout-PNG (foto_cutout), sonst
                # Foto-Match (dann sollte das Motiv selbst freigestellt sein).
                cutout_rel = (sl.get("foto_cutout") or "").strip()
                if cutout_rel:
                    photo_src = (batch_dir / cutout_rel).resolve()
                    if not photo_src.exists():
                        raise RuntimeError(f"foto_cutout nicht gefunden: {cutout_rel}")
                    pmeta = {"source": "cutout", "file": cutout_rel}
                else:
                    photo_src, _pos, pmeta = pick_photo(
                        sl, source=args.source, catalog=catalog, used=used_photos,
                        pexels_key=pexels_key, used_stock_ids=used_stock_ids, stock_dir=stock_dir)
                mirror = "scaleX(-1)" if bc.norm(sl.get("foto_spiegeln", "")) in ("ja", "true", "1", "yes") else "none"
                kc.render_slide(template=kc.TPL_END, out_png=out_png,
                                replacements={"{{EYEBROW}}": eyebrow, "{{STATEMENT_HTML}}": stmt_html,
                                              "{{FONT_SCALE}}": f"{fs:g}", "{{CUTOUT_TRANSFORM}}": mirror,
                                              "{{CTA_TEXT}}": kc.no_dashes(sl.get("cta", DEFAULT_CTA))},
                                assets={"{{LOGO_SRC}}": logo_white, "{{PHOTO_SRC}}": photo_src})
                rec.update({"lines": lines, "photo": pmeta, "cta": sl.get("cta", DEFAULT_CTA),
                            "highlight": words, "style": style})

            else:  # inner (Standard oder Sonder-Layout)
                import html as _h
                layout = bc.norm(sl.get("layout", ""))
                if layout in ("uebersicht", "übersicht", "overview", "serie"):
                    # Serien-Übersicht: alle Teile, aktueller hervorgehoben
                    try:
                        active = int(re.sub(r"\D", "", str(sl.get("aktiv", "0"))) or 0)
                    except ValueError:
                        active = 0
                    items = [l.strip() for l in sl.get("text_lines", []) if l.strip()]
                    list_html = kc.build_overview_list_html(items, active)
                    kc.render_slide(template=kc.TPL_OVERVIEW, out_png=out_png,
                                    replacements={"{{EYEBROW}}": eyebrow,
                                                  "{{HEADLINE_HTML}}": _h.escape(sl.get("titel", "")),
                                                  "{{SUBHEAD}}": _h.escape(sl.get("subhead", "")),
                                                  "{{LIST_HTML}}": list_html,
                                                  "{{SUBLINE}}": _emph_b(sl.get("subline", ""), words),
                                                  "{{FONT_SCALE}}": f"{fs:g}"},
                                    assets={"{{LOGO_SRC}}": logo_white})
                    rec.update({"layout": "uebersicht", "titel": sl.get("titel", ""),
                                "aktiv": active})
                elif layout in ("poster", "ausschnitt", "embed"):
                    # Eingebetteter Poster-Ausschnitt (Beleg + Teaser)
                    embed_rel = (sl.get("embed_file") or "").strip()
                    embed_path = (batch_dir / embed_rel).resolve()
                    if not embed_path.exists():
                        raise RuntimeError(f"embed_file nicht gefunden: {embed_rel}")
                    kc.render_slide(template=kc.TPL_POSTER, out_png=out_png,
                                    replacements={"{{EYEBROW}}": eyebrow,
                                                  "{{CAPTION_HTML}}": _emph_b(sl.get("caption", ""), words),
                                                  "{{NOTE}}": _h.escape(sl.get("note", "")),
                                                  "{{FONT_SCALE}}": f"{fs:g}"},
                                    assets={"{{LOGO_SRC}}": logo_white, "{{EMBED_SRC}}": embed_path})
                    rec.update({"layout": "poster", "embed_file": embed_rel})
                else:
                    icon_svg = kc.resolve_icon_svg(sl.get("icon"), sl.get("thema"), sl.get("titel"))
                    title_html = _h.escape(sl.get("titel", ""))
                    body_html = kc.build_body_html(sl.get("text_lines", []), words, style)
                    kc.render_slide(template=kc.TPL_INNER, out_png=out_png,
                                    replacements={"{{EYEBROW}}": eyebrow, "{{NUMBER}}": seq,
                                                  "{{ICON_SVG}}": icon_svg, "{{TITLE_HTML}}": title_html,
                                                  "{{BODY_HTML}}": body_html, "{{FONT_SCALE}}": f"{fs:g}"},
                                    assets={"{{LOGO_SRC}}": logo_white})
                    rec.update({"titel": sl.get("titel", ""), "icon": sl.get("icon", ""),
                                "highlight": words, "style": style})

            rec["render"] = str(out_png.relative_to(kc.REPO_ROOT))
            upsert_slide(manifest, rec)
            save_manifest(manifest_path, manifest)
            print(f"  [{seq}] {sl['kind']:5} → {out_png.relative_to(kc.REPO_ROOT)}")
        except Exception as ex:
            errors += 1
            print(f"  [{seq}] FEHLER: {ex}")

    # captions
    if with_captions:
        li = data.get("linkedin") or {}
        ig = data.get("instagram") or {}
        if li.get("caption"):
            manifest["posts"]["linkedin"] = {**empty_post(True), "caption": kc.no_dashes(li.get("caption")),
                                             "hashtags": li.get("hashtags", [])}
        if ig.get("caption"):
            manifest["posts"]["instagram"] = {**empty_post(True), "caption": kc.no_dashes(ig.get("caption")),
                                              "hashtags": ig.get("hashtags", [])}
    manifest["stages"] = {"built": now_iso(), "captioned": now_iso()}
    save_manifest(manifest_path, manifest)

    if stock_dir:
        # keep downloaded stock? renders already captured — temp dir can go
        shutil.rmtree(stock_dir, ignore_errors=True)

    print(f"\nFertig. {len(manifest['slides'])} Slides im Manifest, {errors} Fehler.")
    print(f"Manifest: {manifest_path.relative_to(kc.REPO_ROOT)}")

    if args.no_push:
        print(f"(--no-push) Freigabe-Push übersprungen. Manuell: npm run karussell:freigabe:push -- --batch {args.batch}")
    elif not errors:
        import subprocess
        print("\nAuto-Push in den Freigabe-Ordner ...")
        rc = subprocess.run([sys.executable, str(kc.HELPERS / "karussell_freigabe_push.py"),
                             "--batch", args.batch]).returncode
        if rc != 0:
            print(f"⚠ Freigabe-Push fehlgeschlagen — manuell: npm run karussell:freigabe:push -- --batch {args.batch}")
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
