"""Décision déterministe de livraison, distincte du succès de génération PDF.

Aucune confiance déclarée par un modèle ne vaut validation. Les lectures IA
restent proposées pour contrôle humain, même lorsque leurs totaux concordent.
"""
from __future__ import annotations
import hashlib
from dataclasses import asdict
import html
import json
import math
import re
from pathlib import Path
from . import extract, pdfio


def colis(valeur):
    m = re.fullmatch(r'\s*(\d+)\s*(?:colis|[A-Z]{2,3})?\s*', str(valeur or ''))
    return int(m[1]) if m else None


def evaluer(d):
    motifs = list(d.blocages)
    if not re.fullmatch(r'\d{2}[A-Z]{2}[A-Z0-9]{14}', d.mrn):
        motifs.append('MRN absent ou mal formé')
    if not d.mrn_verifie:
        motifs.append('MRN non corroboré par une lecture de code-barres ou CargoWise')
    if not d.dm or re.search(r'vérifier|compléter|absent|inconnu', d.dm, re.I):
        motifs.append('DM / LRN obligatoire manquant')
    if not d.parties:
        motifs.append('Parties non renseignées')
    if not d.articles:
        motifs.append('Aucun article extrait')
    for i, a in enumerate(d.articles, 1):
        if not a.designation or 'vérifier' in a.designation:
            motifs.append(f'Article {i} : désignation manquante')
        if not re.fullmatch(r'\d{6,10}', re.sub(r'[.\s]', '', a.code_nc)):
            motifs.append(f'Article {i} : code marchandise manquant ou invalide')
        brut, net = extract.nombre(a.brut), extract.nombre(a.net)
        if brut is None or not math.isfinite(brut) or brut <= 0:
            motifs.append(f'Article {i} : masse brute absente ou invalide')
        if net is None or not math.isfinite(net) or net <= 0:
            motifs.append(f'Article {i} : masse nette absente ou invalide')
        if brut is not None and net is not None and net > brut:
            motifs.append(f'Article {i} : masse nette supérieure à la masse brute')
        n = colis(a.colis)
        if n is None or n <= 0:
            motifs.append(f'Article {i} : colisage absent ou ambigu')
    total = extract.nombre(d.total.get('brut'))
    masses = [extract.nombre(a.brut) for a in d.articles]
    if total is None or not math.isfinite(total) or total <= 0:
        motifs.append('Total masse brute absent ou invalide')
    elif masses and all(m is not None and math.isfinite(m) for m in masses) and abs(sum(masses)-total) > .05:
        motifs.append('Somme des masses brutes différente du total déclaré')
    n = colis(d.total.get('colis'))
    nombres = [colis(a.colis) for a in d.articles]
    if n is None or n <= 0:
        motifs.append('Total colis absent ou invalide')
    elif nombres and all(x is not None for x in nombres) and sum(nombres) != n:
        motifs.append('Somme des colis différente du total déclaré')
    if d.ecart:
        motifs.append(d.ecart)
    if d.ia_utilisee:
        motifs.append('Transcription IA : validation humaine nécessaire')
    if not d.preuves:
        motifs.append('Traçabilité des sources absente')
    for message in d.avertissements:
        if ('MRN' in message and 'différent' in message) or re.search(r'non associ|non extrait|illisible', message, re.I):
            motifs.append(message)
    return list(dict.fromkeys(motifs))


def codes_annonce(pdf, pages, tmp):
    """Décode le numéro GTAN de la page d'annonce, en conservant sa casse."""
    try:
        import zxingcpp
        from PIL import Image
        out = []
        for page in pages:
            png = pdfio.rendre_page_png(pdf, page, 300, tmp, base=f'annonce_barcode_{page}')
            if png:
                with Image.open(png) as im:
                    out.extend(r.text.strip() for r in zxingcpp.read_barcodes(im)
                               if re.fullmatch(r'[0-9]{6}-GTAN-[A-Za-z0-9]+', r.text.strip()))
        return list(dict.fromkeys(out))
    except (ImportError, RuntimeError, OSError):
        return []


