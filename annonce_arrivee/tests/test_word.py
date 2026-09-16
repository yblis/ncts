"""Contrat Word : document éditable, identité en première page, archivage après génération."""
import copy
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ulix_ncts import config, pipeline, word, extract

class Word(unittest.TestCase):
    def test_document_editable_sans_notes(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'annonce.docx'
            data={'mrn':'26CH07STTEST000010','mrns':['26CH07STTEST000010'],
                  'entete':[['MRN','26CH07STTEST000010']],
                  'articles':[{'no':1,'designation':'TEST EDITABLE','net':'0 kg'}],
                  'controle_interne':{'secret':'NOTE INTERNE INTERDITE'},
                  'avertissements':['NOTE INTERNE INTERDITE']}
            ok,msg=word.generer(data,p)
            self.assertTrue(ok,msg)
            with zipfile.ZipFile(p) as z:
                body=z.read('word/document.xml')
                self.assertIn(b'TEST EDITABLE',body)
                self.assertNotIn(b'NOTE INTERNE INTERDITE',body)
                self.assertNotIn(b'documentProtection',z.read('word/settings.xml'))
                ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
                tree=ET.fromstring(body)
                self.assertIsNotNone(tree.find('.//w:titlePg',ns))
                self.assertFalse(tree.findall('.//w:drawing',ns))
                self.assertTrue(any(b'drawing' in z.read(n) for n in z.namelist() if n.startswith('word/header') and n.endswith('.xml')))
    def test_word_incomplet_genere_et_sources_archivees(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);cfg=copy.deepcopy(config.DEFAULTS);cfg['_projet']=str(root)
            cfg['ia']['active']=False;cfg['cargowise']['active']=False
            for k in cfg['dossiers']:
                p=root/k;p.mkdir();cfg['dossiers'][k]=str(p)
            pdf=Path(cfg['dossiers']['depot_unique'])/'source.pdf';pdf.write_bytes(b'%PDF-test')
            d=extract.Dossier(mrn='26CH07STTEST000010',fichiers=[pdf.name])
            with patch.object(pipeline,'analyser_pdf',return_value=pipeline.Analyse(pdf=pdf,dossiers=[d])):
                r=pipeline.executer(cfg)
            self.assertEqual(len(r.modifiables),1,r.messages)
            self.assertEqual(r.modifiables_avec_reserves,r.modifiables)
            self.assertFalse(r.echecs);self.assertFalse(r.sorties);self.assertFalse(r.a_verifier)
            self.assertEqual(len(r.archives),1);self.assertFalse(pdf.exists())
            self.assertEqual(r.archives[0].read_bytes(),b'%PDF-test')
            self.assertIn('CONTRÔLE',r.rapports[0].read_text())
    def test_echec_word_ne_masque_pas_erreur(self):
        with tempfile.TemporaryDirectory() as td:
            cfg=copy.deepcopy(config.DEFAULTS);cfg['_projet']=td
            r=pipeline.Resultat(mode='unique')
            with patch.object(word,'generer',return_value=(False,'panne Word')):
                pipeline._produire([extract.Dossier(mrn='26CH07STTEST000010')],cfg,Path(td),'test',False,[],r)
            self.assertFalse(r.modifiables);self.assertIn('panne Word',r.messages)
    def test_zero_preserve(self):
        self.assertEqual(word._texte(0),'0')

    def test_archivage_word_unique_multiple_et_exceptions(self):
        for mode in ('unique','multiple'):
            for cas in ('succes','echec','garder','simulation'):
                with self.subTest(mode=mode,cas=cas), tempfile.TemporaryDirectory() as td:
                    root=Path(td);cfg=copy.deepcopy(config.DEFAULTS);cfg['_projet']=str(root)
                    cfg['ia']['active']=False;cfg['cargowise']['active']=False
                    cfg['traitement']['deplacer_traite']=cas!='garder'
                    for k in cfg['dossiers']:
                        p=root/k;p.mkdir();cfg['dossiers'][k]=str(p)
                    sources=[]
                    for i in range(2 if mode=='multiple' else 1):
                        pdf=Path(cfg['dossiers']['depot_'+mode])/f'source{i}.pdf'
                        pdf.write_bytes(b'%PDF-test');sources.append(pdf)
                    def analyser(pdf,*args,**kwargs):
                        # L'archivage se fonde sur le lot produit, même sans noms dans Dossier.
                        mrn='26CH07STTEST000009' if pdf==sources[0] else '26CH07STTEST000010'
                        return pipeline.Analyse(pdf=pdf,dossiers=[extract.Dossier(mrn=mrn)])
                    with patch.object(pipeline,'analyser_pdf',side_effect=analyser), patch.object(word,'generer',return_value=(cas!='echec','test')):
                        r=pipeline.executer(cfg,dry_run=cas=='simulation')
                    self.assertEqual(len(r.archives),len(sources) if cas=='succes' else 0)
                    self.assertTrue(all(p.exists()==(cas!='succes') for p in sources))
                    self.assertEqual(r.echecs,sources if cas=='echec' else [])
