#!/usr/bin/env python3
"""Outil de développement : affiche les « lignes » d'une page PDF reconstruites
à partir des boîtes de mots de `pdftotext -bbox`, avec découpage en cellules
selon les écarts horizontaux. Sert à concevoir/vérifier les extracteurs.

Usage : python3 tools/inspect_lines.py fichier.pdf [--page N] [--xmin A] [--xmax B]
"""

import re
import subprocess
import sys
from pathlib import Path

WORD = re.compile(
    r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>')
PAGE = re.compile(r'<page width="([\d.]+)" height="([\d.]+)">')


def unescape(s: str) -> str:
    return (s.replace("&apos;", "'").replace("&quot;", '"')
             .replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&"))


def mots(pdf: Path, page: int):
    out = subprocess.run(["pdftotext", "-f", str(page), "-l", str(page), "-bbox",
                          str(pdf), "-"], capture_output=True).stdout.decode("utf-8", "replace")
    return [(float(a), float(b), float(c), float(d), unescape(t))
            for a, b, c, d, t in WORD.findall(out)]


def lignes(mots_, tol=4.0):
    """Groupe les mots par ligne (y central), retourne [(y, [(x0,x1,mot)])]."""
    tri = sorted(mots_, key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    out = []
    for w in tri:
        yc = (w[1] + w[3]) / 2
        if out and abs(out[-1][0] - yc) <= tol:
            out[-1][1].append(w)
        else:
            out.append((yc, [w]))
    return [(y, sorted(ws, key=lambda w: w[0])) for y, ws in out]


def cellules(ws, seuil=12.0):
    """Découpe une ligne en cellules selon les écarts horizontaux."""
    cellules_, cur = [], []
    for w in ws:
        if cur and w[0] - cur[-1][2] > seuil:
            cellules_.append(cur)
            cur = [w]
        else:
            cur.append(w)
    if cur:
        cellules_.append(cur)
    return [" ".join(x[4] for x in c) for c in cellules_]


def main():
    args = sys.argv[1:]
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from ulix_ncts import fsutil
    pdf = fsutil.resoudre(Path(__file__).resolve().parent.parent, args[0])
    if not pdf.is_file():
        print(f"FICHIER INTROUVABLE : {args[0]}  (résolu en {pdf})")
        return 1
    page = int(args[args.index("--page") + 1]) if "--page" in args else 1
    xmin = float(args[args.index("--xmin") + 1]) if "--xmin" in args else 0
    xmax = float(args[args.index("--xmax") + 1]) if "--xmax" in args else 1e9
    ms = [w for w in mots(pdf, page) if xmin <= w[0] <= xmax]
    print(f"# {pdf.name} page {page} — {len(ms)} mots")
    for y, ws in lignes(ms):
        detail = " || ".join(f"{c}@{x:.0f}" for c, x in
                             [(c, x) for c, x in _cellules_x(ws)])
        print(f"{y:7.1f} | {detail}")


def _cellules_x(ws, seuil=12.0):
    groupes, cur = [], []
    for w in ws:
        if cur and w[0] - cur[-1][2] > seuil:
            groupes.append(cur)
            cur = [w]
        else:
            cur.append(w)
    if cur:
        groupes.append(cur)
    return [(" ".join(x[4] for x in g), g[0][0]) for g in groupes]


if __name__ == "__main__":
    main()
