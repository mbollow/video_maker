"""Phase 2 of the Bild-Post pipeline: build the image posts.

For every active entry in the curated hooks.txt:
  1. match the best photo from catalog.json (tag overlap, no reuse within a batch)
  2. ask the Anthropic API ONCE for: on-image line split + LinkedIn/Instagram captions
  3. render the 1080x1350 PNG via the static-post.html template
  4. write everything to image-posts/<batch>/manifest.json

Usage:
    npm run bild:build -- --batch juni-fuehrung
    python helpers/bild_build.py --batch <name> --only-seq 03,05 --force
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bild_common as bc
import brand_text as bt  # noqa: E402
import bild_stock  # noqa: E402
from bild_hooks import read_brand_voice  # noqa: E402
from caption_gen import call_anthropic, extract_json  # noqa: E402
from transcribe import _load_env_key  # noqa: E402

DEFAULT_MODEL = "claude-sonnet-4-6"

# Dezent-lebendige Variation: pro Post (nach seq) rotierend, alle on-brand.
# Manuell pro Post via hooks.txt (hl_style / fontscale) überschreibbar.
VARIATION_PRESETS = [
    {"style": "box",       "fontscale": 1.00},
    {"style": "farbe",     "fontscale": 1.06},
    {"style": "underline", "fontscale": 1.00},
    {"style": "box",       "fontscale": 1.10},
    {"style": "boxdark",   "fontscale": 1.00},
    {"style": "italic",    "fontscale": 1.04},
]


def preset_for(seq: str, variation: bool) -> dict:
    if not variation:
        return {"style": "box", "fontscale": 1.0}
    try:
        idx = int(seq) - 1
    except (TypeError, ValueError):
        idx = 0
    return VARIATION_PRESETS[idx % len(VARIATION_PRESETS)]


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_caption_templates(brand: str) -> dict[str, str]:
    base = bc.REPO_ROOT / "brand-guidelines" / brand / "caption-templates"
    out = {}
    for platform in ("linkedin", "instagram"):
        p = base / f"{platform}.md"
        out[platform] = p.read_text() if p.exists() else ""
    return out


def build_post_prompt(*, text: str, typ: str, brand_voice: str,
                      templates: dict[str, str], photo_desc: str) -> str:
    typ_rule = (
        "Es ist ein HOOK (knackig). Teile den Text in 2-3 Display-Zeilen; "
        "die LETZTE Zeile ist die Punchline (sie bekommt die Marker-Box)."
        if typ == "hook" else
        "Es ist ein SPRUCH (zitatartig). Teile den Text in 2-3 ausgewogene, "
        "mittig wirkende Zeilen. Keine Marker-Box."
    )
    return f"""Du bereitest einen Single-Image-Post der Marke Palstek (Führungskräfte-Coaching,
DACH) auf. Durchgehend Du-Ansprache.

ON-IMAGE-TEXT (wird aufs Bild gesetzt, Wortlaut NICHT ändern):
\"{text}\"

{typ_rule}
Zerlege NUR den vorhandenen Wortlaut in Zeilen (keine Wörter hinzufügen/streichen).
Gewähltes Foto (Kontext): {photo_desc}

Erzeuge zusätzlich Captions:
- linkedin: formellerer Fließtext (Du-Ansprache), endet mit CTA-Hinweis
  https://palstek-gmbh.de/termin. Hashtags moderat.
- instagram: gleicher Text wird auch für Facebook genutzt; etwas lockerer, Emojis ok,
  mehr Hashtags. CTA Link in Bio / palstek-gmbh.de/termin.
Erfinde KEINE Fakten — nur die Aussage selbst + Marken-Proof-Points.

Gib zusätzlich `stock_query`: 2-4 ENGLISCHE Stichwörter für ein passendes,
KONZEPTIONELLES Stock-Foto (Metapher, Objekt, Szene, Umgebung). KEINE klar
erkennbare Einzelperson, deren Gesicht so wirken würde, als „hätte sie das
Problem". Beispiele: „Busy ist kein Führungsstil" → "cluttered chaotic desk";
„Schweigen in schwierigen Momenten" → "empty meeting room chairs".

