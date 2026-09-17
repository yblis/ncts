"""OCR local PaddleOCR CPU, modèles réutilisés pendant toute la surveillance."""
from __future__ import annotations

from functools import lru_cache
import importlib.util
import os
from pathlib import Path

from . import plateforme

DETECTION = 'PP-OCRv6_small_det'
RECONNAISSANCE = 'PP-OCRv6_small_rec'
ORIENTATION = 'PP-LCNet_x1_0_doc_ori'
MODELES = (DETECTION, RECONNAISSANCE, ORIENTATION)


class ErreurOCR(RuntimeError):
    pass


def verifier_installation():
    return [nom for nom in ('paddleocr', 'paddle', 'paddlex')
            if importlib.util.find_spec(nom) is None]


def _chemin_modele(nom):
    base = os.environ.get('ULIX_OCR_MODELES')
    dossier = (Path(base).expanduser() if base else
               plateforme.dossier_ressources() / 'ocr_models')
    if base or plateforme.est_fige() or dossier.is_dir():
        chemin = dossier / nom
        if not (chemin / 'inference.json').is_file() or not (chemin / 'inference.pdiparams').is_file():
            raise ErreurOCR(f'Modèle PaddleOCR absent ou incomplet : {chemin}')
        return str(chemin)
    # PaddleOCR réutilise son cache utilisateur après le premier téléchargement.
    return None


def _importer():
    # Évite un test de plusieurs hébergeurs à chaque démarrage. Les poids
    # manquants sont toujours téléchargés par PaddleOCR ; aucun PDF n'est envoyé.
    os.environ.setdefault('PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK', 'True')
    try:
        from paddleocr import PaddleOCR, DocImgOrientationClassification
        return PaddleOCR, DocImgOrientationClassification
    except Exception as exc:
        raise ErreurOCR('PaddleOCR indisponible : relancer Installer.command ou Installer.cmd '
                        f'({type(exc).__name__}: {exc})') from exc


@lru_cache(maxsize=1)
def _lecteur():
    PaddleOCR, _ = _importer()
    try:
        return PaddleOCR(text_detection_model_name=DETECTION,
                         text_recognition_model_name=RECONNAISSANCE,
                         text_detection_model_dir=_chemin_modele(DETECTION),
                         text_recognition_model_dir=_chemin_modele(RECONNAISSANCE),
                         device='cpu', cpu_threads=4, enable_mkldnn=False,
                         use_doc_orientation_classify=False,
                         use_doc_unwarping=False, use_textline_orientation=False)
    except Exception as exc:
        detail = f'{exc} — {exc.__cause__}' if exc.__cause__ else str(exc)
        raise ErreurOCR(f'Initialisation PaddleOCR impossible : {detail}') from exc


@lru_cache(maxsize=1)
def _orienteur():
    _, Orientation = _importer()
    try:
        return Orientation(model_name=ORIENTATION, model_dir=_chemin_modele(ORIENTATION),
                           device='cpu', cpu_threads=4, enable_mkldnn=False)
    except Exception as exc:
        raise ErreurOCR(f'Initialisation orientation PaddleOCR impossible : {exc}') from exc


def _donnees(resultat):
    valeur = resultat.json if hasattr(resultat, 'json') else resultat
    if not isinstance(valeur, dict):
        raise ErreurOCR('Réponse PaddleOCR invalide')
    return valeur.get('res', valeur)


def lire(image: Path):
    try:
        textes = []
        for resultat in _lecteur().predict(str(image)):
            donnees = _donnees(resultat)
            if 'rec_texts' not in donnees:
                raise ErreurOCR('Réponse PaddleOCR sans rec_texts')
            textes.extend(str(t) for t in donnees['rec_texts'] if str(t).strip())
        return '\n'.join(textes)
    except ErreurOCR:
        raise
    except Exception as exc:
        raise ErreurOCR(f'Lecture PaddleOCR en échec : {exc}') from exc


def orientation(image: Path):
    """Angle antihoraire à appliquer à PIL avant de découper le bandeau."""
    try:
        resultats = list(_orienteur().predict(str(image), batch_size=1))
        if len(resultats) != 1:
            raise ErreurOCR("Orientation PaddleOCR sans résultat unique")
        d = _donnees(resultats[0])
        angle = int(d['label_names'][0])
        if angle not in (0, 90, 180, 270):
            raise ErreurOCR('Angle PaddleOCR invalide')
        return angle if float(d['scores'][0]) >= .6 else 0
    except ErreurOCR:
        raise
    except Exception as exc:
        raise ErreurOCR(f'Orientation PaddleOCR en échec : {exc}') from exc


def preparer(destination: Path | None = None):
    """Télécharge/charge les poids à l'installation, les exporte pour les paquets."""
    _lecteur()
    _orienteur()
    if destination is not None:
        import shutil
        from paddlex.inference.utils.official_models import official_models
        destination.mkdir(parents=True, exist_ok=True)
        for nom in MODELES:
            source = _chemin_modele(nom) or official_models[nom]
            shutil.copytree(source, destination / nom, dirs_exist_ok=True)


def autotest():
    """Exerce les modèles avec une image fictive, sans données client."""
    import tempfile
    from PIL import Image, ImageDraw, ImageFont
    preparer()
    with tempfile.TemporaryDirectory() as td:
        png = Path(td) / 'controle.png'
        image = Image.new('RGB', (700, 160), 'white')
        ImageDraw.Draw(image).text((30, 40), 'TRANSIT T1', fill='black',
                                  font=ImageFont.load_default(size=48))
        image.save(png)
        texte = lire(png)
        if 'TRANSIT' not in texte.upper():
            raise ErreurOCR('Le test de lecture PaddleOCR a échoué')
        orientation(png)
    return 'PaddleOCR : lecture et orientation opérationnelles (CPU).'


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='Préparer les modèles PaddleOCR locaux')
    ap.add_argument('--exporter', type=Path)
    args = ap.parse_args()
    preparer(args.exporter)
    print('PaddleOCR : modèles prêts (CPU).')
