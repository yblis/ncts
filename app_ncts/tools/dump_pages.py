#!/usr/bin/env python3
"""Dump ciblé des cellules d'une ou plusieurs pages (aide à l'extraction).

Usage :
    python3 tools/dump_pages.py <pdf> [--pages 1,2,5] [--ymin 100] [--ymax 300]
                               [--xmin 0] [--xmax 600]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ulix_ncts import extract, fsutil, pdfio  # noqa: E402


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    pdf = fsutil.resoudre(Path(__file__).resolve().parent.parent, args[0])
    if not pdf.is_file():
        print(f"FICHIER INTROUVABLE : {args[0]} -> {pdf}")
        return 1
    pages = None
    if "--pages" in args:
        pages = [int(p) for p in args[args.index("--pages") + 1].split(",")]
    ymin = float(args[args.index("--ymin") + 1]) if "--ymin" in args else 0
    ymax = float(args[args.index("--ymax") + 1]) if "--ymax" in args else 1e9
    xmin = float(args[args.index("--xmin") + 1]) if "--xmin" in args else 0
    xmax = float(args[args.index("--xmax") + 1]) if "--xmax" in args else 1e9
    total = pdfio.nombre_pages(pdf)
    print(f"# {pdf.name} — {total} pages")
    for p in (pages or range(1, total + 1)):
        print(f"\n===== page {p} =====")
        for y, ws in extract.lignes(extract.mots_page(pdf, p)):
            if not (ymin <= y <= ymax):
                continue
            cells = [(t, x) for t, x in extract.cellules(ws) if xmin <= x <= xmax]
            if not cells:
                continue
            print(f"{y:7.1f} | " + " || ".join(f"{t}@{x:.0f}" for t, x in cells))
    return 0


if __name__ == "__main__":
    sys.exit(main())
