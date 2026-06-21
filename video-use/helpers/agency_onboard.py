#!/usr/bin/env python3
"""
Agency client onboarding — scaffold everything a new client/brand needs so the
existing pipeline produces + posts reels under THEIR brand.

It creates `brand-guidelines/<brand>/` from a template brand, an empty `broll/`
folder for the client's own footage, and a `metricool.json` carrying their
Metricool brand (blog_id) so every batch for this brand posts to THEIR account.

What it does NOT do (intentionally manual — they're per-client judgement calls):
  - swap the logo / colours / tone in the copied brand files (you edit those)
  - build the B-roll catalog (drop the client's clips, then ask Claude
    "Bau den B-Roll-Katalog für <brand>")
  - connect the client's social channels in the Metricool UI

Usage:
    python agency_onboard.py --brand mueller-gmbh --label "Müller GmbH" --blog-id 1234567
    python agency_onboard.py --brand mueller-gmbh --from default --timezone Europe/Zurich
    python agency_onboard.py --brand mueller-gmbh --force      # overwrite existing
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BRANDS_DIR = REPO_ROOT / "brand-guidelines"

BROLL_README = """\
# B-Roll für diese Marke ({brand})

Lege hier die **eigenen Clips dieses Kunden** ab (`.mp4`). Sie haben Vorrang vor
der gemeinsamen `assets/broll/`-Bibliothek — Clips dieser Marke landen NUR in
Reels dieser Marke (keine Vermischung zwischen Kunden).

Nach dem Ablegen: sag Claude **„Bau den B-Roll-Katalog für {brand}"** — dann
werden Frames extrahiert, der Inhalt per Vision beschrieben und `catalog.json`
hier erzeugt. Die Composition-Stage wählt daraus ~alle 10s einen passenden
Cutaway (Keyword-Match gegen das Gesprochene).

Dateinamen müssen NICHT sprechend sein — die Auswahl läuft über `catalog.json`.
Solange dieser Ordner leer ist, fällt die Marke auf reinen Talking-Head zurück.
"""


def _slug_ok(name: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9_-]*", name))


def main() -> None:
    ap = argparse.ArgumentParser(description="Onboard a new agency client/brand.")
    ap.add_argument("--brand", required=True, help="Brand slug (folder name), e.g. mueller-gmbh")
    ap.add_argument("--label", default=None, help="Display name, e.g. 'Müller GmbH' (default: brand slug)")
    ap.add_argument("--blog-id", dest="blog_id", default=None, help="Metricool blog_id for this client's brand")
    ap.add_argument("--platforms", default="linkedin",
                    help="Comma-separated platforms this brand posts to (e.g. instagram or instagram,tiktok). Default: linkedin")
    ap.add_argument("--timezone", default="Europe/Zurich", help="Audience timezone (default Europe/Zurich)")
    ap.add_argument("--from", dest="template", default="default", help="Template brand to copy (default: default)")
    ap.add_argument("--force", action="store_true", help="Overwrite if the brand folder already exists")
    args = ap.parse_args()

    if not _slug_ok(args.brand):
        print(f"ERROR: --brand must be a slug [a-z0-9_-], got '{args.brand}'", file=sys.stderr)
        sys.exit(2)

    src = BRANDS_DIR / args.template
    dst = BRANDS_DIR / args.brand
    if not src.is_dir():
        print(f"ERROR: template brand not found: {src}", file=sys.stderr)
        sys.exit(2)
    if dst.exists() and not args.force:
        print(f"ERROR: {dst.relative_to(REPO_ROOT)} already exists (use --force to overwrite)", file=sys.stderr)
        sys.exit(2)

    # 1. Copy the template brand definition (colours/type/SKILL/caption-templates).
    shutil.copytree(src, dst, dirs_exist_ok=args.force)

    # 2. Fresh, empty B-roll folder for the client's own footage.
    broll_dir = dst / "broll"
    broll_dir.mkdir(parents=True, exist_ok=True)
    (broll_dir / "README.md").write_text(BROLL_README.format(brand=args.brand), encoding="utf-8")
    # Don't inherit the template brand's b-roll catalog (it describes OTHER footage).
    stale_catalog = broll_dir / "catalog.json"
    if stale_catalog.exists():
        stale_catalog.unlink()

    # 3. Per-client Metricool config — batch_init reads this into every batch's
    #    manifest.metricool.default_blog_id, so pushes land on THIS client's brand.
    plats = [p.strip() for p in args.platforms.split(",") if p.strip()]
    valid = {"linkedin", "instagram", "tiktok", "youtube"}
    bad = [p for p in plats if p not in valid]
    if bad:
        print(f"ERROR: unknown platform(s) {bad}. Valid: {sorted(valid)}", file=sys.stderr)
        sys.exit(2)
    metricool = {
        "label": args.label or args.brand,
        "blog_id": int(args.blog_id) if (args.blog_id and args.blog_id.isdigit()) else args.blog_id,
        "timezone": args.timezone,
        "enabled_platforms": plats,
        "_comment": "blog_id = Metricool brand id (from the Metricool UI URL ?blogId=...). "
                    "enabled_platforms = which channels of this brand to post to (batch_init reads it). "
                    "Used by metricool_push.py via the batch manifest.",
    }
    (dst / "metricool.json").write_text(json.dumps(metricool, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    rel = dst.relative_to(REPO_ROOT)
    print(f"✓ Onboarded brand '{args.brand}' → {rel}")
    print(f"  • metricool.json: blog_id={metricool['blog_id']!r}, tz={args.timezone}, platforms={plats}")
    print(f"  • {rel}/broll/  (empty — drop the client's clips here)")
    print()
    print("NÄCHSTE SCHRITTE (manuell, pro Kunde):")
    print(f"  1. Marke anpassen in {rel}/ — Logo, Farben (colors_and_type.css), Ton (SKILL.md/README.md), Caption-Templates.")
    if not args.blog_id:
        print(f"  2. Metricool: Brand anlegen + Kanäle verbinden → blog_id in {rel}/metricool.json eintragen.")
    else:
        print("  2. Metricool: sicherstellen, dass die Kanäle dieser Brand verbunden sind.")
    print(f"  3. B-Roll des Kunden nach {rel}/broll/ legen → Claude: „Bau den B-Roll-Katalog für {args.brand}\".")
    print(f"  4. Erste Batch: npm run batch:init -- --batch <name> --brand {args.brand}")
    print("  Vollständige Checkliste: agency/ONBOARDING.md")


if __name__ == "__main__":
    main()
