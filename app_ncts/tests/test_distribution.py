"""Distribution : fichier .env, préparation du dossier projet, exécutable figé.

Tout est hors ligne et fictif. Le mode « figé » (PyInstaller) est simulé en
patchant `plateforme.est_fige` ; aucun exécutable n'est construit ici.
"""
import copy
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ulix_ncts import config, plateforme, render, extract as e  # noqa: E402
import lancer  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
GABARIT = ROOT / render.GABARIT_REL


class FichierEnv(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for cle in ("OLLAMA_API_KEY", "ULIX_IA_MODELE", "ULIX_IA_ACTIVE", "ULIX_TEST_VIDE"):
            os.environ.pop(cle, None)
            self.addCleanup(os.environ.pop, cle, None)

    def test_lecture_tolerante(self):
        env = self.root / ".env"
        env.write_text('# commentaire\n\nOLLAMA_API_KEY="abc def"\nexport ULIX_IA_MODELE=\'m:cloud\'\n'
                       'ULIX_IA_ACTIVE=false # inline\nULIX_TEST_VIDE=\nMAL FORMEE\n', encoding="utf-8")
        lu = config.lire_dotenv(env)
        self.assertEqual(lu["OLLAMA_API_KEY"], "abc def")
        self.assertEqual(lu["ULIX_IA_MODELE"], "m:cloud")
        self.assertEqual(lu["ULIX_IA_ACTIVE"], "false")
        self.assertEqual(lu["ULIX_TEST_VIDE"], "")
        self.assertNotIn("MAL FORMEE", lu)
        self.assertEqual(config.lire_dotenv(self.root / "absent.env"), {})

    def test_environnement_prioritaire_et_valeur_vide_ignoree(self):
        (self.root / ".env").write_text("OLLAMA_API_KEY=du_fichier\nULIX_IA_MODELE=\nULIX_IA_ACTIVE=false\n",
                                        encoding="utf-8")
        os.environ["OLLAMA_API_KEY"] = "de_l_environnement"
        lus = config.charger_env(self.root / "inexistant", self.root)
        self.assertEqual(lus, [self.root / ".env"])
        self.assertEqual(os.environ["OLLAMA_API_KEY"], "de_l_environnement")
        self.assertNotIn("ULIX_IA_MODELE", os.environ)
        cfg = config.charger(self.root / "app", self.root)
        self.assertFalse(cfg["ia"]["active"])

    def test_modele_par_defaut_et_exemple_coherents(self):
        from ulix_ncts import ia
        cfg = copy.deepcopy(config.DEFAULTS)
        self.assertEqual(ia.configuration(cfg)["modele"], "deepseek-v4.1-flash:cloud")
        exemple = config.lire_dotenv(ROOT.parent / ".env.example")
        self.assertEqual(exemple["ULIX_IA_MODELE"], "deepseek-v4.1-flash:cloud")
        self.assertEqual(exemple["OLLAMA_API_KEY"], "", "aucune clé ne doit figurer dans l'exemple")


class PreparationProjet(unittest.TestCase):
    def test_dossiers_et_env_crees_une_seule_fois(self):
        with tempfile.TemporaryDirectory() as td:
            projet = Path(td) / "Projet"
            racine = projet / "app"
            racine.mkdir(parents=True)
            (racine / ".env.example").write_text("ULIX_IA_MODELE=exemple\n", encoding="utf-8")
            cfg = config.charger(racine, projet)
            faits = lancer.preparer_projet(cfg, racine)
            self.assertEqual(len(faits), 5, faits)
            for nom in ("Dépôts unique", "Dépôts multiple", "Annonces d'arrivées", "Archive"):
                self.assertTrue((projet / "data" / nom).is_dir(), nom)
            self.assertEqual((projet / ".env").read_text(encoding="utf-8"), "ULIX_IA_MODELE=exemple\n")
            (projet / ".env").write_text("OLLAMA_API_KEY=secret\n", encoding="utf-8")
            self.assertEqual(lancer.preparer_projet(cfg, racine), [])
            self.assertIn("secret", (projet / ".env").read_text(encoding="utf-8"))

    def test_option_projet_et_variable(self):
        with tempfile.TemporaryDirectory() as td:
            projet = Path(td) / "Ailleurs"
            with patch.dict(os.environ, {"ULIX_PROJET": str(projet)}), \
                    patch.object(lancer.pipeline, "executer") as ex, \
                    patch.object(lancer, "verifier_environnement", return_value=[]), \
                    patch("builtins.print"):
                self.assertEqual(lancer.main(["--preparer", "--sans-couleur"]), 0)
                ex.assert_not_called()
            noms = sorted(d.name for d in (projet / "data").iterdir() if d.is_dir())
            self.assertEqual(len(noms), 4, noms)
            self.assertTrue(any(n.startswith("D") and n.endswith("unique") for n in noms), noms)
            self.assertTrue((projet / ".env").is_file())


class RechercheVenv(unittest.TestCase):
    def test_dossier_voisin_illisible_ignore(self):
        """Runner GitHub : /home/packer n'est pas lisible, is_file() lève PermissionError."""
        vrai_is_file = Path.is_file

        def is_file_capricieux(self):
            if "interdit" in self.parts:
                raise PermissionError(13, "Permission denied", str(self))
            return vrai_is_file(self)

        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            (base / "interdit").mkdir()
            (base / "projet" / "app").mkdir(parents=True)
            with patch.object(Path, "is_file", is_file_capricieux):
                self.assertIsNone(plateforme.chercher_python(base / "projet" / "app", profondeur=1))


class ExecutableFige(unittest.TestCase):
    def test_gabarit_embarque_prioritaire(self):
        with tempfile.TemporaryDirectory() as td:
            ressources = Path(td)
            embarque = ressources / render.GABARIT_REL
            embarque.parent.mkdir(parents=True)
            embarque.write_text("# gabarit embarqué\n")
            with patch.object(plateforme, "est_fige", return_value=True), \
                    patch.object(plateforme, "dossier_ressources", return_value=ressources):
                self.assertEqual(render.trouver_gabarit(Path(td) / "projet"), embarque)

    def test_rendu_relance_l_executable(self):
        d = e.Dossier(mrn="26CH07STTEST000001", dm="DM TEST", date="01.01.2026", mrn_verifie=True,
                      articles=[e.Article(designation="Test", code_nc="63071000", brut="12 kg",
                                          net="10 kg", colis="2")],
                      total={"brut": "12 kg", "colis": "2 colis"},
                      parties=[{"role": "Expéditeur", "lignes": ["SOCIETE TEST"]}])
        cfg = copy.deepcopy(config.DEFAULTS)
        data = render.dossiers_vers_data([d], cfg)
        with tempfile.TemporaryDirectory() as td:
            sortie = Path(td) / "annonce.pdf"
            appels = []

            def faux_run(cmd, **kw):
                appels.append(cmd)
                # le sous-processus réel exécuterait le gabarit : on rejoue ici
                # l'option interne dans ce processus pour vérifier le contrat
                code = lancer.main(cmd[1:])
                self.assertEqual(code, 0)

                class CP:
                    returncode = code
                    stdout = stderr = ""
                return CP()

            with patch.object(plateforme, "est_fige", return_value=True), \
                    patch.object(render.subprocess, "run", side_effect=faux_run):
                ok, msg = render.generer(data, sortie, GABARIT)
            self.assertTrue(ok, msg)
            self.assertEqual(appels[0][:2], [sys.executable, "--rendu-gabarit"])
            self.assertEqual(appels[0][2], str(GABARIT))
            self.assertEqual(sortie.read_bytes()[:5], b"%PDF-")

    def test_binaires_embarques_prioritaires(self):
        with tempfile.TemporaryDirectory() as td:
            app = Path(td) / "app"
            faux = app / "bin" / "poppler" / "pdftotext"
            faux.parent.mkdir(parents=True)
            faux.write_text("#!/bin/sh\n")
            with patch.object(plateforme, "dossier_application", return_value=app):
                plateforme.oublier_binaires()
                try:
                    self.assertEqual(plateforme.chemin_binaire("pdftotext"), str(faux))
                    env = plateforme.environnement_sous_processus()
                finally:
                    plateforme.oublier_binaires()


if __name__ == "__main__":
    unittest.main()
