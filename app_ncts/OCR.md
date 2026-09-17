# OCR local PaddleOCR

La couche texte native du PDF reste prioritaire. Pour les pages sans texte exploitable ou dont le classement est ambigu, PaddleOCR lit le bandeau après correction de l’orientation (0, 90, 180 ou 270 degrés). Il remplace Tesseract ; aucun binaire Tesseract n’est requis.

Modèles CPU : `PP-OCRv6_small_det`, `PP-OCRv6_small_rec` et `PP-LCNet_x1_0_doc_ori`. Les versions Python sont épinglées dans `requirements.txt`. Les modèles restent chargés pendant la surveillance.

Relancer `Installer.command` (macOS) ou `Installer.cmd` (Windows) pour installer les dépendances et télécharger les modèles. Sur ce poste, cette préparation a déjà été réalisée. Redémarrer la surveillance pour charger le nouveau code.

Vérification depuis `app_ncts` :

```sh
.venv/bin/python lancer.py --statut-ocr
```

Les PDF restent locaux pendant l’OCR. Après téléchargement initial, les poids sont réutilisés depuis le cache PaddleX. Les distributions embarquent leurs modèles. `ULIX_OCR_MODELES` permet de désigner un dossier contenant les trois sous-dossiers de modèles ; un modèle manquant provoque une erreur explicite.

Ce changement concerne la lecture OCR existante, notamment le classement des pages. Il ne remplace ni les contrôles MRN/code-barres, ni la recherche BI/CargoWise, ni la validation humaine. Des confusions entre I et 1 restent possibles ; aucune donnée absente n’est inventée.