def codes_mrn(pdf, pages, tmp):
    """Lecture optique, jamais déduite du texte ni du nom de fichier."""
    try:
        import zxingcpp
        from PIL import Image
    except ImportError:
        return {}, 'Décodeur zxing-cpp absent : vérification des codes-barres indisponible'
    resultats = {}
    try:
        for page in pages:
            png = pdfio.rendre_page_png(pdf, page, 250, tmp, base=f'barcode_{page}')
            if not png:
                continue
            with Image.open(png) as im:
                lus = sorted({r.text.strip() for r in zxingcpp.read_barcodes(im)
                              if re.fullmatch(r'\d{2}[A-Z]{2}[A-Z0-9]{14}', r.text.strip())})
            if lus:
                resultats[page] = lus
    except Exception as exc:
        return resultats, f'Lecture des codes-barres incomplète : {exc}'
    return resultats, ''


def fiche(dossiers, data, analyses, dossier, nom):
    """Fiche interne HTML autonome et images locales des pages candidates.

    Les pages candidates ne sont pas présentées comme des preuves d'un champ
    précis. Les extractions IA conservent aussi le JSON brut page par page.
    """
    dossier.mkdir(parents=True, exist_ok=True)
    assets = dossier / (nom + '_sources')
    assets.mkdir(exist_ok=True)
    formulaire = dossier / (nom + '_validation.json')
    sources = [{"fichier": str(an.pdf.resolve()), "sha256": (an.sha256 or hashlib.sha256(an.pdf.read_bytes()).hexdigest())}
               for an in analyses if an.pdf.is_file()]
    formulaire.write_text(json.dumps({"version":1,"sources":sources,
        "motifs_initiaux":[{"mrn":d.mrn,"motifs":evaluer(d)} for d in dossiers],
        "dossiers":[asdict(d) for d in dossiers]},ensure_ascii=False,indent=2),encoding='utf-8')
    sections = []
    esc = lambda x: html.escape(str(x))
    for d in dossiers:
        sections.append(f'<h2>{esc(d.mrn or "MRN inconnu")}</h2><ul>' + ''.join(f'<li>{esc(m)}</li>' for m in evaluer(d)) + '</ul>')
        sections.append('<pre>' + esc(json.dumps({'dm':d.dm,'total':d.total,
            'articles':[vars(a) for a in d.articles], 'preuves':d.preuves,
            'lectures_ia':d.lectures_ia},ensure_ascii=False,indent=2)) + '</pre>')
    for index, an in enumerate(analyses):
        sections.append(f'<h2>Source : {esc(an.pdf.name)}</h2>')
        for v in an.verdicts:
            if v.famille == 'ENVELOPPE':
                continue
            try:
                png = pdfio.rendre_page_png(an.pdf,v.page,110,assets,base=f'source_{index}_p{v.page}')
                if png:
                    rel = png.relative_to(dossier).as_posix()
                    sections.append(f'<h3>Page {v.page} — {esc(v.famille)}</h3><img src="{esc(rel)}">')
            except Exception as exc:
                sections.append(f'<p>Page {v.page} : aperçu indisponible ({esc(exc)})</p>')
    chemin = dossier / (nom + '_controle.html')
    chemin.write_text('<!doctype html><meta charset="utf-8"><title>Vérification interne</title>'
        '<style>body{font:16px sans-serif;max-width:1000px;margin:40px auto}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#eee;padding:20px}img{max-width:100%;border:1px solid #aaa}li{margin:8px}</style>'
        '<h1>À vérifier — document non validé pour livraison</h1><p>Comparer les valeurs aux sources ci-dessous. Reporter les corrections dans le fichier JSON de validation, puis utiliser tools/valider_dossier.py avec le nom du vérificateur et la confirmation explicite des sources. Les contrôles de complétude et de sommes restent obligatoires.</p>'
        + f'<p><a href="{esc(formulaire.name)}">Fichier de validation à corriger</a></p>'
        + ''.join(sections),encoding='utf-8')
    return chemin
