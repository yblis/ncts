#!/usr/bin/env python3
"""Mesure la place réelle de PaddleOCR (OCR) dans le traitement.

Instrumente `ulix_ncts.pdfio.ocr` pour compter et chronométrer chaque appel, puis
lance un traitement en simulation (aucun fichier écrit, rien n'est archivé).

Usage : python3 tools/mesure_ocr.py
"""

import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

from ulix_ncts import pdfio  # noqa: E402

_appel_reel = pdfio.ocr
_stat = {"appels": 0, "secondes": 0.0}


def _ocr_compte(*args, **kwargs):
    debut = time.time()
    resultat = _appel_reel(*args, **kwargs)
    _stat["appels"] += 1
    _stat["secondes"] += time.time() - debut
    return resultat


pdfio.ocr = _ocr_compte

from ulix_ncts import config as C, pipeline  # noqa: E402

cfg = C.charger()
debut = time.time()
res = pipeline.executer(cfg, dry_run=True, enrichir_cw=False)
duree = time.time() - debut

pages = sum(len(a.verdicts) for a in res.analyses)
print()
print("=" * 62)
print(f"documents traités          : {len(res.analyses)}")
print(f"pages analysées            : {pages}")
print(f"appels OCR (PaddleOCR)     : {_stat['appels']}")
print(f"pages traitées par OCR     : "
      f"{pages and 100 * _stat['appels'] / pages:.1f} % des pages")
print(f"temps passé en OCR         : {_stat['secondes']:.1f} s")
print(f"temps total du traitement  : {duree:.1f} s")
print(f"part de l'OCR dans le total: {duree and 100 * _stat['secondes'] / duree:.0f} %")
print("=" * 62)
print()
for an in res.analyses:
    print(f"  {an.pdf.name[:48]:50} {len(an.verdicts):3} pages, "
          f"transit {an.pages_transit or 'aucune'}")
