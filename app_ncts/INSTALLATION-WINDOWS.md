# Installation sur Windows

L'outil fonctionne à l'identique sur macOS et Windows. Ce document ne couvre que
ce qui change sur Windows.

## En trois étapes

1. Copier le dossier `app_ncts` complet, **avec son sous-dossier `Documentation`**, à côté
   des dossiers de dépôt, comme sur macOS :

   ```
   hermes\
   ├── data\
   │   ├── Dépôts unique\   <- les fichiers à traiter sont déposés ici
   │   ├── Dépôts multiple\
   │   ├── Annonces d'arrivées\
   │   └── Archive\
   └── app_ncts\             <- le programme
       └── Documentation\   <- les scripts de rendu
   ```

2. Double-cliquer **`Installer.cmd`** (une seule fois). Il crée
   l'environnement Python local et installe PaddleOCR et ses modèles, puis vérifie poppler.

3. Double-cliquer **`Surveiller.cmd`** et laisser la fenêtre ouverte. Déposer un
   PDF dans un dépôt suffit : l'annonce se génère seule.

Pour un traitement ponctuel, double-cliquer **`Lancer.cmd`**.

## Ce qu'il faut installer avant

Deux choses, une seule fois par poste. Aucune ne demande de droits
administrateur pour l'outil lui-même, mais poppler peut en demander
pour s'installer dans `Program Files`.

| Élément | Où | Remarque |
|---|---|---|
| **Python 3** | https://www.python.org/downloads/ | cocher **« Add Python to PATH »** pendant l'installation |
| **poppler** | https://github.com/oschwartz10612/poppler-windows/releases | télécharger l'archive, l'extraire dans `C:\Program Files\poppler` |

`Installer.cmd` détecte ces outils et affiche ces liens si l'un manque.

## Si poppler est installé ailleurs

C'est le piège le plus courant sur Windows : l'archive de poppler est souvent
extraite dans un dossier que personne n'a ajouté au `PATH`. Le programme cherche
alors tout seul dans les emplacements habituels (`C:\Program Files\poppler\…`,
`C:\poppler\…`) et dans les
archives extraites nommées `poppler-*`.

Si les vôtres sont ailleurs, indiquez leurs dossiers dans `config.json` :

```json
"binaires": [
    "D:\\outils\\poppler-24.08.0\\Library\\bin"
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
- Sous `data/`, `Archive/`, `Annonces d'arrivées/` et les dossiers de dépôt gardent les mêmes
  noms. Les noms accentués sont acceptés (le programme résout les variantes
  d'accents), mais des noms sans accents (`Depots unique`, `Annonces d'arrivees`)
  évitent toute mauvaise surprise en ligne de commande.


# Récapitulatif installation rapide

```powershell
winget install Python.Python.3.12
winget install -e --id oschwartz10612.Poppler

.\Installer.cmd
```

Puis ferme et rouvre PowerShell, et vérifie :

```powershell
python --version
pdfinfo -v
pdftoppm -v
```

Puis ferme et rouvre Powershell dans le dossier "app_ncts"

lancer la commande suivante:

```powershell
python.exe lancer.py --cle-ia <MACLE_OLLAMA>
.\Surveiller.cmd
```

Les tests métier sont disponibles avec `.venv\Scripts\python.exe -m unittest discover -s tests -v`.

PaddleOCR travaille localement sur CPU. Une connexion est nécessaire lors de l’installation des modèles. Vérifier ensuite avec `.venv\Scripts\python.exe lancer.py --statut-ocr`. Voir [OCR.md](OCR.md).

## Version installée : connexion au MCP CargoWise direct

Utiliser un installateur construit depuis la version du client prenant en charge
`params` et `cargowise_find_by_mrn`. Modifier une URL ne met pas à jour un ancien
exécutable. Les réglages privés du Mac ne sont pas inclus dans le paquet GitHub.

Depuis `Documents\ULIX NCTS`, arrêter la surveillance :

```powershell
.\Surveillance.cmd --kill
notepad .env
```

Dans ce fichier privé, ajouter ou remplacer la ligne `CW_MCP_URL` par l’URL
privée du MCP CargoWise fournie séparément. Ne pas conserver plusieurs lignes
pour la même variable. Retirer les anciennes valeurs `CW_MCP_TOKEN` et
`CW_OAUTH_*` d’IKAMO si elles sont présentes. Les variables Windows du même nom
priment sur `.env` : les corriger aussi si elles avaient été définies.

Le nouveau MCP testé fonctionne sans parcours OAuth : **ne pas lancer
`Lancer.cmd --autoriser` pour ce serveur**. Cette option reste disponible pour
les serveurs protégés par OAuth ; elle cible le serveur configuré.

Vérifier une déclaration connue, puis démarrer la surveillance :

```powershell
.\Lancer.cmd --statut-cargowise --cle-cargowise VOTRE_CLE_NCT
.\Surveillance.cmd
```

Remplacer `VOTRE_CLE_NCT` par une clé NCT réelle pour le diagnostic.
Le PID de surveillance confirme uniquement le lancement du processus : consulter
`Surveillance.log` pour les erreurs de connexion ou de traitement.

La recherche BI de repli nécessite aussi sa configuration privée sur ce poste.
La connexion IA, configurée par `--cle-ia`, est indépendante de CargoWise.
