# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Vue d'ensemble

Application Python (sans framework, stdlib + reportlab/Pillow/python-docx/zxing-cpp) qui
lit des PDF de transit douanier (TAD UE TR1/TR2, TCH suisse OFDF, TAD français, formulaires
CargoWise CW1) et produit l'**annonce d'arrivée NCTS** d'ULIX SWISS SA (Word modifiable par
défaut, ou PDF « annonce + liste d'inventaire » avec cadre CONTRÔLE 3140).

Le code et les commentaires sont en **français** ; garder cette langue (identifiants,
messages, docstrings, rapports).

Deux points d'entrée coexistent :

- `app_ncts/` : l'application locale (ce qu'on développe ici).
- `app_ncts/Documentation/` : plugin Claude Desktop/Cowork (skill `ulix-doc-arrivee-ncts`,
  agent `ncts-generator`) qui exécute le même métier via les connecteurs MCP CargoWise.
  Seul son sous-dossier `skills/ulix-doc-arrivee-ncts/scripts/` est versionné : il contient
  `generate_doc.py`, le **gabarit de rendu PDF** dont dépend l'application.

## Disposition des dossiers (importante)

Le dossier racine du dépôt est le **dossier PROJET métier** ; `app_ncts/` est le dossier
du CODE. Les dossiers de travail (`Dépots unique/`, `Dépots multiple/`,
`Annonces d'arrivées/`, `Archive/`) sont résolus relativement au PROJET, c'est-à-dire au
parent de `lancer.py`, avec tolérance des accents et du NFD macOS (`fsutil.resoudre`).
Ils sont ignorés par Git, comme tout `*.pdf`, `*.docx`, `*.png`, `relectures/`,
`config.json`, `corpus_reference.json` et le reste de `Documentation/`.

## Commandes

Tout se lance depuis `app_ncts/` avec le venv local (`.venv/bin/python3` sur macOS,
`.venv\Scripts\python.exe` sur Windows). `Installer.command` / `Installer.cmd` créent ce venv
et installent reportlab, Pillow, python-docx, zxing-cpp ; poppler (`pdfinfo`, `pdftotext`,
`pdftoppm`) doivent être installés sur le poste. PaddleOCR et ses modèles sont installés via Installer.command.

```bash
cd app_ncts

# Tests (unittest, aucune dépendance réseau ni PDF réel)
.venv/bin/python3 -m unittest discover -s tests
.venv/bin/python3 -m unittest tests.test_qualite                     # un module
.venv/bin/python3 -m unittest tests.test_qualite.Fiabilite.test_valide  # un test

# Traitement
.venv/bin/python3 lancer.py                    # traite les deux dépôts
.venv/bin/python3 lancer.py --simulation       # analyse sans écrire ni archiver
.venv/bin/python3 lancer.py --garder           # ne pas déplacer les PDF dans Archive/
.venv/bin/python3 lancer.py --format pdf       # circuit PDF strict (Word par défaut)
.venv/bin/python3 lancer.py --surveiller       # guetteur : traite chaque lot déposé
.venv/bin/python3 lancer.py --cargowise --nct NCT00000202   # enrichissement MCP
.venv/bin/python3 lancer.py --statut-cargowise --nct NCT…   # diagnostic connexion
.venv/bin/python3 lancer.py --autoriser        # OAuth interactif vers le MCP
.venv/bin/python3 lancer.py --cle-ia CLE       # clé du modèle vision -> ~/.ulix_ncts_ia.json
.venv/bin/python3 lancer.py --statut-ia

# Outils de développement (tools/)
.venv/bin/python3 tools/dump_extract.py fichier.pdf [--pages 1,2]   # en-tête + articles extraits
.venv/bin/python3 tools/dump_pages.py fichier.pdf --pages 2          # cellules positionnelles
.venv/bin/python3 tools/inspect_lines.py fichier.pdf --page 1        # lignes pdftotext -bbox
.venv/bin/python3 tools/debug_ia.py fichier.pdf                      # réponse brute du modèle
.venv/bin/python3 tools/evaluer_corpus.py DOSSIER --reference tests/fixtures/corpus_reference.json
.venv/bin/python3 tools/test_windows.py                              # simule os.name == "nt"
.venv/bin/python3 tools/faux_mcp_oauth.py & .venv/bin/python3 tools/test_oauth.py  # OAuth sans CargoWise
.venv/bin/python3 tools/valider_dossier.py FICHIER_validation.json --operateur "Nom" --confirmer-sources
```

