"""Palstek VideoMaker — lokale Web-Oberfläche (Weg B).

Dashboard + Eingang: Videos hochladen, Batches/Bibliothek ansehen.
Die eigentliche Verarbeitung (EDL/Composition) stößt der Nutzer über Claude Code
an (läuft über Max), nicht über diesen Server.

Start:  uv run --with flask python webui/server.py
        → http://127.0.0.1:8730
"""
from __future__ import annotations
import json, re, datetime, unicodedata
from pathlib import Path
from flask import (Flask, render_template, request, redirect, url_for,
                   flash, send_from_directory, abort)

ROOT = Path(__file__).resolve().parent.parent          # Repo-Root
RAW_BATCHES = ROOT / "raw" / "batches"
BATCHES = ROOT / "batches"
PROJECTS = ROOT / "projects"
VIDEO_EXT = {".mov", ".mp4", ".m4v"}

app = Flask(__name__)
app.secret_key = "palstek-videomaker-local"


# ---------- helpers ----------------------------------------------------------
def safe_batch_name(name: str) -> str:
    """Erlaubt Buchstaben (inkl. Umlaute), Zahlen, - _ . — entfernt Pfadtrenner."""
    name = name.strip().replace("/", "_").replace("\\", "_").replace("..", "_")
    name = re.sub(r"[^\w\-.]", "_", name, flags=re.UNICODE)
    return name.strip("._-")


def slug_part(stem: str) -> str:
    s = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return s or "clip"


def load_manifest(batch: str) -> dict | None:
    mp = BATCHES / batch / "manifest.json"
    if mp.exists():
        try:
            return json.loads(mp.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def fmt_dt(iso: str | None) -> str:
    if not iso:
        return ""
    return iso.replace("T", " ")[:16]


def first_line(text: str | None, n: int = 70) -> str:
    if not text:
        return ""
    line = text.strip().splitlines()[0].strip().strip('„"')
    return (line[:n] + "…") if len(line) > n else line


# ---------- pages ------------------------------------------------------------
@app.route("/")
def inbox():
    suggested = datetime.date.today().isoformat() + "_"
    return render_template(
        "inbox.html", active="inbox", suggested_name=suggested,
        last_batch=request.args.get("last"), last_count=request.args.get("count"),
    )


@app.route("/api/upload", methods=["POST"])
def upload():
    batch = safe_batch_name(request.form.get("batch", ""))
    files = [f for f in request.files.getlist("files") if f and f.filename]
    if not batch:
        flash("Bitte einen Batch-Namen angeben.")
        return redirect(url_for("inbox"))
    if not files:
        flash("Keine Videodateien ausgewählt.")
        return redirect(url_for("inbox"))

    dest = RAW_BATCHES / batch
    if dest.exists() and any(p.suffix.lower() in VIDEO_EXT for p in dest.iterdir()):
        flash(f"Batch „{batch}“ existiert bereits und enthält Videos — bitte einen anderen Namen wählen "
              f"(bestehende Batches werden nie überschrieben).")
        return redirect(url_for("inbox"))
    dest.mkdir(parents=True, exist_ok=True)

    saved = 0
    for i, f in enumerate(files, start=1):
        ext = Path(f.filename).suffix.lower()
        if ext not in VIDEO_EXT:
            continue
        out = dest / f"{i:02d}-{slug_part(Path(f.filename).stem)}{ext}"
        f.save(out)
        saved += 1

    ctx = request.form.get("context", "").strip()
    if ctx:
        (dest / "_context.md").write_text(
            f"# Kontext für Batch {batch}\n\n{ctx}\n", encoding="utf-8")

    flash(f"{saved} Video(s) hochgeladen, Batch „{batch}“ angelegt.")
    return redirect(url_for("inbox", last=batch, count=saved))


@app.route("/batches")
def batches():
    names = set()
    if BATCHES.exists():
        names |= {p.name for p in BATCHES.iterdir() if p.is_dir()}
    if RAW_BATCHES.exists():
        names |= {p.name for p in RAW_BATCHES.iterdir() if p.is_dir()}

    rows = []
    for name in names:
        m = load_manifest(name)
        raw_dir = RAW_BATCHES / name
        if m:
            vids = m.get("videos", [])
            count = len(vids)
            rendered = sum(1 for v in vids if (v.get("stages", {}) or {}).get("rendered"))
            scheduled = sum(
                1 for v in vids for p in (v.get("posts", {}) or {}).values()
                if p.get("enabled") and p.get("scheduled_at"))
            created = fmt_dt(m.get("created_at"))
        else:
            count = len([p for p in raw_dir.iterdir() if p.suffix.lower() in VIDEO_EXT]) if raw_dir.exists() else 0
            rendered = scheduled = 0
            created = ""
        rows.append({
            "name": name, "count": count, "rendered": rendered, "scheduled": scheduled,
            "created": created, "has_review": (BATCHES / name / "review.html").exists(),
        })
    rows.sort(key=lambda r: r["created"], reverse=True)
    return render_template("batches.html", active="batches", batches=rows)


@app.route("/library")
def library():
    videos = []
    if PROJECTS.exists():
        for pd in sorted(PROJECTS.iterdir()):
            final = pd / "renders" / "final.mp4"
            if not final.exists():
                continue
            if "__" in pd.name:
                batch, seq = pd.name.rsplit("__", 1)
            else:
                batch, seq = pd.name, "01"
            m = load_manifest(batch)
            v = None
            if m:
                v = next((x for x in m.get("videos", []) if x.get("seq") == seq), None)
            posts = (v or {}).get("posts", {})
            li = (posts.get("linkedin") or {})
            ig = (posts.get("instagram") or {})
            dur = (((v or {}).get("stages", {}) or {}).get("rendered") or {}).get("duration_s")
            thumb = BATCHES / batch / "thumbnails" / f"{seq}.jpg"
            title = first_line(li.get("caption")) or f"{batch} #{seq}"
            videos.append({
                "batch": batch, "seq": seq, "title": title,
                "duration": round(dur) if dur else None,
                "video_url": f"/files/projects/{pd.name}/renders/final.mp4",
                "thumb_url": f"/files/batches/{batch}/thumbnails/{seq}.jpg" if thumb.exists() else None,
                "linkedin": li.get("caption"), "linkedin_at": fmt_dt(li.get("scheduled_at")),
                "instagram": ig.get("caption"), "instagram_at": fmt_dt(ig.get("scheduled_at")),
            })
    videos.sort(key=lambda x: (x["batch"], x["seq"]), reverse=True)
    return render_template("library.html", active="library", videos=videos)


@app.route("/review/<path:batch>")
def review(batch):
    rp = BATCHES / batch / "review.html"
    if not rp.exists():
        abort(404)
    return redirect(f"/files/batches/{batch}/review.html")


@app.route("/files/<path:relpath>")
def files(relpath):
    """Serviert Dateien aus dem Repo-Root (Videos, Thumbnails, review.html) mit
    Schutz gegen Path-Traversal."""
    target = (ROOT / relpath).resolve()
    if not str(target).startswith(str(ROOT)) or not target.is_file():
        abort(404)
    return send_from_directory(target.parent, target.name)


if __name__ == "__main__":
    print("Palstek VideoMaker UI  →  http://127.0.0.1:8730")
    app.run(host="127.0.0.1", port=8730, debug=False)
