#!/usr/bin/env python3
"""Débogage du repli IA : montre les pages soumises et la réponse brute du modèle.

Usage : python3 tools/debug_ia.py <pdf> [--page N]
"""

import json
import sys
import tempfile
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

from ulix_ncts import config as C, ia, pdfio, pipeline  # noqa: E402


def main() -> int:
    pdf = Path(sys.argv[1]).resolve()
    cfg = C.charger()
    conf = ia.configuration(cfg)

    if "--page" in sys.argv:
        pages = [int(sys.argv[sys.argv.index("--page") + 1])]
    else:
        verdicts = pipeline.classer_pages(pdf, cfg)
        for v in verdicts:
            print(f"  page {v.page:2} : {v.famille:14} {v.detail}")
        an = type("A", (), {"verdicts": verdicts, "pdf": pdf})()
        pages = ia._pages_a_lire(an, conf)

    print(f"\nIA : {conf['modele']} @ {conf['url']}")
    print(f"pages soumises : {pages}\n")
    with tempfile.TemporaryDirectory() as tmp:
        for p in pages:
            image = pdfio.rendre_page_png(pdf, p, conf["dpi"], Path(tmp))
            print(f"--- page {p} -> {image.name} ({image.stat().st_size // 1024} Ko)")
            lu = ia.lire_page(image, conf, "test")
            print(json.dumps(lu, ensure_ascii=False, indent=2)[:1400])
            print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
