# Hermes — annonces d’arrivée NCTS

Application Python de génération et de contrôle documentaire NCTS.
Voir [le guide de l’application](annonce_arrivee/README.md) et
[l’installation Windows](annonce_arrivee/INSTALLATION-WINDOWS.md).

## Configuration locale

Copier `annonce_arrivee/config.example.json` vers `annonce_arrivee/config.json`
pour configurer le poste. Le fichier local est ignoré par Git. Sans ce fichier,
l’application utilise ses paramètres par défaut. Aucun accès CargoWise n’est
préconfiguré dans la version publique.

## Contenu public et privé

Le dépôt contient le code, les scripts de rendu et des tests fictifs. Les
références de test ne représentent pas des déclarations utilisables en douane.
Les documents clients, relectures, sorties, paramètres locaux, secrets et
la documentation interne du plugin sont exclus de Git. Les scripts situés dans
`Documentation/skills/ulix-doc-arrivee-ncts/scripts/` restent nécessaires au rendu.
Les fichiers exclus peuvent être conservés localement pour l’exploitation.

## Vérification

Depuis la racine, avec les dépendances de l’application installées :

```sh
python3 -m unittest discover -s annonce_arrivee/tests
```

Avant chaque publication, vérifier `git diff --cached` : un `.gitignore`
n’empêche pas l’ajout forcé de fichiers ni les secrets écrits dans le code.
