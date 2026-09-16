"""Accès bas niveau aux PDF : couche texte, rendu image, OCR par zone/bandeau.

Le pipeline « cheap-first » du skill est respecté : on lit d'abord la couche
texte (instantanée, gratuite) et on ne paie l'OCR que sur les pages sans texte
exploitable ou au verdict ambigu, et seulement sur les zones utiles.

Aucun paquet Python externe n'est requis : pdftotext / pdftoppm / pdfinfo /
tesseract (poppler + tesseract) et Pillow si présent (repli sans Pillow : crops
via -x -y -W -H de pdftoppm).
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import plateforme

try:
    from PIL import Image
except Exception:  # Pillow absent : on utilisera le crop natif de pdftoppm
    Image = None


class OutilManquant(RuntimeError):
    """Un binaire externe requis est absent."""


BINAIRES = plateforme.BINAIRES


def verifier_outils(requis=BINAIRES) -> list[str]:
    """Binaires manquants. Cherchés dans le PATH **et** les emplacements Windows."""
    return plateforme.verifier_outils(requis)


def _run(cmd, **kw) -> subprocess.CompletedProcess:
    """Lance un binaire externe en lui transmettant l'environnement adapté.

    Le chemin du binaire est résolu ici, en un seul point : sur Windows, poppler
    et tesseract sont fréquemment installés hors du PATH, et tous les appels du
    module passent par cette fonction.

    `env` est indispensable sur Windows : il porte `PYTHONUTF8` (encodage des
    sorties) et `TESSDATA_PREFIX` (modèles de langue de tesseract, que certains
    installateurs ne positionnent pas).
    """
    if cmd and isinstance(cmd[0], str):
        resolu = plateforme.chemin_binaire(cmd[0])
        if resolu:
            cmd = [resolu, *cmd[1:]]
    kw.setdefault("env", plateforme.environnement_sous_processus())
    kw.setdefault("timeout", 120)
    cp = subprocess.run(cmd, capture_output=True, **kw)
    if cp.returncode and not ("--psm" in cmd and "0" in cmd):
        detail = cp.stderr.decode("utf-8", "replace") if isinstance(cp.stderr, bytes) else str(cp.stderr)
        raise RuntimeError(f"{Path(cmd[0]).name} a échoué : {detail[:300]}")
    return cp


def _txt(cp: subprocess.CompletedProcess) -> str:
    # les binaires poppler/tesseract peuvent sortir dans l'encodage local
    # (cp1252 sur Windows) : on décode en tolérant, jamais en levant.
    for encodage in ("utf-8", None):
        try:
            return cp.stdout.decode(encodage or "utf-8", "replace")
        except (LookupError, UnicodeDecodeError):
            continue
    return cp.stdout.decode("utf-8", "replace")


def nombre_pages(pdf: Path) -> int:
    out = _txt(_run(["pdfinfo", str(pdf)]))
    m = re.search(r"^Pages:\s+(\d+)", out, re.M)
    return int(m.group(1)) if m else 0


def couche_texte(pdf: Path, page: int) -> str:
    return _txt(_run(["pdftotext", "-f", str(page), "-l", str(page), str(pdf), "-"]))


def couche_texte_layout(pdf: Path, page: int) -> str:
    return _txt(_run(["pdftotext", "-layout", "-f", str(page), "-l", str(page),
                      str(pdf), "-"]))


def texte_bbox(pdf: Path, page: int) -> str:
    """Couche texte en XML `-bbox` (mots avec leurs boîtes, pour l'extraction
    positionnelle). Passe par `_run` : binaire résolu et environnement adapté."""
    return _txt(_run(["pdftotext", "-f", str(page), "-l", str(page), "-bbox",
                      str(pdf), "-"]))


def dimensions_pdf(pdf: Path) -> list[tuple[float, float]]:
    """[(largeur_pt, hauteur_pt)] par page, via pdfinfo."""
    out = _txt(_run(["pdfinfo", "-f", "1", "-l", str(max(nombre_pages(pdf), 1)),
                     str(pdf)]))
    dims = []
    for m in re.finditer(r"page\s+(\d+)\s+size:\s+([\d.]+)\s+x\s+([\d.]+)", out):
        dims.append((float(m.group(2)), float(m.group(3))))
    return dims or [(595.0, 842.0)]


# --------------------------------------------------------------------- rendu
def _png_rendu(dossier: Path, base: str, page: int) -> Path | None:
    """PNG produit par pdftoppm pour cette page.

    pdftoppm nomme sa sortie ``<base>-<page>.png`` quand ``-f``/``-l`` ciblent une
    page précise. On cherche donc ce nom exact AVANT tout glob : avec plusieurs
    pages rendues dans le même dossier et un ``base`` par défaut identique, un
    glob trié renvoyait toujours la page 1 — le modèle relisait la même page.
    """
    exact = dossier / f"{base}-{page}.png"
    if exact.is_file():
        return exact
    # replis : nom sans suffixe, puis variante à nombre de chiffres variable
    for motif in (f"{base}.png", f"{base}-{page:02d}.png", f"{base}-*.png"):
        trouves = sorted(dossier.glob(motif))
        if trouves:
            return trouves[0]
    return None


def rendre_page_png(pdf: Path, page: int, dpi: int, dossier: Path,
                    base: str = "pg") -> Path | None:
    _run(["pdftoppm", "-singlefile", "-png", "-r", str(dpi), "-f", str(page), "-l", str(page),
          str(pdf), str(dossier / base)])
    cible = dossier / f"{base}.png"
    return cible if cible.is_file() else None


def rendre_zone_pt(pdf: Path, page: int, dpi: int, dossier: Path, base: str,
                   x_pt: float, y_pt: float, w_pt: float, h_pt: float) -> Path | None:
    """Crop natif pdftoppm (aucune dépendance image)."""
    _run(["pdftoppm", "-singlefile", "-png", "-r", str(dpi), "-f", str(page), "-l", str(page),
          "-x", str(int(x_pt * dpi / 72)), "-y", str(int(y_pt * dpi / 72)),
          "-W", str(int(w_pt * dpi / 72)), "-H", str(int(h_pt * dpi / 72)),
          str(pdf), str(dossier / base)])
    cible = dossier / f"{base}.png"
    return cible if cible.is_file() else None


def agrandir(image: Path, facteur: int = 3, dossier: Path | None = None) -> Path:
    """Agrandit une image (l'OCR dégradé des SAD scannés en a besoin)."""
    if Image is None or facteur <= 1:
        return image
    img = Image.open(image)
    img = img.resize((img.width * facteur, img.height * facteur), Image.LANCZOS)
    cible = (dossier or image.parent) / f"{image.stem}_x{facteur}.png"
    img.save(cible)
    return cible


def redresser(image: Path) -> Path:
    """Redresse une page paysage scannée en portrait (TAD UE)."""
    if Image is None:
        return image
    img = Image.open(image)
    if img.width > img.height:
        img = img.rotate(90, expand=True)
        cible = image.parent / f"{image.stem}_rot.png"
        img.save(cible)
        return cible
    return image


def ocr(image: Path, langue: str = "eng", psm: int = 6) -> str:
    cp = _run(["tesseract", str(image), "-", "-l", langue, "--psm", str(psm)])
    return _txt(cp)


def orientation(image: Path) -> int:
    out = _txt(_run(["tesseract", str(image), "-", "--psm", "0"]))
    m = re.search(r"Rotate:\s*(\d+)", out)
    return int(m.group(1)) % 360 if m else 0


def ocr_bandeau_haut(pdf: Path, page: int, dpi: int, langue: str = "eng",
                     fraction: float = 0.22) -> str:
    """OCR du seul bandeau haut (titre + case TYPE), 1 passe d'orientation."""
    if Image is None:
        png = rendre_zone_pt(pdf, page, dpi, Path(tempfile.mkdtemp()),
                             "band", 0, 0, 600, 842 * fraction)
        return ocr(png, langue, 6) if png else ""
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        png = rendre_page_png(pdf, page, dpi, d)
        if not png:
            return ""
        img = Image.open(png)
        rot = orientation(png)
        if rot:
            img = img.rotate(rot, expand=True) if rot in (90, 270) else img
        bande = img.crop((0, 0, img.width, int(img.height * fraction)))
        p = d / "bande.png"
        bande.save(p)
        return ocr(p, langue, 6)


def crops_sont_paysage(pdf: Path, page: int) -> bool:
    dims = dimensions_pdf(pdf)
    if page - 1 < len(dims):
        w, h = dims[page - 1]
        return w > h
    return False
