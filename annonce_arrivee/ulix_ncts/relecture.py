"""Relectures de sources liées à leur empreinte, jamais au seul nom du PDF.

Une relecture documentaire ne vaut pas validation douanière. Les preuves et
les champs absents restent disponibles au contrôle interne.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from .extract import Article, Dossier

DOSSIER = Path(__file__).resolve().parents[1] / 'relectures'


def charger(pdf: Path, empreinte: str, dossier: Path | None = None):
    chemin = (dossier or DOSSIER) / (empreinte + '.json')
    if not chemin.is_file():
        return None
    brut = json.loads(chemin.read_text(encoding='utf-8'))
    if brut.get('sha256') != empreinte or hashlib.sha256(pdf.read_bytes()).hexdigest() != empreinte:
        raise ValueError('La relecture ne correspond pas au contenu du PDF')
    if not isinstance(brut.get('dossiers'),list) or not brut['dossiers']:
        raise ValueError('Relecture sans dossier')
    dossiers = []
    for valeur in brut['dossiers']:
        contenu = dict(valeur)
        contenu['articles'] = [Article(**a) for a in contenu.get('articles', [])]
        d = Dossier(**contenu)
        d.fichiers = [pdf.name]
        d.preuves.append({'fichier':str(pdf.resolve()),'sha256':empreinte,
                          'methode':brut.get('methode','relecture documentaire'),
                          'relecture':str(chemin),'pages':brut.get('pages',[])})
        dossiers.append(d)
    if len({d.mrn for d in dossiers}) != len(dossiers):
        raise ValueError('MRN dupliqué dans la relecture')
    return dossiers
