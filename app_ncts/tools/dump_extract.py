#!/usr/bin/env python3
"""Dump de l'extraction (en-tête + articles) pour un PDF donné.

Usage : python3 tools/dump_extract.py <pdf> [--pages 1,2]
"""

import sys
import tempfile
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))
from ulix_ncts import classify, extract, pdfio  # noqa: E402


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    pdf = Path(args[0]).expanduser().resolve()
    if not pdf.is_file():
        print(f"FICHIER INTROUVABLE : {pdf}")
        return 1
    pages = None
    if "--pages" in args:
        pages = [int(p) for p in args[args.index("--pages") + 1].split(",")]
    tmp = Path(tempfile.mkdtemp())
    print(f"# {pdf.name}")
    for p in (pages or range(1, pdfio.nombre_pages(pdf) + 1)):
        txt = pdfio.couche_texte(pdf, p)
        famille, pos, neg, detail = classify.classer(txt)
        print(f"\n== page {p} : {famille} (+{pos}/-{neg}) {detail}")
        layout = pdfio.couche_texte_layout(pdf, p)
        try:
            if famille == "TRANSIT_TAD":
                print("   en-tête :", extract.extraire_tad_entete(pdf, p))
            elif famille == "TRANSIT_TCH":
                print("   TCH :", extract.extraire_tch(layout))
            elif famille == "TRANSIT_FR":
                print("   FR :", extract.extraire_tad_fr(pdf, p, layout))
            elif famille == "TRANSIT_LISTE":
                print("   ELENCO :", extract.extraire_tad_articles(pdf, p, 200, tmp))
                print("   LISTE  :", extract.extraire_liste_std(pdf, p))
            elif famille.startswith("ANNONCE_CW"):
                faits = extract.extraire_cw1(layout, p)
                print("   CW1 :", {k: v for k, v in faits.items() if k != "plat"})
                if faits.get("type_page") == "liste":
                    print("   ART :", extract.extraire_cw1_articles(pdf, [faits["plat"]]))
            wb = extract.extraire_waybill_dhl(layout)
            if wb:
                print("   waybill :", wb)
        except Exception as exc:                     # diagnostic, jamais silencieux
            print(f"   ERREUR extraction : {type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
