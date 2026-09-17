"""Rapprochement automatique : aucun accès réseau ni donnée client."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ulix_ncts import config, cw_client as cw, pipeline, extract

MRN = '26CH07STTEST000002'


class Recherche(unittest.TestCase):
    def setUp(self):
        self.cfg = copy.deepcopy(config.DEFAULTS)
        self.cfg['cargowise']['active'] = True
        self.reponse = {'mrn': MRN, 'complete': True, 'matches': [
            {'declarationKey': 'NCT00000001', 'mrn': MRN, 'movement_type': 'A'}]}
        self.entete = {'mrn': MRN, 'movement_type': 'A', 'lrn': 'DM TEST'}
        self.appels = []
        self.disponible = True

    def appel(self, outil, arguments):
        self.appels.append((outil, arguments))
        return json.dumps(self.reponse if outil == 'cargowise_find_arrival_by_mrn' else self.entete)

    def interroger(self):
        test = self
        class Client:
            def nom_outil(self, candidats, motif=''):
                if candidats == ['cargowise_find_arrival_by_mrn']:
                    return candidats[0] if test.disponible else ''
                return 'cargowise_get_ncts'
            def parametre(self, *args):
                return 'declarationKey'
            def appeler_outil(self, outil, arguments):
                return test.appel(outil, arguments)
        with patch.object(cw, 'connecter', return_value=(Client(), cw.ResultatCW())):
            return cw.interroger(self.cfg, [], mrns=[MRN])

    def test_recherche_puis_relecture_exacte(self):
        res = self.interroger()
        self.assertTrue(res.ok)
        self.assertEqual(res.entete['NCT00000001']['lrn'], 'DM TEST')
        self.assertEqual(self.appels, [
            ('cargowise_find_arrival_by_mrn', {'mrn': MRN}),
            ('cargowise_get_ncts', {'declarationKey': 'NCT00000001'})])

    def test_outil_absent_ne_signifie_pas_dossier_absent(self):
        self.disponible = False
        res = self.interroger()
        self.assertFalse(res.ok)
        self.assertIn('Aucune recherche effectuée', res.message)
        self.assertEqual(self.appels, [])

    def test_aucun_resultat_ambigu_incomplet_et_mauvais_mrn(self):
        original = copy.deepcopy(self.reponse)
        for champ, valeur in [('matches', []), ('matches', original['matches'] * 2),
                              ('complete', False), ('mrn', '26CH07STTEST000005')]:
            with self.subTest(champ=champ, valeur=valeur):
                self.reponse = {**original, champ: valeur}
                self.appels = []
                self.assertFalse(self.interroger().ok)
                self.assertEqual(len(self.appels), 1)

    def test_relecture_cw_contredit_recherche(self):
        for champ, valeur in [('mrn', '26CH07STTEST000005'), ('movement_type', 'D')]:
            with self.subTest(champ=champ):
                self.entete = {'mrn': MRN, 'movement_type': 'A', champ: valeur}
                self.assertFalse(self.interroger().ok)

    def test_erreur_mcp_ne_devient_pas_resultat(self):
        client = cw._MCP('https://example.invalid')
        with patch.object(client, 'appeler', return_value={
                'isError': True, 'content': [{'type': 'text', 'text': 'indisponible'}]}):
            with self.assertRaises(RuntimeError):
                client.appeler_outil('recherche', {'mrn': MRN})

    def test_pipeline_lit_pdf_avant_recherche_et_conserve_donnees_si_erreur(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.cfg['_projet'] = td
            self.cfg['dossiers'] = {k: str(root / k) for k in self.cfg['dossiers']}
            pdf = root / 'source.pdf'
            d = extract.Dossier(mrn=MRN)
            analyse = pipeline.Analyse(pdf=pdf, dossiers=[d])
            def recherche(cfg, cles, **kwargs):
                self.assertEqual(kwargs['mrns'], [MRN])
                self.assertEqual(cles, [])
                raise RuntimeError('serveur indisponible')
            with patch.object(pipeline, 'analyser_pdf', return_value=analyse) as lire, \
                 patch.object(cw, 'interroger', side_effect=recherche), \
                 patch.object(pipeline, '_produire', return_value=[]):
                res = pipeline.executer(self.cfg, dry_run=True, lot=([pdf], []))
            lire.assert_called_once()
            self.assertEqual(res.analyses[0].dossiers[0].mrn, MRN)
            self.assertTrue(any('serveur indisponible' in m for m in analyse.messages))
