## Sortie Word modifiable (par défaut)

La surveillance produit désormais un `.docx` dans `Annonces d'arrivées`.
Les champs et tableaux se modifient directement dans Word. Les codes-barres sont limités à
la première page ; les notes internes restent dans le rapport et le JSON du dossier `data`.
Les valeurs absentes portent la mention « à compléter ». La génération Word ne constitue
pas une validation des données. Après une génération Word réussie, les PDF sources sont
déplacés dans `Archive`, sauf avec `--garder` ou en simulation. En cas d’échec, ils restent
dans le dépôt.

Après mise à jour, arrêter la surveillance avec Ctrl+C puis relancer `./Surveiller.command`.
Sur une autre machine, relancer l'installateur pour installer `python-docx`.
Pour conserver le circuit PDF avec validation stricte : `./Surveiller.command --format pdf`.

Après une modification dans Word, mettre aussi à jour les champs répétés et les totaux.
Les images des codes-barres ne suivent pas une modification manuelle du MRN : régénérer
le document si ce numéro change. Exporter le PDF final depuis Word ; les modifications
Word ne sont pas réimportées dans les données JSON de l'application.

# Annonce d'arrivée NCTS — génération automatique

Script qui scanne les PDF déposés, lit les documents de transit (TR1/TR2/TCH,
TAD UE, formulaires CargoWise) et génère le **document d'arrivée NCTS** : PDF
2 pages au minimum, page 1 « Annonce d'arrivée », page 2 « Liste d'inventaire » avec le
cadre CONTRÔLE ULIX SWISS SA (n° 3140).

```
Dépots unique   →  1 fichier PDF   →  1 annonce d'arrivée
Dépots multiple →  N fichiers PDF  →  1 seule annonce d'arrivée
```

## Annonce originale et relectures

Lorsqu'un PDF contient une « Annonce arrivée », le programme reprend son code-barres
GTAN décodé, en conservant la casse. Les MRN restent dans les tableaux ; trois transits
ne donnent donc pas trois codes-barres d'annonce. Sans annonce originale, les documents
de transit conservent leurs codes-barres MRN. Un numéro d'annonce illisible n'est jamais
remplacé automatiquement par un MRN.

Une relecture documentaire peut être enregistrée dans `annonce_arrivee/relectures`,
sous l'empreinte SHA-256 du PDF. Elle ne s'applique qu'au contenu exact relu, même si
le nom du fichier change. Un autre PDF portant le même nom ne reçoit pas ces données.
Les relectures conservent leurs preuves, les champs absents et leur méthode ; elles
ne constituent pas une validation douanière. Les relectures réelles sont privées
et exclues de Git. Les tests publiés utilisent des données fictives.


## Utilisation

1. **Première fois sur un poste** : double-cliquer **`Installer.command`**
   (crée l'environnement Python local et installe reportlab + Pillow ; installe
   aussi poppler et tesseract via Homebrew si besoin).
2. **À chaque traitement** : déposer les PDF dans `Dépots unique/` et/ou
   `Dépots multiple/`, puis double-cliquer **`Lancer.command`**.
3. Les annonces sont écrites dans **`Annonces d'arrivées/`** ; les PDF traités
   sont déplacés dans **`Archive/`** (aucun doublon, pas de retraitement).

En ligne de commande (équivalent, avec options) :

```bash
cd annonce_arrivee
.venv/bin/python3 lancer.py                 # traite les deux dépôts
.venv/bin/python3 lancer.py --unique        # seulement « Dépots unique »
.venv/bin/python3 lancer.py --multiple      # seulement « Dépots multiple »
.venv/bin/python3 lancer.py --simulation    # analyse sans rien écrire
.venv/bin/python3 lancer.py --garder        # ne pas archiver les PDF traités
.venv/bin/python3 lancer.py --cargowise     # enrichir via le serveur MCP CargoWise
```