WICHTIG für valides JSON:
- Verwende in caption-Texten KEINE geraden Anführungszeichen ("). Wenn du
  zitieren musst, nutze deutsche Anführungszeichen „ ".
- Jede caption ist EINZEILIG (nutze keine echten Zeilenumbrüche; trenne mit Punkten).

## MARKEN-STIMME
{brand_voice}

## LINKEDIN-TEMPLATE
{templates.get('linkedin', '')}

## INSTAGRAM-TEMPLATE
{templates.get('instagram', '')}

## OUTPUT (reines JSON, kein Fence, kein Kommentar)
- emphasis: 1-2 Schlüsselwörter aus dem On-Image-Text (exakter Wortlaut), die
  visuell hervorgehoben werden — die stärksten/zugespitztesten Wörter.
{{"lines": ["...", "..."],
  "stock_query": "...",
  "emphasis": ["...", "..."],
  "linkedin": {{"caption": "...", "hashtags": ["#..."]}},
  "instagram": {{"caption": "...", "hashtags": ["#..."]}}}}
"""


def build_layout_prompt(*, text: str, typ: str) -> str:
    """Minimaler Prompt: nur Zeilen-Split + Stock-Query (keine Captions).

    Genutzt beim Neubau mit erhaltenen Captions — viel weniger Output,
    dadurch praktisch keine JSON-Fragilität."""
    typ_rule = (
        "HOOK: teile den Text in 2-3 Zeilen, die LETZTE Zeile ist die Punchline."
        if typ == "hook" else
        "SPRUCH: teile den Text in 2-3 ausgewogene, mittig wirkende Zeilen."
    )
    return f"""Single-Image-Post der Marke Palstek. On-Image-Text (Wortlaut NICHT ändern):
\"{text}\"
{typ_rule} Zerlege NUR den vorhandenen Wortlaut (keine Wörter hinzufügen/streichen).

Gib zusätzlich stock_query: 2-4 ENGLISCHE Stichwörter für ein KONZEPTIONELLES
Stock-Foto (Metapher/Objekt/Szene, KEINE erkennbare Einzelperson, deren Gesicht
wirken würde als „hätte sie das Problem").

Gib zusätzlich emphasis: 1-2 SCHLÜSSELWÖRTER aus dem Text (exakter Wortlaut),
die visuell hervorgehoben werden sollen — die stärksten/zugespitztesten Wörter.

OUTPUT reines JSON, kein Fence, kein Kommentar, keine geraden Anführungszeichen in Werten:
{{"lines": ["...", "..."], "stock_query": "...", "emphasis": ["...", "..."]}}
"""


def generate_json(prompt: str, *, model: str, api_key: str) -> dict:
    """Anthropic call → JSON, with one repair retry on parse failure."""
    try:
        return extract_json(call_anthropic(prompt, model=model, api_key=api_key, max_tokens=3000))
    except Exception:
        repair = prompt + (
            "\n\nDeine vorherige Antwort war kein valides JSON. Gib AUSSCHLIESSLICH "
            "valides JSON zurück — keine geraden Anführungszeichen (\") in Texten, "
            "jede caption einzeilig."
        )
        return extract_json(call_anthropic(repair, model=model, api_key=api_key, max_tokens=3000))


def empty_post(enabled: bool) -> dict:
    return {"enabled": enabled, "caption": None, "hashtags": [], "status": "pending"}


def load_or_init_manifest(path: Path, batch: str, brand: str) -> dict:
    if path.exists():
        return json.loads(path.read_text())
    return {
        "schema_version": "1.0",
        "kind": "image",
        "batch_name": batch,
        "brand": brand,
        "brand_path": f"brand-guidelines/{brand}",
        "freigabe_dir_env": "FREIGABE_BILDER_DIR",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "posts": [],
    }


def save_manifest(path: Path, manifest: dict) -> None:
    manifest["updated_at"] = now_iso()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def upsert_post(manifest: dict, record: dict) -> None:
    for i, p in enumerate(manifest["posts"]):
        if p["seq"] == record["seq"]:
            manifest["posts"][i] = {**p, **record}
            return
    manifest["posts"].append(record)


def main() -> None:
    ap = argparse.ArgumentParser(description="Build Bild-Posts from a curated hooks.txt")
    ap.add_argument("--batch", required=True)
    ap.add_argument("--brand", default="default")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--only-seq", default=None, help="z.B. 03,05")
    ap.add_argument("--force", action="store_true", help="Auch schon gebaute Posts neu bauen")
    ap.add_argument("--rate-limit-ms", type=int, default=500)
    ap.add_argument("--no-push", action="store_true",
                    help="Auto-Push in den Freigabe-Ordner überspringen (Standard: pushen)")
    ap.add_argument("--source", choices=["juliana", "stock"], default="juliana",
                    help="Bildquelle für den Batch: juliana (Fotos) oder stock (Pexels). "
                         "Pro Post via 'bild: stock' in hooks.txt überschreibbar.")
    ap.add_argument("--regen-captions", action="store_true",
                    help="Captions beim Neubau neu generieren (Standard: vorhandene behalten)")
    ap.add_argument("--new-image", action="store_true",
                    help="Beim Neubau ein neues Bild wählen (Standard: bestehendes Bild behalten)")
    ap.add_argument("--no-variation", action="store_true",
                    help="Keine Auto-Variation der Stile über den Batch (alle im Standard-Stil 'box')")
    args = ap.parse_args()

    batch_dir = bc.REPO_ROOT / "image-posts" / args.batch
    hooks_path = batch_dir / "hooks.txt"
    manifest_path = batch_dir / "manifest.json"

    entries = [e for e in bc.parse_hooks_txt(hooks_path) if bc.is_active(e)]
    only = {s.strip() for s in args.only_seq.split(",")} if args.only_seq else None
    if only:
        entries = [e for e in entries if e["seq"] in only]
    if not entries:
        sys.exit("Keine aktiven Einträge in hooks.txt (status: ja + Text vorhanden).")

    catalog = bc.load_catalog(args.brand)
    logo = bc.brand_logo(args.brand)
    if not logo.exists():
        sys.exit(f"Logo fehlt: {logo}")
    brand_voice = read_brand_voice(args.brand)
    templates = read_caption_templates(args.brand)
    api_key = _load_env_key("ANTHROPIC_API_KEY")

    # Stock-Quelle: Pexels-Key nur laden, wenn überhaupt Stock gebraucht wird.
    needs_stock = args.source == "stock" or any(
        bc.norm(e.get("bild", "")) == "stock" for e in entries)
    pexels_key = _load_env_key("PEXELS_API_KEY") if needs_stock else None
    stock_dir = Path(tempfile.mkdtemp(prefix="bildpost_stock_")) if needs_stock else None

    manifest = load_or_init_manifest(manifest_path, args.batch, args.brand)
    other_seqs = {e["seq"] for e in entries}
    # photos already used by earlier-built posts (avoid reuse within the batch)
    used = {p.get("photo", {}).get("file") for p in manifest["posts"]
            if p.get("photo", {}).get("file") and p["seq"] not in other_seqs}
    used_stock_ids = {p["photo"]["id"] for p in manifest["posts"]
                      if p.get("photo", {}).get("provider") == "pexels"
                      and p["seq"] not in other_seqs}

    print(f"Baue {len(entries)} Bild-Posts (model={args.model}) ...")
    errors = 0
    for i, e in enumerate(entries, start=1):
        seq = e["seq"]
        existing = next((p for p in manifest["posts"] if p["seq"] == seq), None)
        if existing and existing.get("stages", {}).get("built") and not args.force:
            print(f"  [{seq}] schon gebaut (--force zum Neubauen) — übersprungen")
            pm = existing.get("photo", {})
            if pm.get("file"):
                used.add(pm["file"])
            if pm.get("provider") == "pexels" and pm.get("id") is not None:
                used_stock_ids.add(pm["id"])
            continue
        try:
            source = bc.norm(e.get("bild", "")) or args.source
            if source not in ("juliana", "stock"):
                source = args.source

            # Juliana-Foto wird VOR dem Prompt gematcht (liefert die Bildbeschreibung).
            ex_photo = existing.get("photo", {}) if existing else {}
            photo = None
            if source == "juliana":
                # Gemerktes Foto nur wiederverwenden, wenn es noch im Ordner liegt —
                # KI-Bilder werden punktuell aussortiert, das darf keinen Re-Build brechen.
                reuse = (not args.new_image and ex_photo.get("source") == "juliana"
                         and ex_photo.get("file"))
                if reuse and not bc.resolve_photo(ex_photo["file"]):
                    print(f"  Hinweis: gemerktes Foto {ex_photo['file']} liegt nicht mehr "
                          f"in den Quellordnern — es wird neu gematcht")
                    reuse = False
                if reuse:
                    photo = {"file": ex_photo["file"], "object_pos": ex_photo.get("object_pos", "50% 30%"),
                             "score": ex_photo.get("score"), "beschreibung": ex_photo.get("beschreibung", "")}
                else:
                    photo = bc.match_photo(e.get("thema"), catalog, used)
                    if not photo:
                        raise RuntimeError("kein Foto im Katalog")
                photo_path = bc.resolve_photo(photo["file"])
                if not photo_path:
                    raise RuntimeError(f"Foto nicht in den GF_FOTOS_DIR-Quellen gefunden: {photo['file']}")
                photo_desc = photo.get("beschreibung", "")
            else:
                photo_desc = "(konzeptionelles Stock-Bild, kein Porträt)"

            reuse_caps = bool(existing and not args.regen_captions
                              and existing.get("posts", {}).get("linkedin", {}).get("caption"))
            if reuse_caps:
                prompt = build_layout_prompt(text=e["text"], typ=e["typ"])
            else:
                prompt = build_post_prompt(
                    text=e["text"], typ=e["typ"], brand_voice=brand_voice,
                    templates=templates, photo_desc=photo_desc,
                )
            data = generate_json(prompt, model=args.model, api_key=api_key)
            lines = data.get("lines") or [e["text"]]

            # Bildquelle auflösen
            if source == "juliana":
                used.add(photo["file"])
                photo_src = photo_path
                object_pos = photo["object_pos"]
                photo_meta = {"source": "juliana", "file": photo["file"],
                              "object_pos": object_pos, "score": photo.get("score"),
                              "beschreibung": photo.get("beschreibung", "")}
                src_label = photo["file"]
            else:
                pinned = e.get("stock_query")
                object_pos = "50% 45%"
                reuse_img = (not args.new_image and not pinned
                             and ex_photo.get("provider") == "pexels" and ex_photo.get("src_url"))
                if reuse_img:
                    # Bestehendes Stock-Bild beibehalten (Text-Edit ≠ Bildwechsel)
                    photo_src = bild_stock.download_url(ex_photo["src_url"], stock_dir, ex_photo.get("id", "x"))
                    photo_meta = {**ex_photo, "source": "stock", "object_pos": object_pos}
                    src_label = f"pexels[behalten #{ex_photo.get('id')}]"
                else:
                    query = pinned or data.get("stock_query") or " ".join(e.get("thema", [])[:2]) or e["text"]
                    pick = bild_stock.fetch_stock(query, pexels_key, used_stock_ids, stock_dir)
                    if not pick:
                        raise RuntimeError(f"kein Stock-Treffer für '{query}'")
                    used_stock_ids.add(pick["id"])
                    photo_src = pick["path"]
                    photo_meta = {"source": "stock", "provider": "pexels", "id": pick["id"],
                                  "query": query, "photographer": pick.get("photographer"),
                                  "url": pick.get("url"), "src_url": pick.get("src_url"),
                                  "object_pos": object_pos}
                    src_label = f"pexels[{query}]"

            preset = preset_for(seq, not args.no_variation)
            style = (e.get("hl_style") or preset["style"]).strip().lower()
            # Betonungs-Wörter: manuell (highlight) hat Vorrang vor KI (emphasis)
            words = e.get("highlight") or data.get("emphasis") or []
            # Schriftgröße: manuell (fontscale) hat Vorrang vor Preset
            try:
                font_scale = float(str(e["fontscale"]).replace(",", ".")) if e.get("fontscale") else preset["fontscale"]
            except (ValueError, TypeError):
                font_scale = preset["fontscale"]
            hook_html = bc.build_emphasis_html(lines, e["typ"], words=words, style=style)
            out_png = batch_dir / "renders" / f"{seq}.png"
            bc.render_post(
                photo_src=photo_src, logo_src=logo, hook_html=hook_html, typ=e["typ"],
                out_png=out_png, object_pos=object_pos, font_scale=font_scale,
            )

            li = data.get("linkedin") or {}
            ig = data.get("instagram") or {}
            # Beim Neubau (z.B. nur Bildwechsel) vorhandene Captions behalten,
            # außer --regen-captions wurde gesetzt.
            if existing and not args.regen_captions:
                ex = existing.get("posts", {})
                if ex.get("linkedin", {}).get("caption"):
                    li = {"caption": ex["linkedin"]["caption"], "hashtags": ex["linkedin"].get("hashtags", [])}
                if ex.get("instagram", {}).get("caption"):
                    ig = {"caption": ex["instagram"]["caption"], "hashtags": ex["instagram"].get("hashtags", [])}
            record = {
                "seq": seq,
                "typ": e["typ"],
                "text": e["text"],
                "thema": e.get("thema", []),
                "source": source,
                "photo": photo_meta,
                "lines": lines,
                "style": style,
                "emphasis": words,
                "font_scale": font_scale,
                "render": str(out_png.relative_to(bc.REPO_ROOT)),
                "posts": {
                    "linkedin": bt.fix_post({**empty_post(True), "caption": li.get("caption"),
                                             "hashtags": li.get("hashtags", [])}),
                    "instagram": bt.fix_post({**empty_post(True), "caption": ig.get("caption"),
                                              "hashtags": ig.get("hashtags", [])}),
                },
                "stages": {"built": now_iso(), "captioned": now_iso()},
            }
            if existing and existing.get("freigabe"):
                record["freigabe"] = existing["freigabe"]
            upsert_post(manifest, record)
            save_manifest(manifest_path, manifest)
            print(f"  [{seq}] {e['typ']:6} [{source}] → {src_label} → {out_png.relative_to(bc.REPO_ROOT)}")
        except Exception as ex:
            errors += 1
            print(f"  [{seq}] FEHLER: {ex}")
        if i < len(entries) and args.rate_limit_ms > 0:
            time.sleep(args.rate_limit_ms / 1000.0)

    if stock_dir:
        shutil.rmtree(stock_dir, ignore_errors=True)

    print(f"\nFertig. {len(entries) - errors} ok, {errors} Fehler.")
    print(f"Manifest: {manifest_path.relative_to(bc.REPO_ROOT)}")

    # Auto-Push in den Freigabe-Ordner ist Standard (stehende Regel: der Nutzer/
    # Juliana schauen NUR im Freigabe-Ordner, nie in image-posts/.../renders/).
    built_any = any(p.get("stages", {}).get("built") for p in manifest["posts"])
    if args.no_push:
        print(f"(--no-push) Freigabe-Push übersprungen. Manuell: npm run bild:freigabe:push -- --batch {args.batch}")
    elif built_any:
        import subprocess
        print("\nAuto-Push in den Freigabe-Ordner ...")
        rc = subprocess.run([sys.executable, str(bc.HELPERS / "bild_freigabe_push.py"),
                             "--batch", args.batch]).returncode
        if rc != 0:
            print(f"⚠ Freigabe-Push fehlgeschlagen — manuell: npm run bild:freigabe:push -- --batch {args.batch}")
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
