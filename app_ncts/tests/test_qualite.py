"""Scénarios de livraison et de lecture multipage entièrement hors ligne."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ulix_ncts import qualite, extract as e, ia, pipeline as p, render, config

class Fiabilite(unittest.TestCase):
    def dossier(self):
        return e.Dossier(mrn='26CH07STTEST000010',dm='DM 123',mrn_verifie=True,
            articles=[e.Article(designation='TEST',code_nc='12345678',brut='12 kg',net='10 kg',colis='2')],
            total={'brut':'12 kg','colis':'2'},entete=[['Référence déclaration','1234567890']],parties=[{'role':'Expéditeur','lignes':['TEST']}],
            preuves=[{'page':1,'methode':'cas de référence synthétique'}])

    def lecture(self,page,total=2,designation='TEST',reference='FACTURE1'):
        return {'document':{'type':'facture','reference':reference,'page':page,'pages':total,'awb':'1234567890'},
                'articles':[{'designation':designation,'code_nc':'12345678','brut':'6','net':'5','colis':'1'}]}

    def test_valide(self):
        self.assertEqual(qualite.evaluer(self.dossier()),[])

    def test_blocages_independants_de_confiance(self):
        for champ,valeur in [('dm',''),('mrn_verifie',False),('ia_utilisee',True),('preuves',[])]:
            with self.subTest(champ=champ):
                d=self.dossier();setattr(d,champ,valeur);d.confiance='haute'
                self.assertTrue(qualite.evaluer(d))

    def test_ecarts_masses_colis_et_non_finis(self):
        d=self.dossier();d.total={'brut':'20 kg','colis':'5'}
        motifs=' '.join(qualite.evaluer(d))
        self.assertIn('masses',motifs);self.assertIn('colis',motifs)
        for nombre in ['nan','inf','-1','0']:
            d=self.dossier();d.articles[0].brut=nombre
            self.assertTrue(qualite.evaluer(d))

    def test_multipage_toutes_les_lignes_sans_double_total(self):
        d=self.dossier();d.articles=[]
        self.assertTrue(ia.fusionner_lectures(d,[(8,self.lecture(2,designation='B')),(7,self.lecture(1,designation='A'))]))
        self.assertEqual([a.designation for a in d.articles],['A','B'])
        self.assertEqual(d.total['brut'],'12 kg')
        self.assertEqual([p['page'] for p in d.preuves if p.get('methode')=='IA, non validée'],[7,8])

    def test_page_manquante_ne_remplace_pas_donnees(self):
        d=self.dossier();avant=copy.deepcopy(d.articles)
        self.assertFalse(ia.fusionner_lectures(d,[(3,self.lecture(2))]))
        self.assertEqual(d.articles,avant)
        self.assertTrue(d.blocages)

    def test_factures_distinctes_non_fusionnees(self):
        d=self.dossier()
        self.assertFalse(ia.fusionner_lectures(d,[(1,self.lecture(1,1)),(2,self.lecture(1,1,reference='AUTRE'))]))
        self.assertIn('rapprochement humain',' '.join(d.blocages))

    def test_pagination_dupliquee_non_comptee_deux_fois(self):
        d=self.dossier()
        self.assertFalse(ia.fusionner_lectures(d,[(1,self.lecture(1)),(2,self.lecture(1))]))

    def test_livraison_bloquee_garde_sources_et_cree_fiche(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);cfg=copy.deepcopy(config.DEFAULTS);cfg['_projet']=str(root);cfg['document']['format_sortie']='pdf'
            for cle in cfg['dossiers']:
                cfg['dossiers'][cle]=str(root/cle);(root/cle).mkdir()
            source=root/'depot_unique'/'source.pdf';source.write_bytes(b'%PDF-test')
            d=self.dossier();d.dm='';d.fichiers=[source.name]
            an=p.Analyse(pdf=source,dossiers=[d])
            gabarit=Path(__file__).resolve().parents[1]/render.GABARIT_REL
            with patch.object(p,'analyser_pdf',return_value=an),patch.object(render,'trouver_gabarit',return_value=gabarit):
                resultat=p.executer(cfg)
            self.assertTrue(source.exists());self.assertEqual(resultat.sorties,[])
            self.assertEqual(len(resultat.a_verifier),1)
            self.assertEqual(resultat.a_verifier[0].parent.name,'A_verifier')
            self.assertIn('DM / LRN',resultat.fiches[0].read_text())
            self.assertFalse(resultat.archives)

    def test_code_barre_lu_optiquement(self):
        from reportlab.pdfgen.canvas import Canvas
        from reportlab.graphics.barcode.code128 import Code128
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);pdf=root/'test.pdf';c=Canvas(str(pdf))
            Code128(self.dossier().mrn,barWidth=1,barHeight=45).drawOn(c,80,600)
            c.save()
            codes,erreur=qualite.codes_mrn(pdf,[1],root)
            self.assertFalse(erreur)
            self.assertEqual(codes,{1:[self.dossier().mrn]})

    def test_facture_autre_envoi_non_appliquee(self):
        d=self.dossier();lu=self.lecture(1,1);lu['document']['awb']='9999999999'
        self.assertFalse(ia.fusionner_lectures(d,[(2,lu)]))
        self.assertIn('non rapprochée',' '.join(d.blocages))

    def test_ia_ne_sarrete_pas_a_premiere_page_complete(self):
        from PIL import Image
        d=self.dossier();d.articles=[]
        an=p.Analyse(pdf=Path('source.pdf'),verdicts=[p.Verdict(page=1,famille='ANNEXE'),p.Verdict(page=2,famille='ANNEXE')])
        cfg=copy.deepcopy(config.DEFAULTS)
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            def image(pdf,page,*args,**kw):
                out=root/f'{page}.png';Image.new('RGB',(30,30),(page,0,0)).save(out);return out
            with patch.object(ia,'configuration',return_value={'max_pages':2,'dpi':150}),patch.object(ia,'_richesse_page',return_value=0),patch.object(ia.pdfio,'rendre_page_png',side_effect=image),patch.object(ia,'lire_page',side_effect=[self.lecture(1,designation='A'),self.lecture(2,designation='B')]) as lire:
                self.assertTrue(ia.completer_dossier(d,an,cfg,root,echo=lambda *a:None))
            self.assertEqual(lire.call_count,2)
            self.assertEqual([a.designation for a in d.articles],['A','B'])
            self.assertTrue(d.ia_utilisee)
            self.assertTrue(qualite.evaluer(d))

    def test_budget_ia_depasse_bloque_livraison(self):
        d=self.dossier();an=p.Analyse(pdf=Path('source.pdf'),verdicts=[p.Verdict(page=1,famille='ANNEXE')])
        with patch.object(ia,'configuration',return_value={'max_pages':0,'dpi':150}),patch.object(ia,'_richesse_page',return_value=0),patch.object(ia,'lire_page') as lire:
            ia.completer_dossier(d,an,{},Path('.'),echo=lambda *a:None)
        lire.assert_not_called()
        self.assertIn('complétude',' '.join(d.blocages))

    def test_validation_humaine_source_changee_refusee(self):
        import hashlib
        import importlib.util
        from dataclasses import asdict
        chemin=Path(__file__).resolve().parents[1]/'tools/valider_dossier.py'
        spec=importlib.util.spec_from_file_location('validation',chemin)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as td:
            source=Path(td)/'source.pdf';source.write_bytes(b'original')
            d=self.dossier();d.ia_utilisee=True
            formulaire={'version':1,'sources':[{'fichier':str(source),'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}],'dossiers':[asdict(d)]}
            self.assertFalse(module.preparer(formulaire,'Test opérateur')[0].ia_utilisee)
            source.write_bytes(b'modifie')
            with self.assertRaisesRegex(ValueError,'modifiée'):
                module.preparer(formulaire,'Test opérateur')

    def test_validation_humaine_ne_contourne_pas_totaux(self):
        import hashlib
        import importlib.util
        from dataclasses import asdict
        chemin=Path(__file__).resolve().parents[1]/'tools/valider_dossier.py'
        spec=importlib.util.spec_from_file_location('validation',chemin)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as td:
            source=Path(td)/'source.pdf';source.write_bytes(b'original')
            d=self.dossier();d.total['brut']='100 kg'
            formulaire={'version':1,'sources':[{'fichier':str(source),'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}],'dossiers':[asdict(d)]}
            with self.assertRaisesRegex(ValueError,'Somme'):
                module.preparer(formulaire,'Test opérateur')

if __name__=='__main__':unittest.main()