Sortie par annonce : le PDF (`Annonce_et_Inventaire_<clé>.pdf`), le `data.json`
ayant servi au rendu (traçabilité), et un `Rapport_<horodatage>.txt` listant
pour chaque fichier les pages retenues, les pages écartées, la confiance et les
écarts détectés.

## Ce que le script sait lire

| Document | Traitement |
|---|---|
| TAD UE (TR1/TR2, « ELENCO DEGLI ARTICOLI ») | 1 article par page de liste : désignation, code NC, masses, colis, document précédent, justificatifs |
| Déclaration de transit national OFDF (GDRN, CH) | GDRN, référence, colisage, masse brute, parties, bureau de destination. Le formulaire ne porte **pas** de désignation : elle est reprise du waybill DHL du dépôt (source tracée sur le document) |
| TAD français « TRANSIT – DOCUMENT D'ACCOMPAGNEMENT » | cases 31/32/33/35/38/40/50/53 |
| Formulaire CargoWise « Annonce arrivée » + inventaire + listes | un dossier par MRN listé (utilisé pour le DM et la référence) |

Les pièces hors sujet sont **écartées du document** : waybills DHL, factures
proforma, e-mails de demande de dédouanement, déclarations d'export EX1/EAD
(le piège n°1 du process), pages de garde DHL. Elles restent exploitées comme
source de triangulation quand c'est utile, et figurent au rapport.

## Garde-fous

- **Aucune marchandise inventée** : un champ non lu est marqué « à vérifier » et
  signalé dans le rapport, jamais estimé.
- **MRN recoupé** : la couche texte des scans est dégradée (l/1, O/0, S/5). Le
  MRN lu est rapproché de celui du nom de fichier déposé, et la correction est
  tracée dans le rapport.
- **Contrôle croisé** du colisage et des masses entre le document de transit, le
  total déclaré et le waybill ; les divergences sont conservées dans le rapport interne et le JSON,
  sans apparaître sur le document final.
- **Cases du cadre CONTRÔLE jamais cochées** par l'outil.
- **Rendu figé** : le PDF est produit exclusivement par le script déterministe
  du skill ULIX (`Documentation/skills/ulix-doc-arrivee-ncts/scripts/generate_doc.py`) —
  fond blanc, accents, code-barres Code 128 du MRN, cadre 3140. Aucun rendu
  improvisé, aucune charte graphique.

## Configuration (facultative)

Un `config.json` à côté de ce fichier (ou `~/.ulix_ncts.json`) peut surcharger
les réglages ; les variables d'environnement `ULIX_*` ont la priorité :

```json
{
  "dossiers": { "depot_unique": "Dépots unique", "depot_multiple": "Dépots multiple",
                "sortie": "Annonces d'arrivées", "archive": "Archive" },
  "traitement": { "deplacer_traite": true, "dpi_ocr": 200 },
  "cargowise": { "active": false, "url": "http://localhost:8000/mcp", "token": "" }
}
```

La résolution des dossiers tolère les accents et les formes Unicode macOS :
« Dépots unique » et « Dépôts unique » désignent le même dossier.

## Deux façons d'utiliser l'outil

L'outil fonctionne sur **macOS et Windows** à l'identique. Les lanceurs existent
en deux versions dans le dossier (`*.command` pour macOS, `*.cmd` pour Windows) :
utiliser ceux de son système. Sur Windows, voir **`INSTALLATION-WINDOWS.md`**.

### 1. Surveillance automatique (recommandé pour les utilisateurs)

Double-cliquer **`Surveiller.command`** (macOS) ou **`Surveiller.cmd`**
(Windows), puis laisser la fenêtre ouverte. Le programme surveille les deux
dépôts : dès qu'un PDF y est déposé, il est traité et l'annonce apparaît dans
« Annonces d'arrivées ». **L'utilisateur n'a rien d'autre à faire que déposer ses
fichiers.**

```bash
.venv/bin/python3 lancer.py --surveiller            # guetteur permanent
.venv/bin/python3 lancer.py --surveiller --une-fois # traiter le lot présent puis quitter
```

