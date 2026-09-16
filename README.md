# Génération d'annonces d’arrivée NCTS

Application Python de génération et de contrôle documentaire NCTS.
Voir [le guide de l’application](app_ncts/README.md) et
[l’installation Windows](app_ncts/INSTALLATION-WINDOWS.md).

## Paquets pour les équipes (sans Python ni outils à installer)

Un tag `v1.2.0` poussé sur GitHub déclenche `.github/workflows/construire.yml`,
qui publie une Release avec l'installateur Windows (Python, poppler et
tesseract inclus), le `.pkg` macOS et le `.deb` Linux. Le dossier installé
contient les dépôts prêts à recevoir les fichiers et un `.env` pour la clé IA
(modèle par défaut `deepseek-v4.1-flash:cloud`). Voir
[build/DISTRIBUTION.md](build/DISTRIBUTION.md).

## Configuration locale

Copier `app_ncts/config.example.json` vers `app_ncts/config.json`
pour configurer le poste. Le fichier local est ignoré par Git. Sans ce fichier,
l’application utilise ses paramètres par défaut. Aucun accès CargoWise n’est
préconfiguré dans la version publique.

## Contenu public et privé

Le dépôt contient le code, les scripts de rendu et des tests fictifs. Les
références de test ne représentent pas des déclarations utilisables en douane.
Les documents clients, relectures, sorties, paramètres locaux, secrets et
la documentation interne du plugin sont exclus de Git. Les scripts situés dans
`app_ncts/Documentation/skills/ulix-doc-arrivee-ncts/scripts/` restent nécessaires au rendu.
Les fichiers exclus peuvent être conservés localement pour l’exploitation.

## Vérification

Depuis la racine, avec les dépendances de l’application installées :

```sh
python3 -m unittest discover -s app_ncts/tests
```

Avant chaque publication, vérifier `git diff --cached` : un `.gitignore`
n’empêche pas l’ajout forcé de fichiers ni les secrets écrits dans le code.
