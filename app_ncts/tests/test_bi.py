"""Recherche BI fictive et relecture obligatoire via IKAMO."""
import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ulix_ncts import bi_client as bi, cw_client as cw, config

MRN = '26CH07STTEST000002'


class Client:
    def __init__(self):
        self.rows = [{'mrn': MRN, 'declarationKey': 'NCT00000001'}]
        self.connected = True
        self.colonnes = ['TransitMRN', 'NctKey']
        self.appels = []
        self.truncated = False

    def initialiser(self):
        pass

    def lister_outils(self):
        return []

    def appeler_outil(self, outil, args):
        self.appels.append((outil, args))
        if outil == 'mssql_connection_status':
            return json.dumps({'connected': self.connected, 'database': 'TEST'})
        if outil == 'mssql_describe_table':
            return json.dumps({'columns': [{'name': n} for n in self.colonnes]})
        return json.dumps({'rows': self.rows, 'truncated': self.truncated})


class RechercheBI(unittest.TestCase):
    def setUp(self):
        self.cfg = copy.deepcopy(config.DEFAULTS)
        self.cfg['bi'].update(active=True, url='https://example.invalid/private',
                              database='TEST', table='Transits',
                              colonne_mrn='TransitMRN', colonne_nct='NctKey')
        self.client = Client()

    def resoudre(self, mrns=None):
        with patch.object(bi, '_MCP', return_value=self.client):
            return bi.resoudre(self.cfg, [MRN] if mrns is None else mrns)

    def test_correspondance_unique_et_requete_bornee(self):
        r = self.resoudre()
        self.assertEqual(r.cles, {'NCT00000001': MRN})
        self.assertEqual(r.source, 'TEST.dbo.Transits')
        q = self.client.appels[-1][1]
        self.assertIn('SELECT DISTINCT TOP (2)', q['sql'])
        self.assertIn("WHERE [TransitMRN] = '" + MRN + "'", q['sql'])
        self.assertEqual(q['max_rows'], 2)

    def test_sql_indisponible_ne_devient_pas_absence(self):
        self.client.connected = False
        r = self.resoudre()
        self.assertFalse(r.cles)
        self.assertIn('connexion SQL indisponible', r.messages[0])
        self.assertEqual(len(self.client.appels), 1)

    def test_mapping_absent_et_schema_change(self):
        self.client.colonnes = ['Autre']
        self.assertFalse(self.resoudre().cles)
        self.cfg['bi']['table'] = ''
        self.assertIn('à configurer', self.resoudre().messages[0])

    def test_mauvaise_base(self):
        self.cfg['bi']['database'] = 'AUTRE'
        self.assertFalse(self.resoudre().cles)
        self.assertEqual(len(self.client.appels), 1)

    def test_mrn_invalide_avant_reseau(self):
        self.assertFalse(self.resoudre(["'; DROP TABLE X"]).cles)
        self.assertEqual(self.client.appels, [])

    def test_absent_ambigu_tronque_mrn_et_cle_errones(self):
        for rows, tronque in [([], False), (self.client.rows * 2, False),
                              (self.client.rows, True),
                              ([{'mrn': '26CH07STTEST000005', 'declarationKey': 'NCT00000001'}], False),
                              ([{'mrn': MRN, 'declarationKey': 'S00000001'}], False)]:
            with self.subTest(rows=rows, tronque=tronque):
                self.client.rows, self.client.truncated = rows, tronque
                self.assertFalse(self.resoudre().cles)

    def test_erreur_ne_divulgue_pas_url(self):
        with patch.object(bi, '_MCP', side_effect=OSError('https://example.invalid/private')):
            r = bi.resoudre(self.cfg, [MRN])
        self.assertNotIn('private', ' '.join(r.messages))

    def test_bi_vers_cw_avec_confirmation_mrn_et_arrivee(self):
        self.cfg['cargowise']['active'] = True
        class CW:
            def nom_outil(self, *args): return 'cargowise_get_ncts'
            def parametre(self, *args): return 'declarationKey'
            def appeler_outil(self, outil, args):
                return json.dumps({'mrn': MRN, 'movement_type': 'A', 'lrn': 'DM TEST'})
        with patch.object(bi, '_MCP', return_value=self.client), \
             patch.object(cw, 'connecter', return_value=(CW(), cw.ResultatCW())):
            r = cw.interroger(self.cfg, [], mrns=[MRN])
        self.assertTrue(r.ok)
        self.assertEqual(r.entete['NCT00000001']['lrn'], 'DM TEST')
        self.assertEqual(r.entete['NCT00000001']['source_liaison_bi'], 'TEST.dbo.Transits')

    def test_aucune_lecture_cw_si_bi_ambigue(self):
        self.cfg['cargowise']['active'] = True
        self.client.rows *= 2
        with patch.object(bi, '_MCP', return_value=self.client), \
             patch.object(cw, 'connecter', return_value=(object(), cw.ResultatCW())):
            r = cw.interroger(self.cfg, [], mrns=[MRN])
        self.assertFalse(r.ok)
        self.assertTrue(any('plusieurs correspondances' in m for m in r.avertissements))

    def test_document_vers_dossier_avec_base_source(self):
        self.cfg['bi'].update(mode='documents', source_database='SOURCE',
                              colonne_document='Filename', colonne_dossier='Shipment')
        self.client.colonnes = ['Filename', 'Shipment']
        self.client.rows = [{'shipmentKey': 'SBDY00000001'}]
        r = self.resoudre()
        self.assertEqual(r.dossiers, {MRN: 'SBDY00000001'})
        self.assertFalse(r.cles)
        self.assertIn('[SOURCE].[dbo].[Transits]', self.client.appels[-1][1]['sql'])
        self.assertIn("IN ('" + MRN + "', '" + MRN + ".pdf')", self.client.appels[-1][1]['sql'])

    def test_dossier_confirme_sans_nct_ne_valide_pas_le_transit(self):
        class CW:
            def nom_outil(self, candidats): return candidats[0]
            def appeler_outil(self, outil, args):
                return json.dumps({'documents': [{'file_name': MRN + '.pdf'}],
                                   'related': [{'key': 'SBDY00000001'}]})
        resolution = bi.ResultatBI(dossiers={MRN: 'SBDY00000001'}, source='TEST')
        r = cw._interroger_dossiers_bi(CW(), cw.ResultatCW(), resolution)
        self.assertFalse(r.ok)
        self.assertEqual(r.liaisons_bi[MRN]['dossier'], 'SBDY00000001')
        self.assertFalse(r.entete)

    def test_document_doit_etre_confirme_et_arrivee_unique(self):
        class CW:
            def nom_outil(self, candidats): return candidats[0]
            def appeler_outil(self, outil, args):
                if outil == 'cargowise_get_shipment_context':
                    return json.dumps({'documents': [{'file_name': self.fichier}],
                        'related': [{'key': k} for k in self.cles]})
                return json.dumps({'mrn': MRN, 'movement_type': self.mouvement,
                                   'lrn': 'DM TEST'})
        client = CW()
        resolution = bi.ResultatBI(dossiers={MRN: 'SBDY00000001'}, source='TEST')
        for fichier, cles, mouvement, ok in [
            (MRN + '.pdf', ['NCT00000001'], 'A', True),
            ('autre.pdf', ['NCT00000001'], 'A', False),
            (MRN + '.pdf', ['NCT00000001'], 'D', False),
            (MRN + '.pdf', ['NCT00000001', 'NCT00000002'], 'A', False)]:
            with self.subTest(fichier=fichier, cles=cles, mouvement=mouvement):
                client.fichier, client.cles, client.mouvement = fichier, cles, mouvement
                r = cw._interroger_dossiers_bi(client, cw.ResultatCW(), resolution)
                self.assertEqual(r.ok, ok)