Le guetteur attend qu'un dépôt soit **réellement terminé** avant de traiter :
copie de fichier non atomique, PDF tronqué sans marqueur de fin `%%EOF`, fichiers
temporaires du Finder ou du navigateur (`.part`, `.crdownload`, `~~$…`) sont
écartés. Un lot déposé en une seule fois (3 fichiers d'un coup) est traité comme
un tout : en dépôt multiple ils forment bien une seule annonce. Un lot en échec
ne fait jamais tomber la surveillance.

### 2. Traitement à la demande

Double-cliquer **`Lancer.command`** (macOS) ou **`Lancer.cmd`** (Windows), ou :

```bash
cd hermes/annonce_arrivee
.venv/bin/python3 lancer.py               # les deux dépôts
.venv/bin/python3 lancer.py --unique      # seulement « Dépots unique »
.venv/bin/python3 lancer.py --multiple    # seulement « Dépots multiple »
.venv/bin/python3 lancer.py --simulation  # analyser sans rien écrire
```

| Règle | Dépôt | Résultat |
|---|---|---|
| **Dépôt unique** | 1 fichier PDF | 1 annonce d'arrivée |
| **Dépôt multiple** | plusieurs PDF | **une seule** annonce regroupant tous les MRN et tous les articles |

Après génération et validation réussies, les sources partent dans `hermes/Archive/`.
Les échecs restent dans le dépôt. Aucun mécanisme ne déduplique une nouvelle copie
d’un fichier déjà traité ; un MRN répété dans un même lot est refusé pour éviter
le double comptage.

### Ce que contient chaque dossier

```
hermes/
├── Dépots unique/          ← vous déposez ici (1 fichier = 1 annonce)
├── Dépots multiple/        ← vous déposez ici (N fichiers = 1 annonce)
├── Annonces d'arrivées/    ← UNIQUEMENT les PDF à remettre au client
│   └── data/               ← fichiers de travail : les .json et le rapport
└── Archive/                ← les PDF de dépôt, une fois traités
```

Le dossier « Annonces d'arrivées » ne contient que les PDF : les fichiers
d'échange `.json` et le rapport texte sont rangés dans son sous-dossier `data/`,
pour ne pas polluer la liste des annonces. Ce sous-dossier est créé
automatiquement et reprend les mêmes noms que les PDF, pour retrouver la source
d'une annonce d'un coup d'œil.

## Repli IA (lecture des pages en échec)

L'extraction est **déterministe par défaut** : `pdftotext` puis `tesseract`
(gratuit, hors ligne, reproductible). C'est ce qui traite l'essentiel des
documents — l'OCR ne pèse que ~11 % du temps de traitement sur les 11 PDF de
référence.

Un **repli IA** (vision) prend le relais **uniquement** sur les dossiers que le
déterministe n'a pas su renseigner — typiquement :

- les SAD scannés dont la couche texte confond lettres et chiffres (l/1, S/5, O/0) ;
- les TCH suisses sans waybill, où la seule désignation est une **facture
  proforma** dont le tableau est illisible pour l'OCR classique.

Le repli est déclenché par les champs manquants, indépendamment de la confiance
globale. Il est suspendu lorsqu’un PDF contient plusieurs déclarations, faute
d’association certaine des annexes. Les pages EXPORT sont exclues.
Le modèle lit l’image de la page et rend désignations, code marchandise, masses
et colis. La provenance est conservée dans le rapport interne et le JSON.
Aucune note IA ou de provenance n’est imprimée sur le document final.

```bash
.venv/bin/python3 lancer.py --statut-ia          # l'accès au modèle répond-il ?
.venv/bin/python3 lancer.py --cle-ia VOTRE_CLE   # enregistrer la clé sur ce poste
.venv/bin/python3 tools/debug_ia.py <pdf>        # ce que le modèle voit et rend
```

### La clé, et l'indépendance vis-à-vis d'Hermes

**L'outil ne dépend d'aucun autre logiciel** : ni de l'agent Hermes, ni d'un
démon Ollama local. Il parle directement à l'API d'Ollama Cloud
(`https://ollama.com/v1`).

La clé est stockée dans un **fichier privé du poste**, `~/.ulix_ncts_ia.json`,
en droits **600** (lisible par vous seul) :

```bash
.venv/bin/python3 lancer.py --cle-ia a1f4…      # écrit le fichier en 600
```

Ce fichier est **hors du dossier du projet** : copier le dossier chez un autre
utilisateur ne diffuse donc jamais la clé. Elle n'apparaît ni dans `config.json`,
ni dans un rapport, ni dans un message — les diagnostics n'en montrent que la
présence et la provenance.

Ordre de résolution (le premier trouvé gagne) :

| Priorité | Source | Usage |
|---|---|---|
| 1 | `OLLAMA_API_KEY` (environnement) | déploiement automatisé, sans fichier |
| 2 | `~/.ulix_ncts_ia.json` (600) | usage normal sur un poste |
| 3 | `config.json` → `ia.api_key` | dernier recours, **déconseillé** (fichier copiable) |

L'endpoint distant est refusé s'il n'est pas en `https://` : la clé passerait en
clair sur le réseau.

Réglages dans `config.json`, section `ia` :

| Clé | Rôle |
|---|---|
| `active` | `true` = autoriser le repli IA (défaut : `true`) |
| `base_url` / `modele` | vides = valeurs du fichier privé, à défaut Ollama Cloud |
| `max_pages` | pages relues au maximum par dossier (défaut 3) |
| `max_tokens` | budget de réponse : un modèle raisonneur consomme du budget avant de répondre |
| `dpi` | résolution du rendu soumis au modèle (défaut 150) |

Un échec de l’IA conserve les données déterministes ; le document préparé reste
dans `A_verifier/`. L’incident est consigné au rapport interne.

### Mise en place chez un utilisateur

1. Copier le dossier `annonce_arrivee` et le dossier `Documentation` à côté des
   dépôts (l'arborescence attendue : voir plus bas).
2. Double-cliquer **`Installer.command`** une fois : il installe poppler,
   tesseract et l'environnement Python local (aucun droit administrateur).
3. Enregistrer la clé IA : `lancer.py --cle-ia VOTRE_CLE` (en Terminal, ou en
   passant la variable `OLLAMA_API_KEY`).
4. Double-cliquer **`Surveiller.command`** et laisser la fenêtre ouverte.

Sans clé, le repli IA reste simplement inactif : tout le reste fonctionne, et
`--statut-ia` indique quoi faire.

## CargoWise via MCP

Configurer l'URL de votre serveur dans `config.json` ou `CW_MCP_URL`, puis
réaliser l'autorisation OAuth sur chaque poste. Le jeton est enregistré dans
`~/.ulix_ncts_tokens.json` (droits 600), hors du dépôt. Les clés NCT ci-dessous
sont fictives : les remplacer par une clé autorisée sur votre instance.

```bash
.venv/bin/python3 lancer.py --statut-cargowise --cle-cargowise NCT99000001  # vérifier l'accès
.venv/bin/python3 lancer.py --nct NCT99000001        # enrichir avec une déclaration
.venv/bin/python3 lancer.py --autoriser              # (re)faire l'autorisation OAuth
.venv/bin/python3 lancer.py --autoriser --nouveau-client   # si le port du client est occupé
```

### Limite à connaître : la clé `NCT…` n'est pas dans les PDF

`cargowise_get_ncts` n'accepte **que** la clé de déclaration `NCT` + 8 chiffres.
Vérifié sur le serveur : un MRN, un DM/LRN ou un n° de dossier renvoient
« no business object matching the criteria ». Or les PDF déposés portent un MRN,
un DM ou un GDRN — jamais la clé NCT.

Conséquence : **pour que l'enrichissement CargoWise s'applique, il faut fournir
la clé** :

```
.venv/bin/python3 lancer.py --nct NCT99000002
```

Elle peut aussi figurer dans le nom du fichier déposé
(`NCT99000002 - DM PMP 20990101.pdf` → clé détectée automatiquement).

Sans clé, le traitement continue normalement : le document est produit à partir
des seuls PDF, et le rapport l'indique explicitement.

### Garde-fou de cohérence

L’en-tête CargoWise n’est appliqué **que** si le MRN renvoyé par le serveur
correspond exactement à celui du document. Un MRN absent ou seulement ressemblant
ne suffit pas ; une différence avec le nom de fichier est signalée sans écrasement. Passer une clé `--nct` valide pour un autre
dossier ne mélange donc jamais deux déclarations : le rapport signale l'absence
de correspondance et le document sort avec les données du PDF.

### Champs récupérés

Selon les outils exposés par le serveur : MRN, statuts, type de mouvement,
date d'arrivée, référence LRN et bureau de destination. Le serveur peut aussi
exposer les eDocs et le contexte d'expédition.

**Noms de paramètres** : ils peuvent varier selon les outils.
`cargowise_get_ncts` attend `declarationKey`, mais `cargowise_get_document` et
`cargowise_list_documents` attendent `shipmentKey` / `documentType`, et
`cargowise_get_shipment_summary` / `_track_shipment` attendent
`shipmentNumber`. Le client les découvre dans `tools/list`, jamais en dur.

### OAuth

Les métadonnées OAuth sont découvertes auprès du serveur configuré. Selon ses
capacités, le client utilise PKCE et l'enregistrement dynamique. Si aucun jeton
de renouvellement n'est émis, relancer `--autoriser` après expiration.

### Autre serveur MCP

L'URL se surcharge par `CW_MCP_URL` (ou `cargowise.url`) : aucun autre réglage
n'est nécessaire, la découverte OAuth est automatique.

`tools/faux_mcp_oauth.py` démarre un serveur MCP de test protégé par OAuth
(découverte, enregistrement dynamique, PKCE, rafraîchissement) et
`tools/test_oauth.py` rejoue la chaîne complète :

```bash
.venv/bin/python3 tools/faux_mcp_oauth.py 8765 &
.venv/bin/python3 tools/test_oauth.py 8765
```

## Structure

```
annonce_arrivee/
├── Lancer.command          lancement en double-clic
├── Installer.command       installation (une fois par poste)
├── lancer.py               point d'entrée et options
├── ulix_ncts/
│   ├── config.py           configuration et résolution des dossiers
│   ├── fsutil.py           chemins macOS (NFD, accents)
│   ├── pdfio.py            lecture PDF, rendus, OCR
│   ├── classify.py         classification des pages (transit / export / annexe)
│   ├── extract.py          extraction par famille de formulaire
│   ├── oauth.py            OAuth 2.1 (découverte, PKCE, DCR, jetons)
│   ├── cw_client.py        client MCP CargoWise (optionnel)
│   ├── render.py           écriture du data.json + appel du gabarit ULIX
│   └── pipeline.py         orchestration dépôt unique / multiple
└── tools/                  diagnostics ; faux serveur MCP + test OAuth
```

Le rendu final est un PDF à mise en page fixe : le script ne fait que préparer
les données et appeler le gabarit du skill, jamais de rendu ad hoc.

## Prérequis

- Python 3.11 ou plus récent (installé pour vous par `Installer.command`).
- `poppler` et `tesseract` (`brew install poppler tesseract`) pour la lecture
  des scans.
- Accès en lecture/écriture aux dossiers `Dépots unique`, `Dépots multiple`,
  `Annonces d'arrivées` et `Archive`.

---
V1.0 — ULIX SWISS SA — génération locale, aucune donnée n'est saisie ni modifiée
dans CargoWise (lecture seule).


## Fiabilisation et limites opérationnelles — 16 septembre 2026

- L’archivage dépend d’un rendu réussi et de contrôles automatiques (texte attendu,
  DM ou mention « à vérifier », dernière page avec cadre contrôle, limites de page).
  Un rendu rejeté est isolé sous `Annonces d’arrivées/A_verifier/`.
- Un dépôt multiple est indivisible : chaque PDF doit fournir un transit reconnu.
  Les annexes seules dans un fichier distinct ne sont pas automatiquement rattachées ;
  les joindre au PDF du transit concerné. Un fichier incomplet ou temporaire présent
  dans le dépôt multiple bloque son traitement. Une pause entre deux fichiers qui
  ne sont pas encore apparus reste indétectable : préparer le lot hors du dépôt,
  puis le déposer ensemble. Ne pas mélanger deux opérations dans ce dépôt.
- Les échecs et les fichiers conservés (`--garder`, simulation) ne sont pas relancés
  en boucle pendant la même session de surveillance. Modifier le fichier ou
  redémarrer la surveillance permet un nouvel essai.
- Le PDF final ne contient ni notes de contrôle, ni écarts, ni provenance technique
  ou documentaire : ces informations restent dans le rapport interne et le JSON.
  Les champs manquants gardent leur mention « à vérifier ».
  Les codes-barres figurent uniquement sur la première page physique. L’inventaire
  et les pages de continuation n’en portent pas. Le cadre CONTRÔLE reste sur la
  dernière page. Les en-têtes longs peuvent nécessiter des pages supplémentaires.
- Maximum 10 déclarations par annonce. Une description individuelle trop longue
  pour le gabarit entraîne un échec explicite, sans archivage. Scinder le lot ou
  revoir la description dans ce cas. Ne pas démarrer deux surveillances sur les
  mêmes dépôts simultanément.
- Les totaux ne sont calculés que si toutes les valeurs correspondantes sont
  connues. Les adresses provenant de l’IA utilisent le même schéma que le rendu.
- Une nouvelle annonce portant un MRN déjà présent en sortie reçoit un suffixe
  temporel ; l’ancien PDF n’est pas écrasé.
- Les contrôles automatiques ne remplacent pas la vérification humaine du contenu,
  des unités de masse et de la lisibilité des codes-barres au scanner.
- Avec une clé IA configurée, les images sélectionnées sont envoyées au service
  distant configuré (Ollama Cloud par défaut). Le fonctionnement n’est donc pas
  entièrement local. Mettre `ia.active` à `false` pour interdire ces appels.

### Tests de non-régression hors ligne

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Sous Windows : `.venv\Scripts\python.exe -m unittest discover -s tests -v`.
Les tests de rendu requièrent reportlab, Pillow et Poppler. Aucun appel CargoWise
ou IA n’est effectué. `tools/test_windows.py` reste un diagnostic du poste courant ;
un passage sur macOS ne valide pas une installation Windows réelle.


## Contrôle avant livraison — mode strict

Une génération PDF réussie n’est plus une autorisation de livraison.

```
Annonces d'arrivées/
├── Prets_a_remettre/  # seulement les dossiers ayant passé les contrôles
├── A_verifier/        # PDF préparés, fiches HTML internes et formulaires JSON
└── data/             # rapports et traces de traitement/validation
```

Les sources d’un dossier à vérifier restent dans le dépôt. Dans un lot multiple,
un seul dossier bloqué bloque la livraison et l’archivage du lot entier.
Les PDF clients restent sans notes de contrôle/provenance et avec les codes-barres
sur la première page seulement.

### Contrôles obligatoires

- MRN formé correctement, corroboré par lecture optique du code-barres ou par
  CargoWise avec correspondance exacte. Si le code-barres et le nom concordent,
  une erreur OCR peut être rectifiée, avec trace interne.
- DM/LRN renseigné, parties présentes, articles avec désignation, code marchandise,
  masses brute et nette positives, colisage interprétable ; net ≤ brut.
- Totaux connus et sommes des articles concordantes (tolérance brute : 0,05 kg).
  Un colisage partagé entre plusieurs articles nécessite une revue humaine.
- Aucun écart ou association ambiguë non résolu. Une lecture IA n'est jamais
  automatiquement certifiée par sa propre confiance.
- Traçabilité conservée : pages candidates du déterministe, valeurs originales,
  codes-barres lus, réponses IA avec fichier/page et champs, données CargoWise.
  Les pages candidates ne sont pas une localisation exacte garantie de chaque champ.

Le décodeur optique `zxing-cpp` est installé par les installateurs. S’il manque,
le traitement continue, mais aucun MRN n’est considéré vérifié sur cette base.

### Factures multipages et repli IA

Toutes les pages candidates sont lues jusqu’au budget `ia.max_pages` (défaut 12).
Le dépassement du budget est signalé comme une lecture incomplète. Les pages
EXPORT et ENVELOPPE sont exclues. Une page riche n’interrompt plus la lecture.
La fusion exige une référence de document commune, une pagination imprimée
complète, sans doublon, et une référence d’envoi rapprochée de la déclaration
(ou le même MRN). Plusieurs factures différentes ne sont pas fusionnées sans revue.
Les réponses sans référence ou pagination restent disponibles dans la fiche
interne, mais ne remplacent pas les données déterministes. Les copies d’image
strictement identiques sont ignorées ; les duplications non identiques ne sont
pas supposées équivalentes. Les résultats IA demandent toujours un contrôle humain.

### Vérification humaine et correction

1. Ouvrir la fiche `*_controle.html` dans `A_verifier/` : motifs, valeurs et pages
   sources y sont présentés ensemble.
2. Corriger les champs dans le fichier `*_validation.json` lié à la fiche après
   comparaison avec les documents et CargoWise pour le DM. Ne pas modifier les
   chemins ni les empreintes des sources.
3. Le vérificateur exécute explicitement :

```bash
.venv/bin/python tools/valider_dossier.py "CHEMIN_DU_FICHIER_validation.json" --operateur "Prénom Nom" --confirmer-sources
```

Cette commande atteste une relecture humaine complète des sources et des valeurs.
Elle vérifie leurs empreintes SHA-256 et les règles de complétude/sommes, puis
produit une nouvelle annonce dans `Prets_a_remettre/` avec une trace nominative
et datée dans `data/`. Elle ne contacte aucune API, ne modifie pas les sources et
ne les archive pas : retirer le lot vérifié du dépôt avant une autre opération.
Aucun outil ne peut prouver qu’un humain a réellement relu les documents :
l’attestation relève de la procédure de l’équipe.

### Mesurer l’extraction sur un corpus

```bash
.venv/bin/python tools/evaluer_corpus.py "DOSSIER_DES_TRANSITS_SOURCES"
```

Le fichier public `tests/fixtures/corpus_example.json` décrit un cas fictif ;
son PDF n'est pas fourni. Pour mesurer l'extraction réelle, fournir un corpus
privé avec `--reference tests/fixtures/corpus_reference.json` et ses PDF relus.
Ce fichier privé est exclu de Git. L'évaluation rapporte les champs concordants,
les écarts et les sources absentes, sans appels IA/CargoWise ni déplacement.
Un cas absent n’est jamais compté comme réussi. Les tests synthétiques de code
ne constituent pas une mesure de précision OCR en production.

## Correctifs du lot du 16 septembre 2026

Le rendu des pages utilise un nom exact (`pdftoppm -singlefile`) : le passage entre
PDF courts et longs ne peut plus sélectionner une ancienne image suffixée `-1` ou
`-01`. La lecture GDRN accepte les espaces internes et certains libellés OCR. Les
listes françaises lisent les codes à six chiffres et séparent les références EXPO
et N380 des désignations, en conservant les décimales des masses.

Un TCH avec plusieurs waybills ne reçoit plus la description d'un seul envoi pour
l'ensemble du poids déclaré. Le repli IA ne contourne pas ce garde-fou. Les relectures privées sont liées à l'empreinte de leurs PDF sources. Cela
ne garantit pas l'exactitude de nouveaux scans ni celle des données sources.
