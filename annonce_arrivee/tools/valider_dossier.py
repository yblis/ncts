#!/usr/bin/env python3
"""Livraison après contrôle humain explicite du formulaire *_validation.json.

Corriger les valeurs de dossiers/articles dans le JSON après lecture des sources.
Puis : python tools/valider_dossier.py FICHIER --operateur NOM --confirmer-sources
Cette commande atteste une relecture humaine ; ne jamais l'appeler automatiquement.
Les sources sont vérifiées par SHA-256, conservées et jamais modifiées/archivées ici.
"""
import argparse
from dataclasses import fields
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ulix_ncts import config, extract, qualite, render


def preparer(formulaire, operateur):
    if formulaire.get('version') != 1 or not formulaire.get('sources'):
        raise ValueError('Formulaire sans version ou sans sources vérifiables')
    for source in formulaire['sources']:
        chemin=Path(source['fichier'])
        if not chemin.is_file() or hashlib.sha256(chemin.read_bytes()).hexdigest()!=source['sha256']:
            raise ValueError(f'Source absente ou modifiée : {chemin}')
    dossiers=[]
    noms={f.name for f in fields(extract.Dossier)}
    for donnees in formulaire.get('dossiers',[]):
        d=extract.Dossier(**{k:v for k,v in donnees.items() if k in noms and k!='articles'})
        d.articles=[extract.Article(**a) for a in donnees.get('articles',[])]
        # Cette attestation ne vient jamais d'une réponse IA ou du statut du rendu.
        d.mrn_verifie=True;d.ia_utilisee=False;d.blocages=[];d.ecart='';d.avertissements=[]
        d.preuves.append({'methode':'relecture humaine explicite','operateur':operateur,
                          'date_utc':datetime.now(timezone.utc).isoformat()})
        motifs=qualite.evaluer(d)
        if motifs:
            raise ValueError(f"{d.mrn} : " + '; '.join(motifs))
        dossiers.append(d)
    if not dossiers or len({d.mrn for d in dossiers})!=len(dossiers):
        raise ValueError('Liste vide ou MRN dupliqué')
    return dossiers


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('formulaire',type=Path)
    ap.add_argument('--operateur',required=True)
    ap.add_argument('--confirmer-sources',action='store_true',required=True)
    args=ap.parse_args(argv)
    if not args.operateur.strip():
        ap.error('Le nom du vérificateur est obligatoire')
    try:
        original=json.loads(args.formulaire.read_text(encoding='utf-8'))
        dossiers=preparer(original,args.operateur.strip())
        cfg=config.charger()
        sortie=Path(cfg['dossiers']['sortie'])/'Prets_a_remettre'
        sortie.mkdir(parents=True,exist_ok=True)
        nom='Annonce_validee_'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.pdf'
        data=render.dossiers_vers_data(dossiers,cfg)
        data['validation_humaine']={'operateur':args.operateur.strip(),
            'date_utc':datetime.now(timezone.utc).isoformat(),'formulaire':original}
        gabarit=render.trouver_gabarit(Path(__file__).resolve())
        if not gabarit:
            raise ValueError('Gabarit introuvable')
        # Rien dans le dossier prêt avant validation physique du PDF et de sa trace.
        with tempfile.TemporaryDirectory(prefix='.validation-',dir=sortie) as td:
            tmp=Path(td);pdf=tmp/nom
            ok,message=render.generer(data,pdf,gabarit)
            if not ok:
                raise ValueError(message)
            controle=render.verifier_rendu(pdf,data=data)
            if not controle['ok']:
                raise ValueError(str(controle))
            preuves=Path(cfg['dossiers']['sortie'])/'data';preuves.mkdir(exist_ok=True)
            os.replace(pdf.with_suffix('.json'),preuves/(Path(nom).stem+'.json'))
            os.replace(pdf,sortie/nom)
        print(f'VALIDÉ PAR {args.operateur} : {sortie/nom}')
        print('Sources conservées. La trace de validation est dans data/.')
        return 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f'Validation refusée : {exc}',file=sys.stderr)
        return 3


if __name__=='__main__':raise SystemExit(main())