`valider_dossier.py` atteste une relecture humaine : ne jamais l'appeler automatiquement.

## Distribution (paquets Windows / macOS / Linux)

`build/construire.py` produit l'exécutable figé (PyInstaller, mode dossier, spec
`build/ulix_ncts.spec`) puis assemble le dossier « ULIX NCTS » livré aux équipes :
dépôts vides, lanceurs, `.env` initial, `app/` (exécutable + gabarit + `bin/` poppler
et les modèles PaddleOCR). `.github/workflows/construire.yml` l'exécute sur les trois systèmes et
publie une Release sur un tag `v*`. Détails dans `build/DISTRIBUTION.md`.

En mode figé (`plateforme.est_fige()`), le dossier du CODE est celui de l'exécutable,
le gabarit vient de `dossier_ressources()` et `render.generer` relance l'exécutable
avec l'option interne `--rendu-gabarit` (toujours `generate_doc.py`, jamais un autre
rendu). Les binaires livrés dans `app/bin/` priment sur ceux du poste. Le `.env` du
dossier PROJET (`config.charger_env`) alimente l'environnement sans écraser les
variables déjà définies ; `.env.example` à la racine du dépôt en est le modèle public
(clé `OLLAMA_API_KEY`, modèle `ULIX_IA_MODELE=deepseek-v4.1-flash:cloud`).

Les scripts `Lancer.command`/`Surveiller.command` (macOS) et `.cmd` (Windows) ne font
qu'appeler `lancer.py` avec le venv.

## Architecture du pipeline (`app_ncts/ulix_ncts/`)

Chaîne « cheap-first » : déterministe d'abord, IA seulement en repli, jamais bloquante.

1. **`surveillance`** (mode `--surveiller`) attend qu'un lot soit stable : taille/mtime
   figés `stabilite_s` secondes, marqueur `%%EOF` présent, fichiers temporaires ignorés.
   En dépôt multiple, un seul fichier incomplet bloque tout le lot.
2. **`pipeline.executer`** : dépôt unique = 1 PDF -> 1 annonce ; dépôt multiple =
   N PDF -> 1 annonce. Pour chaque PDF, `analyser_pdf` :
   - `classer_pages` : `classify.classer` sur la couche texte (`pdfio.couche_texte`),
     puis OCR du **bandeau haut seulement** si la page est scannée ou indéterminée.
     Familles : `TRANSIT_TAD`, `TRANSIT_TCH`, `TRANSIT_FR`, `TRANSIT_LISTE`, `ANNONCE_CW*`
     (retenues) ; `EXPORT` (piège n°1, EX1/EAD), `ANNEXE`, `ENVELOPPE` (écartées mais
     exploitées en triangulation).
   - `relecture.charger` : si un JSON existe dans `relectures/<sha256>.json`, il remplace
     l'extraction (lié au contenu exact du PDF, pas au nom).
   - `qualite.codes_mrn` : décodage optique des codes-barres (zxing-cpp) pour corroborer
     le MRN.
   - `extract.*` : un extracteur par famille (`extraire_tad_entete`, `extraire_liste_std`,
     `extraire_tch`, `extraire_tad_fr`, `extraire_cw1`, `extraire_waybill_dhl`). Lecture
     **positionnelle** via `pdftotext -bbox` (mots -> lignes -> cellules), pas de regex
     sur texte plat pour les TAD. Un TCH n'a pas de désignation : elle vient du waybill
     DHL du même dépôt, apparié par chiffres partagés (`_waybill_pour`).
   - `_appliquer_cw` : enrichissement CargoWise (DM/LRN, date, statut) **après**
     résolution du MRN, sinon on mélange des déclarations.
   - `ia.completer_dossier` : repli vision (endpoint OpenAI-compatible, Ollama par défaut)
     uniquement si un seul dossier et `_lacunaire`. Budget `ia.max_pages`, fusion
     multipage exigeant référence commune + pagination complète.
