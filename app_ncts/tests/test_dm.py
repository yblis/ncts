"""Tests fictifs du compteur partagé ; aucun numéro réel réservé."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from ulix_ncts import dm, dm_service, pipeline
from ulix_ncts.extract import Dossier


def mrn(n):
    return f'26CH{n:014d}'


class RegistreDM(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.horloge = patch.object(dm, 'annee_courante', return_value=2026)
        self.horloge.start()
        self.addCleanup(self.horloge.stop)
        self.base = Path(self.tmp.name) / 'registre.sqlite3'
        self.reg = dm.Registre(self.base)

    def activer(self):
        self.reg.activer('20260040', 'Opérateur test')

    def test_preparation_sans_attribution(self):
        self.assertFalse(self.reg.statut()['actif'])
        with self.assertRaises(dm.ErreurDM):
            self.reg.attribuer([mrn(1)], 'test')
        self.assertEqual(self.reg.statut()['annonces'], 0)

    def test_bascule_unique_et_format(self):
        self.activer()
        with self.assertRaises(dm.ErreurDM):
            self.reg.activer('20260999', 'test')
        self.assertEqual(self.reg.attribuer([mrn(1)], 'test')['dm'], '20260041')

    def test_redemarrage_reimpression_prefixe(self):
        self.activer()
        a = self.reg.attribuer([mrn(1)], 'test')
        self.reg.prefixe([mrn(1)], True, 'Raymond test')
        nouveau = dm.Registre(self.base)
        b = nouveau.attribuer([mrn(1)], 'autre poste')
        self.assertEqual(b['dm'], 'PMP ' + a['dm'])
        self.assertTrue(b['reutilise'])
        self.assertEqual(nouveau.statut()['compteurs'][0]['dernier'], 41)
        nouveau.prefixe([mrn(1)], False, 'test')
        self.assertEqual(nouveau.attribuer([mrn(1)], 'test')['dm'], a['dm'])

    def test_concurrence_postes(self):
        self.activer()
        with ThreadPoolExecutor(max_workers=8) as ex:
            valeurs = list(ex.map(lambda n: dm.Registre(self.base).attribuer([mrn(n)], 'poste')['dm'], range(1, 25)))
        self.assertEqual(len(set(valeurs)), 24)
        self.assertEqual(self.reg.statut()['compteurs'][0]['dernier'], 64)

    def test_concurrence_meme_annonce(self):
        self.activer()
        with ThreadPoolExecutor(max_workers=8) as ex:
            valeurs = list(ex.map(lambda n: dm.Registre(self.base).attribuer([mrn(1)], 'poste')['dm'], range(16)))
        self.assertEqual(set(valeurs), {'20260041'})

    def test_multi_ordre_et_chevauchement(self):
        self.activer()
        a = self.reg.attribuer([mrn(2), mrn(1)], 'test')
        self.assertEqual(self.reg.attribuer([mrn(1), mrn(2)], 'test')['dm'], a['dm'])
        for refs in ([mrn(1)], [mrn(2), mrn(3)]):
            with self.assertRaises(dm.ErreurDM):
                self.reg.attribuer(refs, 'test')
        self.assertEqual(self.reg.statut()['annonces'], 1)

    def test_changement_annee_et_ancienne_reimpression(self):
        self.activer()
        self.reg.attribuer([mrn(1)], 'test')
        with patch.object(dm, 'annee_courante', return_value=2027):
            self.assertEqual(self.reg.attribuer([mrn(2)], 'test')['dm'], '20270001')
            self.assertEqual(self.reg.attribuer([mrn(1)], 'test')['dm'], '20260041')

    def test_simulation_sans_consommation(self):
        self.activer()
        self.assertEqual(self.reg.attribuer([mrn(1)], simulation=True)['dm'], '')
        self.assertEqual(self.reg.statut()['annonces'], 0)
        self.assertEqual(self.reg.statut()['compteurs'][0]['dernier'], 40)

    def test_import_sisa_et_doublons(self):
        self.activer()
        self.assertEqual(self.reg.attribuer([mrn(1)], 'test', 'PMP 20260012')['dm'], 'PMP 20260012')
        with self.assertRaises(dm.ErreurDM):
            self.reg.attribuer([mrn(2)], 'test', '20260012')
        with self.assertRaises(dm.ErreurDM):
            self.reg.attribuer([mrn(1)], 'test', '20260013')
        with self.assertRaises(dm.ErreurDM):
            self.reg.attribuer([mrn(2)], 'test', '20260045')
        self.assertEqual(self.reg.attribuer([mrn(3)], 'test')['dm'], '20260041')

    def test_erreur_ne_consomme_pas(self):
        self.activer()
        with self.assertRaises(dm.ErreurDM):
            self.reg.attribuer([mrn(1)], '')
        self.assertEqual(self.reg.statut()['annonces'], 0)
        self.assertEqual(self.reg.attribuer([mrn(1)], 'test')['dm'], '20260041')

    def test_compteur_sature(self):
        self.reg.activer('20269999', 'test')
        with self.assertRaises(dm.ErreurDM):
            self.reg.attribuer([mrn(1)], 'test')
        self.assertEqual(self.reg.statut()['annonces'], 0)

    def test_mrn_invalide_ou_duplique(self):
        self.activer()
        for refs in ([], ['inconnu'], [mrn(1), mrn(1)]):
            with self.assertRaises(dm.ErreurDM):
                self.reg.attribuer(refs, 'test')

    def test_http_auth_et_reprise(self):
        self.activer()
        token = 'x' * 40
        service = dm_service.serveur(self.reg, token, ('127.0.0.1', 0))
        thread = threading.Thread(target=service.serve_forever, daemon=True)
        thread.start()
        try:
            cfg = {'url': f'http://127.0.0.1:{service.server_port}', 'token': token, 'operateur': 'test'}
            client = dm_service.Client(cfg)
            self.assertTrue(client.appeler('/statut')['actif'])
            self.assertEqual(client.attribuer([mrn(1)])['dm'], '20260041')
            self.assertEqual(client.attribuer([mrn(1)])['dm'], '20260041')
            self.assertEqual(client.attribuer([mrn(2)], simulation=True)['dm'], '')
            with self.assertRaises(dm.ErreurDM):
                dm_service.Client({**cfg, 'token': 'faux'}).appeler('/statut')
            with self.assertRaises(dm.ErreurDM):
                client.appeler('/annuler', {'mrns': [mrn(1)]})
        finally:
            service.shutdown()
            service.server_close()
            thread.join()

    def test_pipeline_echec_rendu_reutilise_numero(self):
        self.activer()
        cfg = {'_projet': self.tmp.name, 'document': {'format_sortie': 'docx'}, 'dm': {'active': True}}
        def attribuer(refs, existant='', simulation=False):
            return self.reg.attribuer(refs, 'test', existant, simulation)
        with patch('ulix_ncts.dm_service.Client') as client, patch('ulix_ncts.render.dossiers_vers_data', side_effect=lambda ds, cfg: {'dm': ds[0].dm}), patch('ulix_ncts.word.generer', return_value=(False, 'panne simulée')):
            client.return_value.attribuer.side_effect = attribuer
            for i in range(2):
                dossier = Dossier(mrn=mrn(1), mrn_verifie=True)
                resultat = pipeline.Resultat(mode='unique')
                pipeline._produire([dossier], cfg, Path(self.tmp.name), 'test', False, [], resultat)
                self.assertEqual(dossier.dm, '20260041')
                self.assertEqual(resultat.modifiables, [])
            self.assertEqual(self.reg.statut()['annonces'], 1)

    def test_pipeline_conflit_bloque_rendu(self):
        cfg = {'_projet': self.tmp.name, 'document': {'format_sortie': 'docx'}, 'dm': {'active': True}}
        ds = [Dossier(mrn=mrn(1), mrn_verifie=True, dm='20260001'), Dossier(mrn=mrn(2), mrn_verifie=True, dm='20260002')]
        resultat = pipeline.Resultat(mode='multiple')
        with patch('ulix_ncts.dm_service.Client') as client, patch('ulix_ncts.word.generer') as rendu:
            pipeline._produire(ds, cfg, Path(self.tmp.name), 'test', True, [], resultat)
            client.assert_not_called()
            rendu.assert_not_called()
            self.assertIn('Plusieurs DM', resultat.messages[0])

    def test_dm_source_ancien_libelle(self):
        self.activer()
        self.assertEqual(self.reg.attribuer([mrn(1)], 'test', 'DM 20260010')['dm'], '20260010')

    def test_horloge_recule_apres_nouvel_an(self):
        self.activer()
        with patch.object(dm, 'annee_courante', return_value=2027):
            self.reg.attribuer([mrn(1)], 'test')
        with self.assertRaises(dm.ErreurDM):
            self.reg.attribuer([mrn(2)], 'test')

    def test_pipeline_multi_transmet_meme_dm_au_rendu(self):
        self.activer()
        cfg = {'_projet': self.tmp.name, 'document': {'format_sortie': 'docx'}, 'dm': {'active': True}}
        ds = [Dossier(mrn=mrn(n), mrn_verifie=True) for n in (1, 2)]
        resultat = pipeline.Resultat(mode='multiple')
        def traduire(ds, cfg):
            self.assertEqual([d.dm for d in ds], ['20260041', '20260041'])
            return {'dm': ds[0].dm}
        with patch('ulix_ncts.dm_service.Client') as client, patch('ulix_ncts.render.dossiers_vers_data', side_effect=traduire), patch('ulix_ncts.word.generer', return_value=(True, 'ok')) as rendu:
            client.return_value.attribuer.side_effect = lambda refs, existant='', simulation=False: self.reg.attribuer(refs, 'test', existant, simulation)
            pipeline._produire(ds, cfg, Path(self.tmp.name), 'test', True, [], resultat)
            self.assertEqual(rendu.call_args.args[0]['dm'], '20260041')
            self.assertEqual(len(resultat.modifiables), 1)
        self.assertEqual(self.reg.statut()['annonces'], 1)

    def test_service_absent_bloque_production(self):
        cfg = {'_projet': self.tmp.name, 'document': {'format_sortie': 'docx'}, 'dm': {'active': True}}
        resultat = pipeline.Resultat(mode='unique')
        with patch('ulix_ncts.dm_service.Client', side_effect=dm.ErreurDM('indisponible')), patch('ulix_ncts.word.generer') as rendu:
            pipeline._produire([Dossier(mrn=mrn(1), mrn_verifie=True)], cfg, Path(self.tmp.name), 'test', False, [], resultat)
            rendu.assert_not_called()
            self.assertIn('indisponible', resultat.messages[0])

    def test_pipeline_simulation_aucune_reservation(self):
        self.activer()
        cfg = {'_projet': self.tmp.name, 'document': {'format_sortie': 'docx'}, 'dm': {'active': True}}
        with patch('ulix_ncts.dm_service.Client') as client, patch('ulix_ncts.render.dossiers_vers_data', return_value={'dm': ''}), patch('ulix_ncts.word.generer') as rendu:
            client.return_value.attribuer.side_effect = lambda refs, existant='', simulation=False: self.reg.attribuer(refs, 'test', existant, simulation)
            pipeline._produire([Dossier(mrn=mrn(1), mrn_verifie=True)], cfg, Path(self.tmp.name), 'test', False, [], pipeline.Resultat(mode='unique'), dry_run=True)
            rendu.assert_not_called()
        self.assertEqual(self.reg.statut()['annonces'], 0)
