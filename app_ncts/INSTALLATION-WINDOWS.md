# Installation sur Windows

L'outil fonctionne à l'identique sur macOS et Windows. Ce document ne couvre que
ce qui change sur Windows.

## En trois étapes

1. Copier le dossier `app_ncts` complet, **avec son sous-dossier `Documentation`**, à côté
   des dossiers de dépôt, comme sur macOS :

   ```
   hermes\
   ├── Dépots unique\        <- les fichiers à traiter sont déposés ici
   ├── Dépots multiple\
   ├── Annonces d'arrivées\
   ├── Archive\
   └── app_ncts\             <- le programme
       └── Documentation\   <- les scripts de rendu
   ```

2. Double-cliquer **`Installer.cmd`** (une seule fois). Il crée
   l'environnement Python local et vérifie la présence de poppler et tesseract.

3. Double-cliquer **`Surveiller.cmd`** et laisser la fenêtre ouverte. Déposer un
   PDF dans un dépôt suffit : l'annonce se génère seule.

Pour un traitement ponctuel, double-cliquer **`Lancer.cmd`**.

## Ce qu'il faut installer avant

Trois choses, une seule fois par poste. Aucune ne demande de droits
administrateur pour l'outil lui-même, mais poppler et tesseract en demandent
pour s'installer dans `Program Files`.

| Élément | Où | Remarque |
|---|---|---|
| **Python 3** | https://www.python.org/downloads/ | cocher **« Add Python to PATH »** pendant l'installation |
| **poppler** | https://github.com/oschwartz10612/poppler-windows/releases | télécharger l'archive, l'extraire dans `C:\Program Files\poppler` |
| **tesseract** | https://github.com/UB-Mannheim/tesseract/wiki | cocher **English** dans les langues supplémentaires |

`Installer.cmd` détecte ces outils et affiche ces liens si l'un manque.

## Si poppler ou tesseract sont installés ailleurs

C'est le piège le plus courant sur Windows : l'archive de poppler est souvent
extraite dans un dossier que personne n'a ajouté au `PATH`. Le programme cherche
alors tout seul dans les emplacements habituels (`C:\Program Files\poppler\…`,
`C:\Program Files\Tesseract-OCR`, `%LOCALAPPDATA%\Programs\…`) et dans les
archives extraites nommées `poppler-*`.

Si les vôtres sont ailleurs, indiquez leurs dossiers dans `config.json` :

```json
"binaires": [
    "D:\\outils\\poppler-24.08.0\\Library\\bin",
    "D:\\outils\\Tesseract-OCR"
]
```

Pour vérifier que tout est trouvé :

```
.venv\Scripts\python.exe lancer.py --statut-ia
```

Et pour lister les binaires manquants, lancer simplement `lancer.py` : le
contrôle pré-vol les nomme avant de commencer.

## La clé du modèle IA

À renseigner une fois par poste :

```
.venv\Scripts\python.exe lancer.py --cle-ia VOTRE_CLE
```

Elle est enregistrée dans le profil de l'utilisateur
(`%USERPROFILE%\.ulix_ncts_ia.json`), **hors du dossier du projet** : copier le
dossier sur un autre poste ne diffuse jamais la clé.

Sans clé, le repli IA reste inactif et tout le reste fonctionne : les documents
se génèrent à partir des seuls PDF.

## Points techniques (pourquoi ces choix)

Trois différences Windows ont été traitées explicitement, chacune correspondant
à une panne réelle si elle est ignorée.

**Encodage de la console.** Le script de rendu imprime `OK → …`. Sur une console
Windows en cp1252, ce caractère `→` provoque une `UnicodeEncodeError` : le
gabarit sort en code 1 et **le PDF est signalé en échec alors qu'il a été
produit**. Le programme force donc `PYTHONUTF8=1` et `PYTHONIOENCODING=utf-8`
pour tous les sous-processus, et `chcp 65001` dans les lanceurs.

**Binaires hors du `PATH`.** Décrit plus haut : recherche dans les emplacements
Windows, surchargeable par `config.json` → `binaires`.

**Emplacement du venv.** `.venv\Scripts\python.exe` au lieu de
`.venv/bin/python3`. La résolution regarde les deux formes, et valide le candidat
avec `import reportlab` avant de l'utiliser — un mauvais interpréteur produirait
un échec de rendu silencieux.

Les fichiers `.cmd` sont écrits en **ASCII sans accents**, avec des guillemets
droits : `cmd.exe` lit les fichiers de commandes dans l'encodage OEM de la
machine, pas en UTF-8, et des accents y provoquent un affichage corrompu.

## Vérifier l'installation

```
.venv\Scripts\python.exe tools\test_windows.py
```

Ce script contrôle la résolution des chemins Windows, la recherche des
binaires, l'environnement transmis aux sous-processus et l'encodage des
lanceurs.

## Différences assumées

- Les fichiers de lancement sont `.cmd` sur Windows et `.command` sur macOS :
  les deux coexistent dans le dossier, chacun peut ignorer ceux de l'autre.
- `Archive/`, `Annonces d'arrivées/` et les dossiers de dépôt gardent les mêmes
  noms. Les noms accentués sont acceptés (le programme résout les variantes
  d'accents), mais des noms sans accents (`Depots unique`, `Annonces d'arrivees`)
  évitent toute mauvaise surprise en ligne de commande.


# Récapitulatif installation rapide

```powershell
winget install Python.Python.3.14
winget install -e --id oschwartz10612.Poppler
winget install -e --id UB-Mannheim.TesseractOCR

python -m pip install pdf2image pytesseract reportlab pillow
```

Puis ferme et rouvre PowerShell, et vérifie :

```powershell
python --version
pdfinfo -v
pdftoppm -v
tesseract --version
```

Puis ferme et rouvre Powershell dans le dossier "app_ncts"

lancer la commande suivante:

```powershell
python.exe lancer.py --cle-ia <MACLE_OLLAMA>
.\Surveiller.cmd
```

Les tests métier sont disponibles avec `.venv\Scripts\python.exe -m unittest discover -s tests -v`.
