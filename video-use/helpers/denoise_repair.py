#!/usr/bin/env python3
"""Repariert Ueber-Entrauschung: holt Sprache zurueck, die DeepFilterNet weggedrueckt hat.

Warum das noetig ist
--------------------
DeepFilterNet entscheidet pro Zeit-/Frequenzpunkt "Sprache oder Rauschen". Bei
leise gesprochenen Stellen (Satzenden, behauchte Woerter) und einem Rohmaterial
mit nur ~20 dB Stoerabstand liegt es gelegentlich daneben und daempft ein
komplettes Wort um 10-30 dB. Im fertigen Reel klingt die Sprecherin dort duenn
und zu leise, waehrend der Rest normal ist.

Was der Helfer macht
--------------------
Er vergleicht Trockensignal (vor dem Entrauschen) und Nassignal (danach) Frame
fuer Frame und begrenzt die Absenkung auf ``--cap`` dB -- aber nur dort, wo im
Trockensignal wirklich Sprache liegt. Sprache wird ueber den Stoerabstand im
Sprachband (300-3400 Hz) gegen ein stationaeres Rauschprofil erkannt (10.
Perzentil je Frequenzbin ueber die ganze Datei). In echten Sprechpausen bleibt
die volle Entrauschung erhalten; in Woertern wird so viel Trockensignal
zurueckgemischt, dass hoechstens ``--cap`` dB Absenkung uebrig bleiben.
Zurueckgemischt wird phasenrichtig im Zeitbereich, es entstehen also keine
Artefakte.

Typischer Ablauf::

    python helpers/denoise.py --in renders/final_reel.mp4 --out renders/_wet.wav
    python helpers/denoise_repair.py --dry renders/final_reel.mp4 \
        --wet renders/_wet.wav --out renders/_audio_fix.wav --cap 5

Danach wie gewohnt auf das Video muxen. Ein anschliessender Lautheits-Durchlauf
(loudnorm I=-14) ist empfehlenswert -- das Entrauschen kostet Pegel, und der
laeuft im Render VOR dem Entrauschen.

``--cap`` steuert den Kompromiss: kleiner Wert = Stimme bleibt voll erhalten,
mehr Raumton; grosser Wert = leiser Raumton, Stimme darf einbrechen. 5 dB hat
sich als guter Mittelwert erwiesen.

Zwei Betriebsarten
------------------
``--mode targeted`` (Standard) greift NUR dort ein, wo der Entrauscher
nachweislich danebenlag. Ueberall sonst bleibt das entrauschte Signal voellig
unangetastet. Das ist die richtige Wahl fuer fertige Videos — der Rest des Tons
bleibt exakt so sauber wie vorher, und nur die verschluckten Woerter werden
geflickt.

Am genauesten wird das mit ``--words <scribe.json>``: dann misst der Helfer die
Absenkung Wort fuer Wort an den echten Wortgrenzen und flickt nur die Woerter
ueber ``--trigger`` dB. Ohne ``--words`` faellt er auf eine gleitende Erkennung
zurueck, die deutlich grober ist — bei fertigen Videos deshalb immer das
Transkript mitgeben (`helpers/transcribe.py <video> --engine scribe`).

``--mode global`` legt die Begrenzung auf das ganze Video. Klingt an den
Problemstellen minimal geschmeidiger, hebt dafuer aber den Raumton im gesamten
Video hoerbar an. Nur nutzen, wenn wirklich das ganze Material betroffen ist.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import scipy.io.wavfile as wavio

HOP_S = 0.005          # 5 ms Analyse-Raster
FFT_N = 1024           # ~21 ms Fenster bei 48 kHz
SPEECH_BAND = (300.0, 3400.0)


def load_mono48k(path: Path) -> tuple[int, np.ndarray]:
    """Liest beliebige Medien als 48 kHz Mono-Float ein (ueber ffmpeg, wenn noetig)."""
    if path.suffix.lower() != ".wav":
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "a.wav"
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-i", str(path),
                 "-vn", "-ac", "1", "-ar", "48000", str(tmp)],
                check=True,
            )
            return load_mono48k(tmp)
    sr, data = wavio.read(path)
    if data.ndim > 1:
        data = data.mean(axis=1)
    if np.issubdtype(data.dtype, np.integer):
        data = data.astype(np.float64) / float(np.iinfo(data.dtype).max + 1)
    else:
        data = data.astype(np.float64)
    return sr, data


def speech_mask(spec_power: np.ndarray, freqs: np.ndarray,
                snr_lo: float, snr_hi: float, dilate_s: float) -> np.ndarray:
    """0..1 je Frame: wie sicher liegt hier Sprache (Stoerabstand im Sprachband)."""
    noise = np.percentile(spec_power, 10, axis=0)
    band = (freqs >= SPEECH_BAND[0]) & (freqs <= SPEECH_BAND[1])
    snr = 10.0 * np.log10(spec_power[:, band].sum(1) / max(noise[band].sum(), 1e-16))
    mask = np.clip((snr - snr_lo) / max(snr_hi - snr_lo, 1e-6), 0.0, 1.0)
    # Rand-Konsonanten mitschuetzen: Maske zeitlich ausdehnen, dann glaetten
    k = max(1, int(round(dilate_s / HOP_S)))
    pad = np.pad(mask, (k, k), mode="edge")
    mask = np.max(np.lib.stride_tricks.sliding_window_view(pad, 2 * k + 1), axis=1)
    return np.convolve(mask, np.ones(7) / 7.0, mode="same")


def damaged_words(dry: np.ndarray, wet: np.ndarray, sr: int, words_json: Path,
                   trigger: float, pad_s: float, frames: int, hop: int) -> tuple[np.ndarray, list]:
    """Absenkung Wort fuer Wort messen; nur die beschaedigten Woerter freigeben.

    Genauer als jede gleitende Erkennung: in den Mikropausen zwischen den Woertern
    daempft der Entrauscher voellig zu Recht um 40 dB und mehr — nur innerhalb
    eines gesprochenen Wortes ist starke Daempfung ein Fehler.
    """
    import json

    payload = json.loads(Path(words_json).read_text(encoding="utf-8"))
    words = [w for w in payload.get("words", []) if w.get("type") != "spacing"]
    if not words:
        raise SystemExit(f"keine Wortzeiten in {words_json}")

    def level(sig: np.ndarray, a: float, b: float) -> float:
        x = sig[int(a * sr):int(b * sr)]
        w = int(sr * 0.02)
        m = len(x) // w
        if m < 1:
            return -120.0
        f = np.sqrt((x[:m * w].reshape(m, w) ** 2).mean(1) + 1e-12)
        return 20 * np.log10(np.sort(f)[-max(1, m // 3):].mean())

    # Der Entrauscher senkt oft den GESAMTpegel (er nimmt ja Energie weg). Dieser
    # gleichmaessige Anteil ist kein Schaden — er wird beim Normalisieren danach
    # ohnehin wieder aufgeholt. Beschaedigt ist ein Wort nur, wenn es DEUTLICH
    # staerker abgesenkt wurde als der Rest. Deshalb zuerst die uebliche Absenkung
    # bestimmen und nur den Ueberschuss darueber bewerten.
    def _att(w) -> float | None:
        a, b = float(w["start"]), float(w["end"])
        if b - a < 0.06:
            return None
        return level(dry, a, b) - level(wet, a, b)

    real = [w for w in words if not str(w.get("text", "")).strip().startswith("[")]
    all_att = [v for v in (_att(w) for w in real) if v is not None]
    baseline = float(np.median(all_att)) if all_att else 0.0

    win = np.zeros(frames, dtype=bool)
    hits = []
    for w in words:
        text = str(w.get("text", "")).strip()
        # Scribe markiert Nicht-Sprache als Ereignis in eckigen Klammern
        # ("[Outro-Musik]" fuer ausklingenden Raumton auf der Endkarte). Solche
        # Bereiche sind KEINE Sprache — dort soll die Entrauschung stehen bleiben.
        if text.startswith("["):
            continue
        a, b = float(w["start"]), float(w["end"])
        if b - a < 0.06:
            continue
        att = level(dry, a, b) - level(wet, a, b) - baseline
        if att <= trigger:
            continue
        i0 = max(0, int(round((a - pad_s) * sr - FFT_N // 2)) // hop)
        i1 = min(frames, int(round((b + pad_s) * sr - FFT_N // 2)) // hop + 1)
        if i1 > i0:
            win[i0:i1] = True
            hits.append((a, b, w.get("text", ""), att))
    soft = np.convolve(win.astype(float), np.ones(13) / 13.0, mode="same")
    if baseline > 0.5:
        print(f"  gleichmaessige Absenkung ueber alle Woerter: {baseline:.1f} dB "
              f"(kein Schaden — holt der Lautheits-Durchlauf danach wieder auf)")
    return soft, hits


def damaged_windows(dry_db: np.ndarray, wet_db: np.ndarray, mask: np.ndarray,
                    trigger: float, min_len_s: float, pad_s: float) -> np.ndarray:
    """1 in Bereichen, in denen der Entrauscher laenger am Stueck Sprache wegdrueckt."""
    # Die Absenkung NUR auf Sprach-Frames auswerten. In den Mikropausen zwischen
    # den Woertern daempft der Entrauscher zu Recht um 40 dB und mehr — wuerde man
    # die mitmitteln, sieht ploetzlich das halbe Video "beschaedigt" aus.
    sp = mask > 0.7
    att_raw = dry_db - wet_db
    if not sp.any():
        return np.zeros(len(mask))
    xs = np.arange(len(att_raw))
    att = np.interp(xs, xs[sp], att_raw[sp])          # Pausen ueberbruecken
    k = 51                                             # ~250 ms Median
    pad = np.pad(att, (k // 2, k // 2), mode="edge")
    att = np.median(np.lib.stride_tricks.sliding_window_view(pad, k), axis=1)
    hot = (att > trigger) & sp

    win = np.zeros(len(hot), dtype=bool)
    min_len = max(1, int(round(min_len_s / HOP_S)))
    pad = max(1, int(round(pad_s / HOP_S)))
    i = 0
    while i < len(hot):
        if not hot[i]:
            i += 1
            continue
        j = i
        while j < len(hot) and hot[j]:
            j += 1
        if j - i >= min_len:
            win[max(0, i - pad):min(len(hot), j + pad)] = True
        i = j
    # weiche Flanken (~60 ms), damit der Uebergang nicht klickt
    return np.convolve(win.astype(float), np.ones(13) / 13.0, mode="same")


def smooth_gain(gain: np.ndarray, attack_s: float = 0.010, release_s: float = 0.060) -> np.ndarray:
    """Ein-Pol-Glaettung, damit der Rueckmisch-Anteil nicht zappelt."""
    ca, cr = np.exp(-HOP_S / attack_s), np.exp(-HOP_S / release_s)
    out = np.empty_like(gain)
    cur = 0.0
    for i, want in enumerate(gain):
        c = ca if want > cur else cr
        cur = c * cur + (1.0 - c) * want
        out[i] = cur
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="DeepFilterNet-Ueberkorrektur zuruecknehmen")
    ap.add_argument("--dry", required=True, type=Path, help="Signal VOR dem Entrauschen (Audio oder Video)")
    ap.add_argument("--wet", required=True, type=Path, help="Signal NACH dem Entrauschen (Audio oder Video)")
    ap.add_argument("--out", required=True, type=Path, help="Ziel-WAV (48 kHz mono)")
    ap.add_argument("--cap", type=float, default=5.0,
                    help="Maximal zugelassene Absenkung auf Sprache in dB (Default 5)")
    ap.add_argument("--snr-lo", type=float, default=8.0, help="Stoerabstand, ab dem Sprache angenommen wird")
    ap.add_argument("--snr-hi", type=float, default=14.0, help="Stoerabstand fuer volle Sprach-Sicherheit")
    ap.add_argument("--dilate", type=float, default=0.040, help="Maske zeitlich ausdehnen (s)")
    ap.add_argument("--mode", choices=["targeted", "global"], default="targeted",
                    help="targeted (Standard): nur nachweislich beschaedigte Stellen flicken. "
                         "global: Begrenzung auf das ganze Video legen.")
    ap.add_argument("--trigger", type=float, default=4.0,
                    help="ab welcher Absenkung eine Stelle als beschaedigt gilt (dB, nur targeted)")
    ap.add_argument("--min-len", type=float, default=0.15,
                    help="Mindestdauer einer beschaedigten Stelle (s, nur targeted)")
    ap.add_argument("--pad", type=float, default=0.10,
                    help="Fenster um beschaedigte Stellen erweitern (s, nur targeted)")
    ap.add_argument("--words", type=Path, default=None,
                    help="Scribe-Transkript (JSON) des ENTRAUSCHTEN Videos — macht die "
                         "Erkennung wortgenau statt gleitend. Sehr empfohlen.")
    ap.add_argument("--report", action="store_true", help="Kurzbericht zur Wirkung ausgeben")
    args = ap.parse_args()

    for p in (args.dry, args.wet):
        if not p.exists():
            sys.exit(f"Datei nicht gefunden: {p}")

    sr, dry = load_mono48k(args.dry.resolve())
    sr_w, wet = load_mono48k(args.wet.resolve())
    if sr != sr_w:
        sys.exit(f"Samplerate passt nicht zusammen: {sr} vs {sr_w}")
    n = min(len(dry), len(wet))
    if abs(len(dry) - len(wet)) > sr * 0.05:
        print(f"Warnung: Laengen weichen um {abs(len(dry)-len(wet))/sr:.2f}s ab — es wird auf die kuerzere gekuerzt.")
    dry, wet = dry[:n], wet[:n]

    hop = int(sr * HOP_S)
    frames = 1 + (n - FFT_N) // hop
    if frames < 2:
        sys.exit("Audio zu kurz fuer die Analyse")
    idx = np.arange(FFT_N)[None, :] + hop * np.arange(frames)[:, None]
    win = np.hanning(FFT_N)
    pd = np.abs(np.fft.rfft(dry[idx] * win, axis=1)) ** 2 + 1e-16
    pw = np.abs(np.fft.rfft(wet[idx] * win, axis=1)) ** 2 + 1e-16
    freqs = np.fft.rfftfreq(FFT_N, 1.0 / sr)

    mask = speech_mask(pd, freqs, args.snr_lo, args.snr_hi, args.dilate)
    dry_db, wet_db = 10 * np.log10(pd.sum(1)), 10 * np.log10(pw.sum(1))

    # zugelassene Absenkung: cap dort wo sicher Sprache, praktisch unbegrenzt in Pausen
    allowed = np.where(mask > 1e-6, np.minimum(args.cap / np.maximum(mask, 1e-6), 200.0), 200.0)
    want = np.maximum(wet_db, dry_db - allowed)
    gain = np.minimum(np.where(want > wet_db + 0.01, 10 ** ((want - dry_db) / 20.0), 0.0), 1.0)

    windows, hits = None, None
    if args.mode == "targeted":
        if args.words:
            windows, hits = damaged_words(dry, wet, sr, args.words, args.trigger,
                                          args.pad, frames, hop)
        else:
            windows = damaged_windows(dry_db, wet_db, mask, args.trigger, args.min_len, args.pad)
        gain = gain * windows
    gain = smooth_gain(gain)

    gs = np.interp(np.arange(n), np.arange(frames) * hop + FFT_N // 2, gain,
                   left=gain[0], right=gain[-1])
    out = wet + gs * dry
    peak = float(np.abs(out).max())
    if peak > 0.99:
        out *= 0.99 / peak

    args.out.parent.mkdir(parents=True, exist_ok=True)
    wavio.write(str(args.out), sr, (out * 32767.0).astype(np.int16))

    if args.report:
        att_before = dry_db - wet_db
        after_db = 10 * np.log10(
            np.abs(np.fft.rfft(out[idx] * win, axis=1)).__pow__(2).sum(1) + 1e-16)
        sp = mask > 0.5
        print(f"  Sprache erkannt auf {100 * sp.mean():.0f}% der Frames")
        if hits:
            print(f"  beschaedigte Woerter: {len(hits)}")
            for a, b, t, att in sorted(hits, key=lambda h: -h[3]):
                print(f"    {a:7.2f}s - {b:7.2f}s  -{att:4.1f} dB   {t}")
        if windows is not None:
            touched = windows > 0.01
            print(f"  angefasst: {100 * touched.mean():.1f}% des Videos "
                  f"({touched.sum() * HOP_S:.1f}s von {frames * HOP_S:.1f}s) — "
                  f"der Rest bleibt Bit-fuer-Bit das entrauschte Signal")
            runs, i = [], 0
            while i < len(touched):
                if touched[i]:
                    j = i
                    while j < len(touched) and touched[j]:
                        j += 1
                    runs.append((i * HOP_S, j * HOP_S))
                    i = j
                else:
                    i += 1
            for a, b in runs:
                print(f"    {a:7.2f}s - {b:7.2f}s  ({b - a:.2f}s)")
        if sp.any():
            print(f"  Absenkung auf Sprache: vorher max {att_before[sp].max():.1f} dB "
                  f"/ Mittel {att_before[sp].mean():.1f} dB "
                  f"-> nachher max {(dry_db - after_db)[sp].max():.1f} dB "
                  f"/ Mittel {(dry_db - after_db)[sp].mean():.1f} dB")
        pause = ~sp
        if pause.any():
            print(f"  Pausen bleiben entrauscht: {(dry_db - after_db)[pause].mean():.1f} dB unter Trockensignal")
    print(f"repariert -> {args.out}")


if __name__ == "__main__":
    main()
