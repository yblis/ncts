import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from PIL import Image
from ulix_ncts import ocr_paddle as moteur, pdfio


class TestPaddleOCR(unittest.TestCase):
    def test_lecture_et_erreur_explicite(self):
        lecteur = Mock()
        lecteur.predict.return_value = [{'res': {'rec_texts': ['TRANSIT', '', 'T2']}}]
        with patch.object(moteur, '_lecteur', return_value=lecteur):
            self.assertEqual(moteur.lire(Path('test.png')), 'TRANSIT\nT2')
            lecteur.predict.return_value = [{}]
            with self.assertRaises(moteur.ErreurOCR):
                moteur.lire(Path('test.png'))

    def test_orientation_confiance(self):
        modele = Mock()
        with patch.object(moteur, '_orienteur', return_value=modele):
            for angle in (0, 90, 180, 270):
                modele.predict.return_value = [{'label_names': [str(angle)], 'scores': [.95]}]
                self.assertEqual(moteur.orientation(Path('test.png')), angle)
            modele.predict.return_value = [{'label_names': ['90'], 'scores': [.4]}]
            self.assertEqual(moteur.orientation(Path('test.png')), 0)

    def test_rotation_avant_decoupe(self):
        with tempfile.TemporaryDirectory() as td:
            png = Path(td) / 'page.png'
            originale = Image.new('RGB', (100, 200), 'white')
            originale.paste('red', (0, 0, 100, 40))
            for angle in (0, 90, 180, 270):
                originale.rotate(-angle, expand=True).save(png)
                def verifier_bande(path, *args):
                    with Image.open(path) as bande:
                        self.assertEqual(bande.size, (100, 40))
                        self.assertEqual(bande.getpixel((50, 20)), (255, 0, 0))
                    return 'TRANSIT'
                with patch.object(pdfio, 'rendre_page_png', return_value=png), patch.object(pdfio, 'orientation', return_value=angle), patch.object(pdfio, 'ocr', side_effect=verifier_bande):
                    self.assertEqual(pdfio.ocr_bandeau_haut(Path('test.pdf'), 1, 200, fraction=.2), 'TRANSIT')

    def test_modele_manquant_ne_telecharge_pas_en_distribution(self):
        with tempfile.TemporaryDirectory() as td, patch.dict('os.environ', {'ULIX_OCR_MODELES': td}):
            with self.assertRaises(moteur.ErreurOCR):
                moteur._chemin_modele(moteur.DETECTION)

    def test_instance_reutilisee(self):
        moteur._lecteur.cache_clear()
        constructeur = Mock()
        try:
            with patch.object(moteur, '_importer', return_value=(constructeur, Mock())), patch.object(moteur, '_chemin_modele', return_value=None):
                self.assertIs(moteur._lecteur(), moteur._lecteur())
                constructeur.assert_called_once()
        finally:
            moteur._lecteur.cache_clear()
