#!/usr/bin/env python3
"""Vérifie la classification page à page sur tous les PDF d'exemple."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))
from ulix_ncts import classify, fsutil, pdfio  # noqa: E402

PROJET = RACINE.parent
dossiers = ["/tmp/t_uni", "/tmp/t_mul", "Dépots unique", "Dépots multiple"]
vus = set()
for d in dossiers:
    rep = fsutil.resoudre(PROJET, d)
    if not rep.is_dir():
        continue
    for pdf in sorted(rep.glob("*.pdf")):
        if pdf.name in vus:
            continue
        vus.add(pdf.name)
        print(f"\n=== {pdf.name}")
        for p in range(1, pdfio.nombre_pages(pdf) + 1):
            txt = pdfio.couche_texte(pdf, p)
            famille, pos, neg, detail = classify.classer(txt)
            marque = "OK " if famille not in ("INDETERMINE",) else "?? "
            print(f"  {marque}p{p:<3} {famille:<16} (+{pos:2d}/-{neg:2d}) {detail}")
