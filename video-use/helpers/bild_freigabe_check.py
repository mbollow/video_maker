"""Read reviewer feedback from the Bilder review folder.

Thin wrapper around freigabe_check.py that points --dir at FREIGABE_BILDER_DIR
(from .env). Any extra args (e.g. --batch, --json) are passed through.

Usage:
    npm run bild:freigabe:check
    python helpers/bild_freigabe_check.py --batch juni-fuehrung
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bild_common as bc  # noqa: E402
import freigabe_check  # noqa: E402

if __name__ == "__main__":
    if "--dir" not in sys.argv:
        sys.argv += ["--dir", bc.env_value("FREIGABE_BILDER_DIR")]
    freigabe_check.main()
