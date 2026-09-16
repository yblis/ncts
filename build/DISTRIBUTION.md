# Distribution : paquets Windows, macOS et Linux

Les équipes n'installent ni Python, ni les bibliothèques, ni (sous Windows et
macOS) poppler et tesseract : tout est livré dans le paquet. Cette page décrit ce
que produit la chaîne, comment publier une version et comment dépanner.

## Ce que reçoivent les équipes

| Système | Fichier | Contenu |
|---|---|---|
| Windows | `ULIX-NCTS-<v>-windows-installateur.exe` | Installateur Inno Setup, **sans droits administrateur**. Installe dans `Documents\ULIX NCTS`, crée les dépôts, le `.env`, les raccourcis du menu Démarrer (« Surveiller les dépôts », « Traiter maintenant ») et, en option, le lancement à l'ouverture de session. |
| Windows | `ULIX-NCTS-<v>-windows-portable.zip` | Le même dossier, à décompresser n'importe où (clé USB, partage réseau). |
| macOS | `ULIX-NCTS-<v>-macos.pkg` | Installe `/Applications/ULIX NCTS` avec poppler et tesseract embarqués. Les dossiers de travail sont créés dans `~/ULIX NCTS`. |
| macOS | `ULIX-NCTS-<v>-macos.zip` | Le même dossier, à glisser où l'on veut. |
| Linux | `ulix-ncts_<v>_amd64.deb` | `sudo apt install ./ulix-ncts_<v>_amd64.deb` ; apt installe `poppler-utils` et `tesseract-ocr`. Commande `ulix-ncts`, dossiers dans `~/ULIX NCTS`. |
| Linux | `ULIX-NCTS-<v>-linux-portable.tar.gz` | Sans installation ; poppler et tesseract doivent être présents. |

Disposition du dossier livré, identique à `hermes/` en développement :

```
ULIX NCTS/
├── Dépôts unique/          1 PDF  -> 1 annonce
├── Dépôts multiple/        N PDF  -> 1 annonce
├── Annonces d'arrivées/    Prets_a_remettre/, A_verifier/, data/
├── Archive/
├── .env                    clé IA, modèle (créé depuis app/.env.example, jamais écrasé)
├── Lancer.cmd|.command     traitement à la demande
├── Surveiller.cmd|.command guetteur : déposer un PDF suffit
├── LISEZMOI.txt
└── app/
    ├── ulix-ncts(.exe)     exécutable PyInstaller
    ├── _internal/          Python, reportlab, python-docx, zxing-cpp, generate_doc.py
    └── bin/poppler, bin/tesseract (+ tessdata)   Windows et macOS seulement
```

Le dossier PROJET est le parent de `app/` (comme `hermes/` est le parent de
`app_ncts/`). Sur macOS et Linux, où le programme est installé dans un dossier
système, les lanceurs positionnent `ULIX_PROJET=~/ULIX NCTS`. L'option
`--projet DOSSIER` fait la même chose à la main.

## Le fichier `.env`

Créé au premier lancement depuis `.env.example` s'il n'existe pas. Variables
utiles :

```
OLLAMA_API_KEY=                          clé Ollama (ou serveur compatible OpenAI)
OLLAMA_BASE_URL=                         vide = https://ollama.com/v1
ULIX_IA_MODELE=deepseek-v4.1-flash:cloud modèle vision de repli
ULIX_IA_ACTIVE=true                      false = jamais d'appel au modèle
ULIX_PROJET=                             dossier de travail (facultatif)
ULIX_BINAIRES=                           poppler/tesseract hors PATH (facultatif)
```

Une variable déjà définie dans l'environnement du système garde la priorité.
Sans clé, le repli IA est désactivé et le traitement déterministe continue ;
les champs non lus sont marqués « à compléter ».

## Publier une version

```bash
# 1. mettre à jour ulix_ncts/__init__.py (__version__) et committer
# 2. poser le tag et le pousser : le workflow construit les trois systèmes
git tag v1.2.0
git push origin v1.2.0
```

`.github/workflows/construire.yml` :

1. `tests` : unittest sur Ubuntu (poppler/tesseract via apt).
2. `windows` : télécharge l'archive poppler officielle (version épinglée
   `POPPLER_WINDOWS`), installe tesseract via Chocolatey, lance
   `build/construire.py --poppler … --tesseract …`, compile l'installateur
   avec Inno Setup (préinstallé sur les runners), vérifie que l'exécutable
   démarre en `--simulation`.
3. `macos` : `brew install poppler tesseract`, `construire.py --embarquer-brew`
   (copie les dylib, réécrit les chemins, resigne ad hoc), `pkgbuild`.
4. `linux` : `construire.py` sur ubuntu-22.04 (glibc minimale), `dpkg-deb`,
   puis installation réelle du `.deb` et lancement en `--simulation`.
5. `release` (tags seulement) : Release GitHub avec les paquets et `SHA256SUMS.txt`.

Sur un push ordinaire, les paquets sont disponibles comme artefacts du
workflow (onglet Actions), sans Release.

## Construire à la main

```bash
pip install -r build/requirements-build.txt
python3 build/construire.py --version 1.2.0                       # système courant
python3 build/construire.py --embarquer-brew                      # macOS : binaires Homebrew
python  build\construire.py --poppler "C:\poppler\Library\bin" --tesseract "C:\Program Files\Tesseract-OCR"
```

Sortie dans `dist/` (ignoré par Git). `--sans-paquet` s'arrête au dossier assemblé.

## Comment le code s'adapte au mode figé

- `plateforme.est_fige()` : vrai sous PyInstaller. `dossier_application()` est le
  dossier de l'exécutable, `dossier_ressources()` le `_internal/` où vit le gabarit.
- `render.trouver_gabarit` regarde d'abord le gabarit embarqué.
- `render.generer` relance l'exécutable avec `--rendu-gabarit GABARIT JSON PDF` :
  `lancer.py` exécute alors `generate_doc.py` via `runpy` avec le reportlab
  embarqué. Le gabarit reste l'unique chemin de rendu.
- `plateforme.chemin_binaire` fouille `app/bin/poppler` et `app/bin/tesseract`
  avant le PATH ; `TESSDATA_PREFIX` et `FONTCONFIG_FILE` sont déduits.
- `lancer.preparer_projet` crée les dossiers de dépôt et le `.env` manquants à
  chaque lancement (idempotent) ; `--preparer` fait seulement cela puis quitte.

## Limites connues

- **Signature.** Les paquets ne sont pas signés. Windows SmartScreen affiche un
  avertissement au premier lancement de l'installateur (« Informations
  complémentaires » puis « Exécuter quand même ») ; certains antivirus
  d'entreprise mettent en quarantaine les exécutables PyInstaller non signés :
  faire ajouter le dossier en liste blanche ou signer avec un certificat ULIX
  (ajouter une étape `signtool` dans le job `windows`). Sur macOS, ouvrir le
  `.pkg` par clic droit → Ouvrir, ou `xattr -d com.apple.quarantine`.
- **macOS.** Le paquet est construit pour l'architecture du runner
  (`macos-latest` = Apple Silicon). Pour des Mac Intel, ajouter un job
  `macos-13`.
- **Linux.** Le `.deb` ne livre pas poppler/tesseract : apt les installe.
- **Taille.** 200 à 250 Mo décompressés, dont l'essentiel pour tesseract et poppler.
