#!/usr/bin/env python3
"""Identifie, dans un PDF multi-documents, les pages qui contiennent VRAIMENT
un titre de transit (T1, T2, T2L, T2F, TCH/transit national) — et écarte les
pièces qui y ressemblent, en particulier les déclarations d'EXPORT (EX1 / EAD /
document d'accompagnement export), factures, e-AD, CMR, AWB, e-mails, etc.

Pipeline « cheap-first » (fiable ET rapide) :
  1. Couche texte (pdftotext) par page — instantané, gratuit. Suffit pour la
     plupart des formulaires douaniers générés électroniquement.
  2. UNIQUEMENT pour les pages sans couche texte exploitable : OCR du seul
     BANDEAU HAUT (≈ 22 % de la page) à 150 dpi, avec essais de rotation
     (0/90/180/270). On lit le titre et la case TYPE, pas toute la page.
  3. Score par ancres : positives (transit) − négatives (export/autre).
     Verrou anti-piège : un titre/type d'EXPORT force le rejet même si la
     mise en page est celle d'un SAD/transit.

Usage :
    python3 find_transit_pages.py fichier.pdf [--json] [--dpi 150]

Sortie : pages de transit retenues, type détecté, et raison du rejet des
pages « pièges ». Dépendances : pdftotext, pdftoppm, tesseract, Pillow.
"""

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

# --- Ancres POSITIVES : un vrai titre de transit -----------------------------
POS = [
    (r"d[ée]claration de marchandises en transit", 6),
    (r"transit national", 5),
    (r"document d.accompagnement[- ]?transit", 6),
    (r"transit accompanying document", 6),
    (r"begleitdokument[- ]?versand|versandbegleitdokument", 6),  # DE transit
    (r"titulaire du r[ée]gime de transit", 4),
    (r"\bgdrn\b", 3),
    (r"d[ée]lai de transit", 3),
    (r"bureau de destination", 2),
    (r"principal oblig[ée]", 2),
    (r"\bt2l\b|\bt2f\b", 4),
]
# Case TYPE = T1/T2 (transit). Inclut le cas « bandeau scanné » où il ne reste
# qu'un « T1 » / « T2 » isolé sur sa ligne.
TYPE_TRANSIT = (r"(?m)\btype\b[^\n]{0,40}\b(t1|t2|t2l|t2f)\b"
                r"|\bdeclaration\b[^\n]{0,20}\b(t1|t2)\b"
                r"|^\s*(t1|t2|t2l|t2f)\s*$")

# --- Ancres NÉGATIVES : export / e-AD / autres pièces (le PIÈGE) --------------
# NB : critères de NIVEAU TITRE uniquement. On n'utilise PAS des libellés de
# champ comme « Exportateur » / « Bureau d'exportation » : ils figurent aussi
# sur le formulaire SAD d'un transit. Le code lettre du MRN (…EX…/…ST…) n'est
# PAS fiable (un transit référence le MRN d'export précédent) — non utilisé.
NEG_EXPORT = [
    (r"export accompanying document", 8),
    (r"document d.accompagnement[- ]?export", 8),
    (r"wywozowy dokument towarzysz", 8),       # PL : EAD export
    (r"ausfuhrbegleitdokument", 8),            # DE : EAD export
    (r"eu export declaration", 8),
    (r"d[ée]claration d.exportation", 7),
    (r"\bead\b", 5),
]
NEG_OTHER = [
    (r"dokument e-?ad|e-?ad\b|administrative accompanying", 6),  # accise EMCS
    (r"proforma invoice|commercial invoice|packing list", 5),
    (r"\bcmr\b|consignment note|lettre de voiture", 4),
    (r"air waybill|\bawb\b\s*no", 3),
    (r"from:\s|sent:\s|subject:|objet\s*:", 4),  # e-mail
    (r"certificate of origin|eur\.?1", 4),
]

MRN_ANY = re.compile(r"\b\d{2}[A-Z]{2}[0-9A-Z]{12,}", re.I)  # présence d'un MRN


def _run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def page_count(pdf):
    out = _run(["pdfinfo", pdf]).stdout
    m = re.search(r"^Pages:\s+(\d+)", out, re.M)
    return int(m.group(1)) if m else 0


def text_layer(pdf, p):
    return _run(["pdftotext", "-f", str(p), "-l", str(p), pdf, "-"]).stdout


def _orientation(img_path):
    """Angle de rotation à appliquer (sens horaire) d'après l'OSD tesseract.
    Renvoie 0 si indéterminé."""
    out = _run(["tesseract", str(img_path), "-", "--psm", "0"]).stdout
    m = re.search(r"Rotate:\s*(\d+)", out)
    return int(m.group(1)) % 360 if m else 0


