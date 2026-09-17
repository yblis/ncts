# Attribution des numéros DM

Le fonctionnement est préparé, mais désactivé par défaut. Aucun numéro réel n’a été réservé. Le dernier numéro Sisa communiqué, **20260874**, est un repère provisoire : ne pas l’utiliser pour activer le compteur avant confirmation de la bascule.

## Règles confirmées par Raymond

- Un compteur unique pour toute la société, commun aux lieux agréés et aux marchandises Philip Morris.
- Format `AAAANNNN`, remise à zéro annuelle ; première attribution de l’année `AAAA0001` (heure Europe/Zurich).
- Ajout manuel de `PMP ` : `PMP AAAANNNN`. Ce préfixe ne crée pas une autre séquence.
- Le DM appartient à l’annonce, même après réimpression. Aucune fonction d’annulation, suppression ou recyclage n’est exposée.
- Les DM existants dans CargoWise ont été attribués par Sisa.

## Registre central

Un seul service reçoit les demandes de tous les postes par HTTP local ou HTTPS. Il garde sa base SQLite sur **son disque local**, jamais sur un partage SMB/NFS, OneDrive ou Dropbox. Les postes utilisent tous la même URL et ne copient jamais la base pour poursuivre en autonomie.

La réservation et le journal sont écrits dans une même transaction. Une annonce est identifiée par l’ensemble de ses MRN, indépendamment de l’ordre et des noms de fichiers. Un lot multiple reçoit un seul DM. Un MRN déjà attribué ne peut pas être regroupé autrement automatiquement : il faut reprendre le lot original. Ce fonctionnement suppose qu’un même MRN identifie le même transit à réception ; les cas de réception fractionnée nécessitent un traitement métier distinct.

Un échec de rendu, une coupure réseau après réservation ou un redépôt réutilise le numéro déjà réservé. Le numéro reste réservé même si le Word n’a pas été produit. Un changement des marchandises ne crée pas de nouveau DM tant que les MRN restent identiques.

Un DM historique présent dans une source peut être repris s’il ne dépasse pas le dernier Sisa de bascule et n’appartient pas déjà à une autre annonce. Une contradiction avec le registre arrête la production. Le préfixe choisi manuellement dans le registre prime lors des réimpressions.

L’attribution exige des MRN corroborés et aucun blocage d’analyse. Elle ne vaut ni validation des marchandises, ni annonce transmise aux douanes. La transmission du DM à CargoWise reste à raccorder ; ce changement prépare le registre et l’intègre aux documents locaux.

## Préparer le serveur

Depuis `app_ncts`, avec le venv installé, créer un secret dans le `.env` privé du serveur (ne pas le versionner) :

```dotenv
ULIX_DM_TOKEN=REMPLACER_PAR_UN_SECRET_ALEATOIRE_DE_32_CARACTERES_MINIMUM
```

Un secret peut être généré avec `.venv/bin/python -c "import secrets; print(secrets.token_urlsafe(32))"`.

Démarrer le service avec un chemin explicite, conservé d’un lancement à l’autre :

```sh
.venv/bin/python lancer.py --serveur-dm --registre-dm /CHEMIN/SERVEUR/registre-dm.sqlite3
```

Il écoute sur `127.0.0.1:8766`, reste **en préparation**, et refuse les nouvelles attributions tant que la bascule n’a pas eu lieu. Pour plusieurs postes, héberger ce processus sur un serveur permanent et placer un reverse proxy HTTPS devant lui. Le déploiement permanent et l’URL partagée restent à établir ; aucune infrastructure externe n’est déployée automatiquement.

Sauvegarder la base avec le service arrêté (ou avec l’API SQLite de sauvegarde). Conserver le journal, protéger les sauvegardes et ne pas restaurer une version ancienne en production sans rapprochement des numéros émis depuis.

## Configurer les postes

Dans leur `.env` privé :

```dotenv
ULIX_DM_ACTIVE=true
ULIX_DM_URL=https://VOTRE_SERVEUR_DM
ULIX_DM_TOKEN=LE_MEME_SECRET_QUE_LE_SERVEUR
ULIX_DM_OPERATEUR=Nom de l’operateur
```

Pour une recette entièrement locale, utiliser `http://127.0.0.1:8766`. Chaque opérateur utilise son nom pour la traçabilité ; le secret partagé authentifie l’accès au service, pas l’identité individuelle de la personne.

```sh
.venv/bin/python lancer.py --statut-dm
```

Si `ULIX_DM_ACTIVE` reste absent ou faux, le programme conserve son comportement précédent (DM repris des sources, champ manquant signalé). Lorsqu’il est vrai, une indisponibilité du service ou un conflit bloque la génération et l’archivage du lot concerné. `--simulation` consulte une éventuelle attribution existante, sans réserver de nouveau numéro.

## Jour de la bascule

1. Arrêter l’attribution de nouveaux DM dans Sisa et obtenir de Raymond son **dernier numéro définitif**.
2. Sur le serveur uniquement, activer la base centrale avec ce numéro et le nom de l’opérateur :

```sh
.venv/bin/python lancer.py --activer-dm DERNIER_NUMERO_SISA_CONFIRME --registre-dm /CHEMIN/SERVEUR/registre-dm.sqlite3 --operateur-dm "Nom de l’operateur"
```

3. Vérifier `--statut-dm`, puis démarrer la surveillance sur les postes configurés.

L’activation est possible une seule fois. Le premier nouveau DM est le suivant du dernier Sisa ; les années suivantes commencent à 0001 automatiquement. Le dépassement de 9999 bloque l’attribution. Une recette utilise une base et une URL séparées, jamais la future base de production.

## Ajouter ou retirer PMP manuellement

Après la première attribution, depuis un poste configuré :

```sh
.venv/bin/python lancer.py --dm-pmp oui --mrn-dm MRN_COMPLET --operateur-dm "Nom de l’operateur"
```

Pour un lot multiple, répéter `--mrn-dm` pour **tous** les transits du lot. `--dm-pmp non` retire seulement le préfixe, avec une trace dans le journal. Le compteur numérique reste inchangé.

Redéposer ensuite une copie des sources archivées pour produire la version portant le préfixe. Les Word/PDF déjà générés ne sont pas modifiés à distance ; une retouche directe du Word ne met pas à jour le registre.

Sous Windows, remplacer `.venv/bin/python` par `.venv\Scripts\python.exe`. Dans une distribution figée, utiliser `app/ulix-ncts` (ou `app\ulix-ncts.exe`) à la place de `python lancer.py`.
