"""Tests métier hors ligne : aucune donnée de production ni API externe."""
import copy
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ulix_ncts import config, pipeline as p, extract as e, render, surveillance as s, ia, cw_client as cw
from ulix_ncts.classify import Verdict

ROOT = Path(__file__).resolve().parents[2]
GABARIT = ROOT / render.GABARIT_REL

class Metier(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cfg = copy.deepcopy(config.DEFAULTS)
        self.cfg["document"]["format_sortie"] = "pdf"
        self.cfg['_projet'] = str(self.root)
        self.cfg['ia']['active'] = False
        for k in self.cfg['dossiers']:
            d = self.root/k; d.mkdir()
            self.cfg['dossiers'][k] = str(d)
        self.pdf = Path(self.cfg['dossiers']['depot_unique'])/'depot.pdf'
        self.pdf.write_bytes(b'%PDF-'+b' '*100+b'%%EOF')

    def dossier(self, mrn='26NL07STTEST000018'):
        return e.Dossier(mrn=mrn, dm='DM TEST', date='01.01.2026', mrn_verifie=True,
                         preuves=[{'fichier':'fixture','page':1,'methode':'fixture validée'}],
                         articles=[e.Article(designation='Marchandise de test',code_nc='63071000',brut='12 kg',net='10 kg',colis='2')],
                         total={'brut':'12 kg','colis':'2 colis'},
                         parties=[{'role':'Expéditeur','lignes':['SOCIETE TEST','ADRESSE TEST']}])

    def test_echec_rendu_conserve_depot(self):
        an = p.Analyse(pdf=self.pdf,dossiers=[self.dossier()])
        with patch.object(p,'analyser_pdf',return_value=an), patch.object(render,'trouver_gabarit',return_value=GABARIT), patch.object(render,'generer',return_value=(False,'échec')):
            r = p.executer(self.cfg)
        self.assertTrue(self.pdf.exists())
        self.assertEqual(r.archives,[])
        self.assertEqual(r.echecs,[self.pdf])

    def test_pdf_ignore_conserve_depot(self):
        with patch.object(p,'analyser_pdf',return_value=p.Analyse(pdf=self.pdf)):
            r=p.executer(self.cfg)
        self.assertTrue(self.pdf.exists())
        self.assertFalse(r.archives)

    def test_succes_archive_et_journal(self):
        with patch.object(p,'analyser_pdf',return_value=p.Analyse(pdf=self.pdf,dossiers=[self.dossier()])), patch.object(render,'trouver_gabarit',return_value=GABARIT):
            r=p.executer(self.cfg)
        self.assertEqual(len(r.sorties),1,r.messages)
        self.assertEqual(len(r.archives),1)
        self.assertIn('archivé :',r.rapports[0].read_text())

    def test_tad_listes_bornees_et_non_doublees(self):
        vs=[Verdict(page=i,famille=f) for i,f in [(1,'TRANSIT_TAD'),(2,'TRANSIT_LISTE'),(3,'TRANSIT_TAD'),(4,'TRANSIT_LISTE')]]
        with patch.object(e,'extraire_tad_entete',side_effect=lambda pdf,page,ref:{'mrn':f'MRN_{page}'}),patch.object(e,'extraire_tad_articles',side_effect=lambda pdf,page,*a:e.Article(designation=f'article_{page}')),patch.object(e,'extraire_liste_std',return_value=[]):
            ds=p._dossiers_tad(self.pdf,vs,self.cfg,self.root)
        self.assertEqual([[a.designation for a in d.articles] for d in ds],[['article_2'],['article_4']])
        with patch.object(e,'extraire_tad_entete',return_value={}),patch.object(e,'extraire_tad_articles') as fallback,patch.object(e,'extraire_liste_std',side_effect=lambda pdf,page:[e.Article(designation=f'std_{page}')]):
            ds=p._dossiers_tad(self.pdf,vs,self.cfg,self.root)
        fallback.assert_not_called()
        self.assertEqual(len(ds[0].articles),1)

    def test_cw_mrn_exact_ou_aucun(self):
        for mrn in ('26NL07STTEST000018',''):
            d=e.Dossier(mrn=mrn)
            p._appliquer_cw([d],{'NCT1':{'mrn':'26NL07STTEST000017','lrn':'AUTRE'}})
            self.assertEqual(d.mrn,mrn)
            self.assertFalse(d.dm)
        d=e.Dossier(mrn='26NL07STTEST000018')
        p._appliquer_cw([d],{'NCT1':{'mrn':d.mrn,'lrn':'BON DM'}})
        self.assertEqual(d.dm,'BON DM')

    def test_fusion_conserve_declaration_distincte(self):
        a=self.dossier();b=self.dossier('26CH07STTEST000006')
        self.assertEqual(p._fusionner([a],[b]),[a,b])
        self.assertEqual(len(p._fusionner([a],[self.dossier()])),1)

    def test_lot_incomplet_attend(self):
        multi=Path(self.cfg['dossiers']['depot_multiple'])
        complet=multi/'complet.pdf'; complet.write_bytes(self.pdf.read_bytes())
        part=multi/'copie.pdf';part.write_bytes(b'%PDF-'+b' '*100)
        with patch.object(s.time,'sleep',side_effect=[None, InterruptedError('attente')]):
            with self.assertRaises(InterruptedError):
                s.attendre_lot(self.root/'vide',multi,stabilite_s=0,echo=lambda *a:None)
        part.write_bytes(complet.read_bytes())
        with patch.object(s.time,'sleep'):
            lot=s.attendre_lot(self.root/'vide',multi,stabilite_s=0,echo=lambda *a:None)
        self.assertEqual(set(lot[1]),{complet,part})

    def test_dossier_lacunaire_pas_haute_confiance(self):
        d=self.dossier();d.articles[0].brut='';d.articles[0].net=''
        p._finaliser(d,self.pdf)
        self.assertTrue(p._lacunaire(d))
        self.assertEqual(d.confiance,'faible')

    def test_parties_ia_schema_gabarit(self):
        d=e.Dossier()
        ia.appliquer(d,{'parties':[{'role':'Expéditeur','nom':'SOCIETE','adresse':'ADRESSE'}]})
        self.assertEqual(d.parties[0]['lignes'],['SOCIETE','ADRESSE'])

    def test_ia_ne_remplit_pas_autre_article_par_position(self):
        d=self.dossier(); d.articles[0].code_nc=''
        ia.appliquer(d,{'articles':[{'designation':'AUTRE PRODUIT','code_nc':'99999999'}]})
        self.assertEqual(d.articles[0].code_nc,'')

    def test_cw_interroge_toutes_cles(self):
        fake=type('Fake',(),{'nom_outil':lambda *a:'get_ncts','parametre':lambda *a:'key','appeler_outil':lambda self,n,args:'{"mrn":"'+args['key']+'"}'})()
        self.cfg['cargowise']['active']=True
        with patch.object(cw,'connecter',return_value=(fake,cw.ResultatCW())):
            r=cw.interroger(self.cfg,['NCT1','NCT2'])
        self.assertEqual(set(r.entete),{'NCT1','NCT2'})

    def test_totaux_incomplets_non_presentes_comme_total(self):
        a=self.dossier(); b=self.dossier('26CH07STTEST000006');b.total={}
        data=render.dossiers_vers_data([a,b],self.cfg)
        self.assertEqual(data['total'],{'brut':'à vérifier','colis':'à vérifier'})

    def test_tous_ecarts_conserves(self):
        d=self.dossier(); d.total={'colis':'3 colis','brut':'20 kg'}
        p._croiser(d)
        self.assertIn('colisage',d.ecart);self.assertIn('masse brute',d.ecart)
        avant=d.ecart;p._croiser(d);self.assertEqual(d.ecart,avant)

    def test_pdf_parties_imprimees_notes_internes_absentes(self):
        d=self.dossier();d.ecart='ECART_TEST : 12 kg contre 20 kg';d.source_marchandises='Lecture IA - test';d.avertissements=['DM à vérifier']
        data=render.dossiers_vers_data([d],self.cfg)
        sortie=self.root/'test.pdf'
        ok,msg=render.generer(data,sortie,GABARIT)
        self.assertTrue(ok,msg)
        controle=render.verifier_rendu(sortie,data=data)
        self.assertTrue(controle['ok'],controle)
        from ulix_ncts import pdfio
        texte=' '.join(pdfio.couche_texte(sortie,i) for i in range(1,controle['pages']+1))
        for mot in ['SOCIETE TEST','ADRESSE TEST']:
            self.assertIn(mot,texte)
        for mot in ['ECART_TEST', 'Lecture IA', 'Notes de contrôle', 'Méthode de lecture']:
            self.assertNotIn(mot,texte)

    def test_gros_entete_paginate_sans_perte(self):
        d=self.dossier();d.entete=[[f'Champ {i}',f'VALEUR_{i:03d}'] for i in range(100)]
        data=render.dossiers_vers_data([d],self.cfg);sortie=self.root/'long.pdf'
        ok,msg=render.generer(data,sortie,GABARIT);self.assertTrue(ok,msg)
        from ulix_ncts import pdfio
        texte=' '.join(pdfio.couche_texte(sortie,i) for i in range(1,pdfio.nombre_pages(sortie)+1))
        self.assertIn('VALEUR_099',texte)
        self.assertTrue(render.verifier_rendu(sortie,data=data)['ok'])

    def test_validation_echouee_conserve_source_et_isole_pdf(self):
        with patch.object(p,'analyser_pdf',return_value=p.Analyse(pdf=self.pdf,dossiers=[self.dossier()])), patch.object(render,'trouver_gabarit',return_value=GABARIT), patch.object(render,'verifier_rendu',return_value={'ok':False,'pages':2,'accents':True,'aplat':False,'erreurs':['test']}):
            r=p.executer(self.cfg)
        self.assertTrue(self.pdf.exists())
        self.assertFalse(r.sorties)
        self.assertTrue(list((Path(self.cfg['dossiers']['sortie'])/'A_verifier').glob('*.pdf')))

    def test_mrn_duplique_refuse(self):
        messages=[];r=p.Resultat(mode='multiple')
        with patch.object(render,'trouver_gabarit',return_value=GABARIT):
            produits=p._produire([self.dossier(),self.dossier()],self.cfg,self.root,'TEST',True,messages,r)
        self.assertFalse(produits)
        self.assertIn('double comptage',r.messages[0])

    def test_erreur_analyse_conserve_source(self):
        with patch.object(p,'analyser_pdf',side_effect=RuntimeError('PDF corrompu')):
            r=p.executer(self.cfg)
        self.assertTrue(self.pdf.exists())
        self.assertEqual(r.echecs,[self.pdf])
        self.assertIn('PDF corrompu',r.analyses[0].messages[0])

    def test_types_colis_reconnus_sans_concatener_chiffres(self):
        self.assertEqual(render._somme(['2 PX','3 colis']),5)
        self.assertEqual(render._somme(['2 PX marques 123','3 colis']),0)

    def test_export_non_soumis_a_ia(self):
        an=p.Analyse(pdf=self.pdf,verdicts=[Verdict(page=1,famille='EXPORT'),Verdict(page=2,famille='TRANSIT_TAD')])
        with patch.object(ia,'_richesse_page',return_value=1):
            self.assertEqual(ia._pages_a_lire(an,{'max_pages':3}),[2])

    def test_surveillance_ne_retraite_pas_fichier_inchange(self):
        ignores={(str(self.pdf),s._signature([self.pdf]))}
        with patch.object(s.time,'sleep',side_effect=[None,InterruptedError('attente')]):
            with self.assertRaises(InterruptedError):
                s.attendre_lot(self.pdf.parent,self.root/'vide',stabilite_s=0,echo=lambda *a:None,ignores=ignores)

    def test_lot_multiple_non_reconnu_ne_produit_pas_annonce_partielle(self):
        rep=Path(self.cfg['dossiers']['depot_multiple'])
        a=rep/'a.pdf';b=rep/'b.pdf'
        a.write_bytes(self.pdf.read_bytes());b.write_bytes(self.pdf.read_bytes())
        def analyser(pdf,*args):
            return p.Analyse(pdf=pdf,dossiers=[self.dossier()] if pdf==a else [])
        with patch.object(p,'analyser_pdf',side_effect=analyser),patch.object(render,'generer') as generer:
            r=p.executer(self.cfg,mode='multiple')
        generer.assert_not_called()
        self.assertEqual(set(r.echecs),{a,b})
        self.assertTrue(a.exists() and b.exists())

    def test_listes_cw_sur_plusieurs_pages(self):
        mrn='26NL07STTEST000018'
        faits={1:{'entete_annonce':True,'positions':[['1',mrn]]},
               2:{'type_page':'liste','mrn':mrn,'page':2},
               3:{'type_page':'liste','mrn':mrn,'page':3}}
        vs=[Verdict(page=i,famille='ANNONCE_CW' if i==1 else 'ANNONCE_CW_LISTE') for i in (1,2,3)]
        with patch.object(p.pdfio,'couche_texte_layout',return_value=''),patch.object(e,'extraire_cw1',side_effect=lambda text,page:faits[page]),patch.object(e,'extraire_cw1_articles',return_value=[e.Article(designation='TEST')]) as lire:
            p._dossiers_cw1(self.pdf,vs)
        lire.assert_called_once_with(self.pdf,[2,3])

    def test_nouveau_pdf_necrase_pas_existant(self):
        cible=self.root/'Prets_a_remettre'/'Annonce_et_Inventaire_26NL07STTEST000018.pdf'
        cible.parent.mkdir(exist_ok=True)
        cible.write_bytes(b'original')
        r=p.Resultat(mode='unique')
        with patch.object(render,'trouver_gabarit',return_value=GABARIT):
            attendus=p._produire([self.dossier()],self.cfg,self.root,'TEST',False,[],r,dry_run=True)
        self.assertEqual(cible.read_bytes(),b'original')
        self.assertNotEqual(attendus[0],cible)

    def test_libelle_formulaire_ne_devient_pas_mrn(self):
        self.assertNotIn('21ITREFERENTE02074',e.candidats_mrn('21 IT REFERENTE 02074'))

    def test_mrn_nom_avec_prefixe_dm(self):
        self.assertEqual(p.mrn_depuis_nom(Path('DM PMP 20990102 - 26CH07STD0TEST0001.pdf')),'26CH07STD0TEST0001')
        d=self.dossier('26CH07STDOTEST0001')
        p._resoudre_identifiants(d,Path('DM PMP 20990102 - 26CH07STD0TEST0001.pdf'))
        self.assertEqual(d.mrn,'26CH07STDOTEST0001')
        self.assertTrue(any('différent' in a for a in d.avertissements))

    def test_codes_barres_uniquement_premiere_page(self):
        import io
        spec=importlib.util.spec_from_file_location('gabarit_test',GABARIT)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        d=self.dossier();d.entete=[[f'Champ {i}',f'Valeur {i}'] for i in range(100)]
        data=render.dossiers_vers_data([d],self.cfg)
        c=module.canvas.Canvas(io.BytesIO(),pagesize=module.A4)
        with patch.object(module,'barcodes',wraps=module.barcodes) as codes:
            nb=module.page_annonce(c,data,1,9)
            self.assertGreater(nb,1)
            module.page_inventaire(c,data,data['articles'],nb+1,nb+1,True)
        self.assertEqual(codes.call_count,1)

if __name__=='__main__':
    unittest.main()