3. **`qualite.evaluer`** décide la livraison indépendamment du succès de rendu : MRN bien
   formé et corroboré, DM présent, parties, articles complets, net ≤ brut, sommes
   concordantes (tolérance 0,05 kg), pas de blocage. Une confiance IA ne vaut jamais
   validation. Non conforme -> `A_verifier/` avec fiche HTML + `*_validation.json` ;
   conforme -> `Prets_a_remettre/`. Rapports et `data.json` vont dans `data/`.
4. **Rendu** : `render.dossiers_vers_data` traduit les `Dossier` vers le schéma JSON du
   gabarit, puis `render.generer` invoque `generate_doc.py` en sous-processus
   (`render.trouver_gabarit` le cherche depuis l'application ou la racine). `word.generer`
   produit le `.docx` éditable (codes-barres en image, première page seulement, sans notes
   internes). **Interdit** : tout rendu PDF improvisé hors de ce gabarit.
5. `_archiver` déplace les sources dans `Archive/` seulement après génération réussie
   (jamais en `--simulation`/`--garder`, jamais pour un lot bloqué).

Modules transverses : `config` (défauts < `config.json` < variables `ULIX_*`/`CW_*`),
`pdfio` (point de passage unique vers poppler/PaddleOCR, rendu `pdftoppm -singlefile`),
`plateforme` (binaires hors PATH sous Windows, venv, console UTF-8/ANSI, `PYTHONUTF8`
pour le sous-processus de rendu), `cw_client` + `oauth` (MCP HTTP streamable, PKCE,
jetons dans `~/.ulix_ncts*.json` en droits 600), `fsutil` (résolution tolérante des noms).

## Garde-fous métier à préserver

- **Aucune marchandise inventée** : champ non lu = `extract.A_VERIFIER` (« à vérifier »,
  rendu « à compléter » dans Word), signalé dans le rapport.
- Le MRN n'est jamais remplacé automatiquement par un numéro d'annonce, ni l'inverse ;
  une correction OCR n'est acceptée que si code-barres et nom de fichier concordent, avec
  trace dans `avertissements`.
- Un TCH avec plusieurs waybills ne reçoit pas la désignation d'un seul envoi ; le repli
  IA ne contourne pas ce garde-fou.
- Les notes de contrôle, écarts et provenance restent dans le rapport, la fiche interne et
  le JSON : **jamais sur le document remis au client**. Codes-barres uniquement sur la
  première page.
- Toute erreur CargoWise ou IA est consignée et le traitement continue sur les seuls PDF.
- Aucun secret dans le dépôt : clés IA et jetons OAuth vivent dans `~/.ulix_ncts*.json` ;
  `config.json` local est ignoré par Git (`config.example.json` est la version publique).

## Tests

`tests/` (unittest, 59 tests, ~4 s) : tout est hors ligne et fictif, les appels externes
sont patchés (`unittest.mock.patch`). Les MRN de test suivent le motif `26CH07STTEST…`.
`test_regressions.py` couvre les cas métier (gabarit, TCH multi-waybills, MRN, archivage),
`test_qualite.py` la décision de livraison et la fusion IA multipage, `test_word.py` le
contrat du `.docx`, `test_annonce_originale.py` la reprise du code-barres GTAN. Les
scripts `tools/test_*.py` ne sont pas des tests unittest mais des vérifications manuelles.