def ocr_header(pdf, p, dpi):
    """OCR du seul bandeau haut. Détecte l'orientation via l'OSD tesseract
    (1 passe) puis OCR une seule fois — rapide. Repli multi-rotation seulement
    si l'OSD échoue."""
    try:
        from PIL import Image
    except ImportError:
        return ""
    with tempfile.TemporaryDirectory() as td:
        base = Path(td) / "pg"
        _run(["pdftoppm", "-png", "-r", str(dpi), "-f", str(p), "-l", str(p),
              pdf, str(base)])
        pngs = list(Path(td).glob("pg*.png"))
        if not pngs:
            return ""
        im = Image.open(pngs[0])

        def ocr_band(angle):
            r = im.rotate(angle, expand=True) if angle else im
            w, h = r.size
            band = r.crop((0, 0, w, int(h * 0.22)))
            bp = Path(td) / f"b{angle}.png"
            band.save(bp)
            return _run(["tesseract", str(bp), "-", "-l", "eng",
                         "--psm", "6"]).stdout

        rot = _orientation(pngs[0])           # OSD : une passe
        txt = ocr_band(rot)
        score = sum(1 for pat, _ in POS + NEG_EXPORT + NEG_OTHER
                    if re.search(pat, txt, re.I))
        if score == 0:                        # OSD peu sûr -> repli ciblé
            for angle in (a for a in (0, 90, 180, 270) if a != rot):
                t2 = ocr_band(angle)
                if sum(1 for pat, _ in POS + NEG_EXPORT + NEG_OTHER
                       if re.search(pat, t2, re.I)) > 0:
                    return t2
        return txt


def classify(text):
    t = text.lower()
    pos = sum(w for pat, w in POS if re.search(pat, t))
    if re.search(TYPE_TRANSIT, t):
        pos += 5
    neg_x = sum(w for pat, w in NEG_EXPORT if re.search(pat, t))
    neg_o = sum(w for pat, w in NEG_OTHER if re.search(pat, t))
    has_mrn = bool(MRN_ANY.search(text))

    # Verrou anti-piège : un TITRE d'export => rejet, même si layout SAD/transit.
    if neg_x >= 7:
        return "EXPORT", pos, neg_x + neg_o, "titre de déclaration d'export (EX1/EAD) — pas un transit"
    if pos >= 6 or (pos >= 4 and has_mrn):
        if neg_x >= 7 and neg_x >= pos:           # export prédominant
            return "EXPORT", pos, neg_x + neg_o, "indices export prédominants"
        kind = "TCH" if re.search(r"transit national|\bgdrn\b", t) else "T1/T2"
        return "TRANSIT", pos, neg_x + neg_o, kind
    if neg_o >= 4:
        return "AUTRE", pos, neg_o, "pièce annexe (facture/e-AD/CMR/e-mail…)"
    return "INDÉTERMINÉ", pos, neg_x + neg_o, "aucun marqueur fort"


def analyze(pdf, dpi=150):
    n = page_count(pdf)
    rows = []
    for p in range(1, n + 1):
        txt = text_layer(pdf, p)
        src = "texte"
        verdict, pos, neg, why = classify(txt)
        # OCR de repli : page sans texte OU verdict ambigu (couche texte d'un
        # scan souvent dégradée → un T1/T2 peut s'y réduire à du bruit). On ne
        # paie l'OCR que sur ces pages, et seulement sur le bandeau haut.
        if len(txt.strip()) < 40 or verdict == "INDÉTERMINÉ":
            otxt = ocr_header(pdf, p, dpi)
            ov, op, on, ow = classify(otxt)
            # on garde le verdict OCR s'il est plus tranché
            rank = {"INDÉTERMINÉ": 0, "AUTRE": 1, "EXPORT": 2, "TRANSIT": 2}
            if rank.get(ov, 0) > rank.get(verdict, 0) or (op > pos):
                verdict, pos, neg, why, src = ov, op, on, ow, "ocr-bandeau"
        rows.append({"page": p, "verdict": verdict, "source": src,
                     "score_pos": pos, "score_neg": neg, "detail": why})
    return rows


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 1
    pdf = args[0]
    dpi = 150
    if "--dpi" in sys.argv:
        dpi = int(sys.argv[sys.argv.index("--dpi") + 1])
    rows = analyze(pdf, dpi)
    transit = [r for r in rows if r["verdict"] == "TRANSIT"]
    if "--json" in sys.argv:
        print(json.dumps({"pdf": pdf, "transit_pages": [r["page"] for r in transit],
                          "pages": rows}, ensure_ascii=False, indent=2))
        return 0
    print(f"\n{pdf}")
    for r in rows:
        flag = "✅" if r["verdict"] == "TRANSIT" else (
            "⛔" if r["verdict"] == "EXPORT" else "· ")
        print(f"  {flag} p{r['page']:>2} {r['verdict']:<12} [{r['source']}] "
              f"(+{r['score_pos']}/-{r['score_neg']}) {r['detail']}")
    print(f"\n  → Page(s) transit retenue(s) : "
          f"{', '.join(str(r['page']) for r in transit) or 'AUCUNE'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
