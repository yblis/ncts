#!/usr/bin/env python3
"""Compare l'extraction réelle à des valeurs de référence, hors ligne.

Usage : python tools/evaluer_corpus.py DOSSIER_SOURCES [--reference fichier.json]
Retour 0 : tous les champs évalués concordent ; 1 : écarts ; 2 : cas non évalués.
Ni API IA, ni CargoWise, ni génération, ni déplacement des sources.
"""
import argparse
import copy
import json
import re
import sys
import tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ulix_ncts import config, extract, pipeline, qualite


def mesurer(dossiers):
    return {
        'mrn':dossiers[0].mrn if len(dossiers)==1 else None,
        'nombre_articles':sum(len(d.articles) for d in dossiers),
        'total_colis':sum(qualite.colis(d.total.get('colis')) or 0 for d in dossiers),
        'total_brut':sum(extract.nombre(d.total.get('brut')) or 0 for d in dossiers),
        'codes_nc':[re.sub(r'[.\s]','',a.code_nc) for d in dossiers for a in d.articles],
        'masses_nettes':[extract.nombre(a.net) for d in dossiers for a in d.articles],
    }


def egaux(attendu, lu):
    if isinstance(attendu,(float,int)) and not isinstance(attendu,bool):
        # Pas de tolérance large masquant une erreur d'unité ou un arrondi de net.
        return isinstance(lu,(float,int)) and abs(attendu-lu)<0.00001
    if isinstance(attendu,list):
        return isinstance(lu,list) and len(attendu)==len(lu) and all(egaux(a,b) for a,b in zip(attendu,lu))
    return attendu==lu


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('sources',type=Path)
    ap.add_argument('--reference',type=Path,default=Path(__file__).resolve().parents[1]/'tests/fixtures/corpus_example.json')
    args=ap.parse_args()
    cfg=copy.deepcopy(config.DEFAULTS);cfg['ia']['active']=False;cfg['cargowise']['active']=False
    rapport=[];corrects=champs=absents=0
    with tempfile.TemporaryDirectory(prefix='corpus-ncts-') as td:
        for cas in json.loads(args.reference.read_text())['cas']:
            fichiers=list(args.sources.rglob(cas['source_pdf']))
            if len(fichiers)!=1:
                rapport.append({'source':cas['source_pdf'],'statut':'non évalué','motif':'source absente ou plusieurs copies'});absents+=1;continue
            try:
                an=pipeline.analyser_pdf(fichiers[0],cfg,Path(td))
                lus=mesurer(an.dossiers)
                ecarts=[]
                for cle,attendu in cas['attendus'].items():
                    champs+=1
                    if egaux(attendu,lus.get(cle)):corrects+=1
                    else:ecarts.append({'champ':cle,'attendu':attendu,'lu':lus.get(cle)})
                rapport.append({'source':cas['source_pdf'],'statut':'écarts' if ecarts else 'concordant','ecarts':ecarts})
            except Exception as exc:
                absents+=1;rapport.append({'source':cas['source_pdf'],'statut':'non évalué','motif':str(exc)})
    print(json.dumps({'champs_concordants':corrects,'champs_evalues':champs,'cas_non_evalues':absents,'cas':rapport},ensure_ascii=False,indent=2))
    return 2 if absents or not champs else (0 if corrects==champs else 1)


if __name__=='__main__':raise SystemExit(main())
