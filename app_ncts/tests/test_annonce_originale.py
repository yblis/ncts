import copy
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from dataclasses import asdict
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ulix_ncts import extract, render, config, relecture, pipeline

class AnnonceOriginale(unittest.TestCase):
    def test_annonce_unique_trois_mrn_un_code_original(self):
        ds=[extract.Dossier(mrn=m,annonce_originale=True,codes_annonce=['260101-GTAN-DeMo1']) for m in
            ['26CH07STTEST000002','26CH07STTEST000005','26CH07STTEST000007']]
        data=render.dossiers_vers_data(ds,config.DEFAULTS)
        self.assertEqual(len(data['mrns']),3)
        self.assertEqual(data['codes_barres'],['260101-GTAN-DeMo1'])
        script=Path(__file__).resolve().parents[1]/render.GABARIT_REL
        spec=importlib.util.spec_from_file_location('gabarit_annonce',script)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        self.assertEqual(module._mrns_de(data),['260101-GTAN-DeMo1'])
        ds[0].codes_annonce=[]
        data=render.dossiers_vers_data(ds[:1],config.DEFAULTS)
        self.assertEqual(module._mrns_de(data),[])
    def test_transit_sans_annonce_garde_code_mrn(self):
        mrn='26CH07STTEST000010'
        self.assertEqual(render.dossiers_vers_data([extract.Dossier(mrn=mrn)],config.DEFAULTS)['codes_barres'],[mrn])
    def test_rotation_appliquee_aux_dimensions(self):
        with patch.object(extract.pdfio,'texte_bbox',return_value='<page width="841.68" height="595.2">'),patch.object(extract.pdfio,'_run'),patch.object(extract.pdfio,'_txt',return_value='Page    3 rot: 90'):
            self.assertEqual(extract.dimensions(Path('source.pdf'),3),(595.2,841.68))
    def test_relecture_liee_au_contenu_pas_au_nom(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);pdf=root/'source.pdf';pdf.write_bytes(b'source originale')
            sha=hashlib.sha256(pdf.read_bytes()).hexdigest()
            dossier=extract.Dossier(mrn='26CH07STTEST000002')
            (root/(sha+'.json')).write_text(json.dumps({'sha256':sha,'dossiers':[asdict(dossier)]}))
            self.assertEqual(relecture.charger(pdf,sha,root)[0].mrn,dossier.mrn)
            pdf.write_bytes(b'autre contenu')
            with self.assertRaises(ValueError):relecture.charger(pdf,sha,root)
            self.assertIsNone(relecture.charger(pdf,hashlib.sha256(pdf.read_bytes()).hexdigest(),root))
    def test_colonnes_masses_ne_prennent_pas_marques_ni_unites(self):
        def word(x,y,t):return (x,y,x+20,y+6,t)
        mots=[word(60,110,'1'),word(180,110,'PC,3,1234500001'),word(320,110,'Cigares'),
              word(510,185,'1.s00000'),word(510,198,'0.960000'),word(470,210,'0.000000')]
        with patch.object(extract,'dimensions',return_value=(595,842)),patch.object(extract,'mots_page',return_value=mots):
            a=extract.extraire_cw1_articles(Path('source.pdf'),[1])[0]
        self.assertEqual(a.colis,'3 PC');self.assertEqual(a.marques,'1234500001')
        self.assertEqual(a.brut,'');self.assertEqual(a.net,'0,96 kg')
    def test_totaux_dossier_relu(self):
        # Jeu fictif autonome : aucun document client ni cache de relecture.
        ds = [extract.Dossier(mrn=f'26CH07STTEST0000{i:02d}',
              articles=[extract.Article(designation=f'Article test {i}-{j}',
                        brut='2 kg', net='1 kg', colis='1 PK') for j in range(n)],
              total={'brut':f'{2*n} kg','net':f'{n} kg','colis':str(n)})
              for i,n in enumerate((3,3,2),1)]
        data=render.dossiers_vers_data(ds,config.DEFAULTS)
        self.assertEqual(len(data['articles']),8)
        self.assertEqual(data['total'],{'brut':'16,00 kg','net':'8,00 kg','colis':'8 colis'})
        self.assertTrue(all(not a.code_nc for d in ds for a in d.articles))
    def test_liste_tad_associee_apres_corroboration_optique(self):
        from ulix_ncts.classify import Verdict
        mrn='26IT00000001500001'
        vs=[Verdict(page=1,famille='TRANSIT_TAD',mrn='26LT00000001S00001'),
            Verdict(page=2,famille='TRANSIT_LISTE',mrn='26IT00000001S00001')]
        cfg=copy.deepcopy(config.DEFAULTS)
        with tempfile.TemporaryDirectory() as td, patch.object(extract,'extraire_tad_entete',return_value={'mrn':'26LT00000001S00001'}),patch.object(extract,'extraire_liste_std',return_value=[extract.Article(designation='TEST')]):
            ds=pipeline._dossiers_tad(Path(mrn+'.pdf'),vs,cfg,Path(td),{1:[mrn],2:[mrn]})
            self.assertEqual(ds[0].mrn,mrn);self.assertEqual(len(ds[0].articles),1)
            self.assertNotIn('liste non associée',' '.join(ds[0].avertissements))
            # Un code optique différent ne doit jamais être accepté par ressemblance OCR.
            ds=pipeline._dossiers_tad(Path(mrn+'.pdf'),vs,cfg,Path(td),{1:[mrn],2:['26IT07STTEST000013']})
            self.assertFalse(ds[0].articles)
            self.assertIn('liste non associée',' '.join(ds[0].avertissements))
    def test_image_rendue_ignore_ancien_suffixe_page(self):
        from ulix_ncts import pdfio
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            (root/'barcode_1-1.png').write_bytes(b'ANCIEN PDF COURT')
            (root/'barcode_1-01.png').write_bytes(b'AUTRE PDF LONG')
            def render(cmd):
                self.assertIn('-singlefile',cmd)
                Path(cmd[-1]+'.png').write_bytes(b'PDF COURANT')
            with patch.object(pdfio,'_run',side_effect=render):
                png=pdfio.rendre_page_png(Path('courant.pdf'),1,250,root,'barcode_1')
            self.assertEqual(png.read_bytes(),b'PDF COURANT')
    def test_gdrn_espace_et_reference_ocr(self):
        faits=extract.extraire_tch('GDRN: 26CHO7STTEST 000099\nR6f6rence: REF-DEMO-1234500002-20.07.2026\n')
        self.assertEqual(faits['mrn'],'26CH07STTEST000099')
        self.assertIn('1234500002',faits['reference'])
    def test_liste_fr_nc_six_chiffres_et_masse_decimale(self):
        def mot(x,y,t):return (x,y+100,x+20,y+105,t)
        mots=[mot(140,160,'4;PX;1000001'),mot(285,160,'IMPLANTS MEDICAUX'),
              mot(285,170,'1;EXPO;26CH07STTEST000011;'),mot(285,180,'1;N380;100001;'),
              mot(455,269,'216'),mot(285,286,'902190'),mot(455,286,'180.2'),mot(455,301,'0')]
        with patch.object(extract,'mots_page',return_value=mots),patch.object(extract,'dimensions',return_value=(595,842)):
            a=extract.extraire_liste_std(Path('test.pdf'),2)[0]
        self.assertEqual((a.brut,a.net,a.code_nc),('216,00 kg','180,20 kg','902190'))
        self.assertNotIn('EXPO',a.designation);self.assertIn('EXPO',a.doc_prec);self.assertIn('N380',a.justif)
    def test_tad_fr_ne_depend_pas_de_variables_tad_italien(self):
        from ulix_ncts.classify import Verdict
        with patch.object(extract.pdfio,'couche_texte_layout',return_value=''),patch.object(extract,'extraire_tad_fr',return_value={'mrn':'26CH07STTEST000012'}):
            self.assertEqual(len(pipeline._dossiers_tad_fr(Path('test.pdf'),[Verdict(page=1,famille='TRANSIT_FR')])),1)

    def test_tch_plusieurs_waybills_ne_decrit_pas_total_avec_un_seul(self):
        from ulix_ncts.classify import Verdict
        faits={'mrn':'26CH07STTEST000099','reference':'1234500002','emballages':'4','masse_brute':'16.9'}
        wb=[{'waybill':'1234500002','designation':'Cigarettes A'},{'waybill':'1234500003','designation':'Cigarettes B'}]
        with patch.object(extract.pdfio,'couche_texte_layout',return_value=''),patch.object(extract,'extraire_tch',return_value=faits):
            d=pipeline._dossiers_tch(Path('test.pdf'),[Verdict(page=1,famille='TRANSIT_TCH')],wb,wb[0])[0]
        self.assertEqual(d.articles[0].designation,extract.A_VERIFIER)
        self.assertIn('plusieurs waybills',' '.join(d.avertissements))
