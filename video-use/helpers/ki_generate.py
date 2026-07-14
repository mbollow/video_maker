"""Batch-Generierung von KI-Juliana-Bildern über ein trainiertes Replicate-Modell.

Ruft dein per `fast-flux-trainer` trainiertes FLUX-Modell N-mal auf (variierte
Prompts + Seeds) und lädt die Bilder herunter — für ein „virtuelles Fotoshooting",
das dann kuratiert in `brand-guidelines/<brand>/gf-ki/` wandern kann.

Voraussetzungen:
  - REPLICATE_API_TOKEN in .env
  - dein trainiertes Modell auf Replicate (Format owner/name), + Trigger-Wort

Usage:
  npm run ki:generate -- --model deinuser/juliana-flux --trigger JULPLSTK --count 50
  python helpers/ki_generate.py --model owner/name --trigger TOK --count 50 \
      --outdir image-ki/juliana-01 --aspect 4:5
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))

from transcribe import _load_env_key  # noqa: E402  (liest .env, exit bei fehlendem Key)

HELPERS = Path(__file__).resolve().parent
REPO_ROOT = HELPERS.parent.parent
API = "https://api.replicate.com/v1"

# Zweckgebundene FLUX-LoRAs: Modell + Trigger gehören paarweise zusammen (eine LoRA =
# ein Modell + ein Trigger-Wort). Defaults werden aus der .env gezogen (siehe --subject).
SUBJECTS = {
    "juliana": {
        "model_env": "REPLICATE_MODEL_JULIANA",
        "trigger_env": "REPLICATE_TRIGGER_JULIANA",
        "outdir_env": "KI_JULIANA_OUTDIR",
        "prompt_file": HELPERS / "prompts" / "juliana_ki_prompts.txt",
        "prefix": "ki",
    },
    "icons": {  # kommt später — .env-Paar ist noch auskommentiert
        "model_env": "REPLICATE_MODEL_ICONS",
        "trigger_env": "REPLICATE_TRIGGER_ICONS",
        "outdir_env": "KI_ICONS_OUTDIR",
        "prompt_file": HELPERS / "prompts" / "icons_ki_prompts.txt",
        "prefix": "icon",
    },
}


def _disp(p: Path) -> str:
    """Repo-relativer Pfad, falls möglich — sonst absolut (z.B. OneDrive außerhalb)."""
    try:
        return str(p.relative_to(REPO_ROOT))
    except ValueError:
        return str(p)


def _env_opt(key: str, default: str = "") -> str:
    """Optionaler .env-Lookup OHNE exit (Gegenstück zu transcribe._load_env_key).
    Sucht dieselben .env-Dateien; leer/fehlend → default."""
    for candidate in (HELPERS.parent / ".env", REPO_ROOT / ".env", Path(".env")):
        if not candidate.exists():
            continue
        for line in candidate.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == key:
                v = v.strip().strip('"').strip("'")
                if v:
                    return v
    return os.environ.get(key, default) or default


def _next_index(outdir: Path, prefix: str) -> int:
    """Nächste freie Nummer für <prefix>_NNN.jpg — echt monoton steigend.
    Berücksichtigt sowohl vorhandene Dateien ALS AUCH das manifest.jsonl, damit
    eine (beim Kuratieren gelöschte) Nummer nie wiederverwendet wird — Neuzugänge
    bleiben so sofort erkennbar."""
    pat = re.compile(rf"^{re.escape(prefix)}_(\d+)\.jpe?g$", re.IGNORECASE)
    highest = 0
    if outdir.exists():
        for f in outdir.iterdir():
            m = pat.match(f.name)
            if m:
                highest = max(highest, int(m.group(1)))
    manifest = outdir / "manifest.jsonl"
    if manifest.exists():
        for line in manifest.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                fn = json.loads(line).get("file", "")
            except (ValueError, TypeError):
                continue
            m = pat.match(fn)
            if m:
                highest = max(highest, int(m.group(1)))
    return highest + 1

# Variierte, on-brand Prompt-Bausteine (Palstek: Führungskräfte-Coaching).
# {trigger} = dein Trainings-Trigger-Wort. Framing/Wardrobe/Mood variiert;
# die IDENTITÄT trägt das Trigger-Wort (nicht die Beschreibung).
PROMPTS = [
    "professional headshot of {trigger}, a businesswoman with glasses, navy blazer, modern bright office, warm genuine smile, looking at camera, natural window light, shot on 85mm, photorealistic",
    "{trigger}, a female executive coach, sitting at a desk with a laptop, thoughtful confident expression, bright minimalist office, soft daylight, professional photography, photorealistic",
    "{trigger}, businesswoman in a light blazer, standing with arms lightly crossed, friendly approachable smile, blurred office background, corporate portrait, natural light, photorealistic",
    "candid photo of {trigger} in a coaching conversation, gesturing while explaining, warm engaged expression, modern meeting room, soft light, documentary style, photorealistic",
    "{trigger}, leadership coach, holding a coffee mug near a large window, calm reflective mood, morning light, lifestyle business portrait, photorealistic",
    "{trigger}, professional woman with glasses, white blouse and dark blazer, seated, hands relaxed, confident warm smile, clean neutral background, studio portrait, photorealistic",
    "{trigger} walking through a bright modern office corridor, business casual, subtle smile, motion candid, natural light, editorial style, photorealistic",
    "{trigger}, businesswoman presenting at a flipchart in a workshop, mid-gesture, engaged expression, bright seminar room, photorealistic",
    "close-up portrait of {trigger}, warm authentic smile, glasses, soft bokeh office background, golden hour light, premium corporate photography, photorealistic",
    "{trigger}, female business coach, leaning against a brick wall outside a modern building, relaxed confident, urban daylight, environmental portrait, photorealistic",
    "{trigger} at a standing desk with notebook, focused thoughtful look, contemporary office with plants, soft daylight, photorealistic",
    "{trigger}, businesswoman in a burgundy blouse and blazer, seated in a lounge chair, friendly open expression, warm interior, lifestyle portrait, photorealistic",
    "{trigger}, professional woman, three-quarter view, subtle confident smile, neutral studio backdrop, even soft lighting, LinkedIn-style headshot, photorealistic",
    "{trigger} in conversation across a table, listening attentively, empathetic expression, bright cafe-like meeting space, candid, photorealistic",
    "{trigger}, leadership coach, arms resting on a table, hands clasped, calm assured expression, minimalist office, soft directional light, photorealistic",
    "{trigger}, businesswoman with glasses, smiling while looking slightly off camera, bright airy office, natural light, authentic corporate lifestyle, photorealistic",
]

NEGATIVE_HINT = "no text, no watermark, no distorted hands, natural skin"


def headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def resolve_version(model: str, token: str) -> str:
    """Akzeptiert owner/name ODER owner/name:VERSION. Bei explizit angegebener
    Version wird diese direkt genutzt, sonst die neueste Version geholt."""
    if ":" in model:
        return model.split(":", 1)[1]
    owner, _, name = model.partition("/")
    if not owner or not name:
        sys.exit(f"--model muss Format owner/name (optional :version) haben, nicht: {model}")
    r = requests.get(f"{API}/models/{owner}/{name}", headers=headers(token), timeout=30)
    if r.status_code == 404:
        sys.exit(f"Modell nicht gefunden/kein Zugriff: {model}")
    r.raise_for_status()
    lv = (r.json() or {}).get("latest_version") or {}
    vid = lv.get("id")
    if not vid:
        sys.exit(f"Keine trainierte Version für {model} gefunden (Training fertig?).")
    return vid


def run_prediction(version: str, inp: dict, token: str, poll_s: float = 2.0,
                   timeout_s: float = 300.0) -> list[str]:
    r = requests.post(f"{API}/predictions", headers=headers(token),
                      json={"version": version, "input": inp}, timeout=30)
    r.raise_for_status()
    pred = r.json()
    get_url = pred.get("urls", {}).get("get") or f"{API}/predictions/{pred['id']}"
    waited = 0.0
    while pred.get("status") not in ("succeeded", "failed", "canceled"):
        if waited > timeout_s:
            raise RuntimeError("Timeout beim Warten auf die Prediction")
        time.sleep(poll_s)
        waited += poll_s
        pred = requests.get(get_url, headers=headers(token), timeout=30).json()
    if pred.get("status") != "succeeded":
        raise RuntimeError(pred.get("error") or f"Status {pred.get('status')}")
    out = pred.get("output") or []
    return out if isinstance(out, list) else [out]


def main() -> None:
    ap = argparse.ArgumentParser(description="Batch-Generierung KI-Bilder via trainierter Replicate-LoRA")
    ap.add_argument("--subject", choices=sorted(SUBJECTS), default="juliana",
                    help="Welche LoRA: zieht Modell/Trigger/Outdir-Defaults aus der .env (Default: juliana)")
    ap.add_argument("--model", default=None,
                    help="Override Replicate-Modell owner/name (sonst REPLICATE_MODEL_<SUBJECT> aus .env)")
    ap.add_argument("--trigger", default=None,
                    help="Override Trigger-Wort (sonst REPLICATE_TRIGGER_<SUBJECT> aus .env)")
    ap.add_argument("--count", type=int, default=50, help="Anzahl Bilder (Default 50)")
    ap.add_argument("--outdir", default=None,
                    help="Zielordner (Default: KI_<SUBJECT>_OUTDIR aus .env, sonst image-ki/<modellname>)")
    ap.add_argument("--aspect", default="4:5", help="Seitenverhältnis (Default 4:5, hochkant)")
    ap.add_argument("--num-outputs", type=int, default=4, help="Bilder pro API-Aufruf (1-4)")
    ap.add_argument("--steps", type=int, default=28)
    ap.add_argument("--guidance", type=float, default=3.0)
    ap.add_argument("--lora-scale", type=float, default=1.0)
    ap.add_argument("--seed-base", type=int, default=1000)
    ap.add_argument("--start-index", default="auto",
                    help="Startnummer der Dateinamen, oder 'auto' = nächste freie <prefix>_NNN (Default: auto)")
    ap.add_argument("--prompt-file", default=None, help="Eigene Prompts (eine pro Zeile, {trigger} nutzen)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    subj = SUBJECTS[args.subject]

    token = _load_env_key("REPLICATE_API_TOKEN")
    model = args.model or _env_opt(subj["model_env"])
    trigger = args.trigger or _env_opt(subj["trigger_env"])
    if not model:
        sys.exit(f"Kein Modell: weder --model noch {subj['model_env']} in .env/Umgebung gesetzt.")
    if not trigger:
        sys.exit(f"Kein Trigger-Wort: weder --trigger noch {subj['trigger_env']} in .env/Umgebung gesetzt.")

    name = model.split("/")[-1]
    if args.outdir:
        outdir = Path(args.outdir)
    else:
        env_out = _env_opt(subj["outdir_env"])
        outdir = Path(env_out) if env_out else REPO_ROOT / "image-ki" / name
    outdir.mkdir(parents=True, exist_ok=True)

    prefix = subj["prefix"]
    if str(args.start_index).lower() == "auto":
        start_index = _next_index(outdir, prefix)
    else:
        start_index = int(args.start_index)

    # Prompts: --prompt-file > subjekt-eigene Datei > eingebauter Fallback
    prompts = PROMPTS
    pf = Path(args.prompt_file) if args.prompt_file else subj["prompt_file"]
    if pf and pf.exists():
        lines = [l.strip() for l in pf.read_text(encoding="utf-8").splitlines()
                 if l.strip() and not l.startswith("#")]
        if lines:
            prompts = lines

    per = max(1, min(4, args.num_outputs))
    print(f"KI-Generierung [{args.subject}]: {args.count} Bilder aus {model} (trigger={trigger})")
    print(f"  Zielordner: {_disp(outdir)} | Schema: {prefix}_NNN.jpg ab {start_index:03d}")

    if args.dry_run:
        print(f"(DRY RUN) {len(prompts)} Prompt-Varianten, {per} Bilder/Aufruf, aspect={args.aspect}")
        for i, p in enumerate(prompts[:3]):
            print(f"  Beispiel {i+1}: {p.format(trigger=trigger)[:120]}…")
        return

    version = resolve_version(model, token)
    print(f"Modell-Version: {version[:12]}…")

    manifest = outdir / "manifest.jsonl"
    idx = start_index
    got = 0
    call = 0
    written: list[str] = []
    with manifest.open("a", encoding="utf-8") as mf:
        while got < args.count:
            prompt = prompts[call % len(prompts)].format(trigger=trigger)
            seed = args.seed_base + call
            want = min(per, args.count - got)
            inp = {
                "prompt": prompt,
                "aspect_ratio": args.aspect,
                "num_outputs": want,
                "output_format": "jpg",
                "output_quality": 92,
                "num_inference_steps": args.steps,
                "guidance_scale": args.guidance,
                "lora_scale": args.lora_scale,
                "seed": seed,
            }
            call += 1
            try:
                urls = run_prediction(version, inp, token)
            except Exception as ex:
                # Beim allerersten Aufruf hart abbrechen (z.B. ungültiger Parameter),
                # damit nicht die ganze Serie ins Leere läuft.
                if got == 0 and call == 1:
                    sys.exit(f"Erster Aufruf fehlgeschlagen — Abbruch. Grund: {ex}")
                print(f"  [Aufruf {call}] FEHLER: {ex}")
                time.sleep(2)
                continue
            for url in urls:
                try:
                    img = requests.get(url, timeout=60).content
                except Exception as ex:
                    print(f"    Download-Fehler: {ex}")
                    continue
                fname = f"{prefix}_{idx:03d}.jpg"
                (outdir / fname).write_bytes(img)
                mf.write(json.dumps({"file": fname, "prompt": prompt, "seed": seed,
                                     "aspect": args.aspect}, ensure_ascii=False) + "\n")
                mf.flush()
                written.append(fname)
                idx += 1
                got += 1
                print(f"  [{got}/{args.count}] {fname}")
                if got >= args.count:
                    break

    print(f"\nFertig. {got} Bilder in {_disp(outdir)} (Metadaten: manifest.jsonl)")
    # Physische Präsenz gegen das Manifest abgleichen — OneDrive verschluckt beim
    # schnellen Schreiben gelegentlich frisch geschriebene Dateien.
    missing = [f for f in written if not (outdir / f).exists()]
    if missing:
        print(f"WARNUNG: {len(missing)} laut Manifest geschriebene Datei(en) sind physisch NICHT")
        print(f"  auffindbar (evtl. OneDrive-Sync): {', '.join(missing)}")
        print("  → gezielt nachgenerieren (--start-index <Nr.> --count …, ggf. --seed-base variieren).")
    print("Nächster Schritt: durchsehen, die besten behalten (kuratieren).")


if __name__ == "__main__":
    main()
