# Déploiement Linux avec données sur SMB

L'image Docker contient Python, Poppler, PaddleOCR, ses trois modèles CPU et le
gabarit de rendu. Le serveur Linux monte le partage SMB ; le conteneur reçoit
uniquement le dossier `data/` en lecture/écriture. Les identifiants SMB restent
sur l'hôte et ne sont jamais copiés dans l'image.

L'image vise un serveur Linux `x86_64` (`amd64`) et utilise l'OCR sur CPU.
Compose fixe cette architecture, y compris si la construction est lancée depuis
un Mac Apple Silicon. Sur ce Mac, les étapes de build qui exécutent PaddleOCR
passent par l'émulation et peuvent être lentes ; construire sur le serveur Linux
`amd64` reste le chemin le plus direct.

Pour lancer temporairement le conteneur sur le Mac avec le dossier `data/` du
projet, régler le `.env` local ainsi :

```dotenv
ULIX_DATA_DIR=./data
ULIX_REQUIRE_SMB=0
```

Puis exécuter `docker compose up -d --build`. Le contrôle CIFS est désactivé
uniquement pour cet usage local. Sur le serveur Linux, utiliser les réglages
SMB de l'étape 2 ci-dessous.

Le service démarre la surveillance automatiquement. Un seul conteneur doit
surveiller ce dossier `data/`.

## 1. Monter le partage SMB sur Linux

Installer le client CIFS et créer le point de montage :

```sh
sudo apt-get update
sudo apt-get install -y cifs-utils
sudo mkdir -p /mnt/ulix-ncts-data
```

Créer `/root/.smbcredentials` avec l'utilisateur SMB ayant accès en lecture et
écriture au partage :

```ini
username=UTILISATEUR_SMB
password=MOT_DE_PASSE_SMB
domain=DOMAINE
```

Protéger ce fichier, puis monter le partage qui contient directement les quatre
dossiers métier (`Archive`, `Annonces d'arrivées`, `Dépôts multiple`,
`Dépôts unique`) :

```sh
sudo chmod 600 /root/.smbcredentials
sudo mount -t cifs //SERVEUR/data /mnt/ulix-ncts-data \
  -o credentials=/root/.smbcredentials,vers=3.0,uid=1000,gid=1000,dir_mode=0770,file_mode=0660
```

Remplacer `SERVEUR`, `data`, `uid` et `gid` par les valeurs du site. Les UID et
GID du montage doivent correspondre à `PUID` et `PGID` dans le fichier `.env`.
Le compte SMB doit lui-même avoir les droits nécessaires côté serveur.

Pour conserver le montage après redémarrage, ajouter une entrée adaptée au site
dans `/etc/fstab`, avec au minimum `credentials=/root/.smbcredentials`,
`_netdev`, `vers=3.0`, `uid=…` et `gid=…`. Garder les identifiants dans le fichier
de credentials, jamais dans `/etc/fstab`.

## 2. Configurer le conteneur

Sur le serveur, placer le dépôt dans un répertoire local, puis préparer les
paramètres :

```sh
cp .env.example .env
chmod 600 .env
```

Dans `.env`, renseigner au minimum :

```dotenv
ULIX_DATA_DIR=/mnt/ulix-ncts-data
PUID=1000
PGID=1000
ULIX_REQUIRE_SMB=1
```

`ULIX_DATA_DIR` désigne la racine du partage montée sur l'hôte. Elle doit
contenir les quatre dossiers attendus. `PUID` et `PGID` doivent correspondre
aux options `uid` et `gid` du montage CIFS.

Les réglages IA et CargoWise sont facultatifs. Ils peuvent être conservés dans
`.env`; ils ne sont pas inclus dans l'image. Pour le repli IA distant, le
conteneur doit pouvoir joindre l'URL configurée.

## 3. Construire et démarrer

La construction a besoin d'un accès Internet pour installer les dépendances et
télécharger les modèles PaddleOCR. `ULIX_DATA_DIR` n'est utilisé qu'au
démarrage du conteneur, donc `docker compose build` fonctionne sans cette
variable. Les exécutions suivantes utilisent les modèles embarqués et ne les
téléchargent pas. Sur le serveur Linux, `uname -m` doit afficher `x86_64`.

```sh
docker compose build
docker compose up -d
docker compose logs -f ncts
```

Si l'image est construite sur un Mac Apple Silicon, Compose produit quand même
une image `linux/amd64`. Pour la transférer vers le serveur Linux :

```sh
# Sur le Mac
docker compose build
mkdir -p dist
docker save ulix-ncts:local | gzip > dist/ulix-ncts-linux-amd64.tar.gz
scp dist/ulix-ncts-linux-amd64.tar.gz UTILISATEUR@SERVEUR:/tmp/

# Sur le serveur Linux, avec le dépôt, .env et le partage SMB déjà monté
gzip -dc /tmp/ulix-ncts-linux-amd64.tar.gz | docker load
docker compose up -d --no-build
```

Le conteneur vérifie que `/opt/ulix-ncts/data` est bien un montage CIFS avant de
lancer l'application. Si le partage n'est pas monté, il s'arrête sans écrire
dans un dossier local de remplacement. Si le service a démarré avant le montage
SMB, monter le partage puis recréer le conteneur avec la commande indiquée plus
bas.

Pour arrêter le service :

```sh
docker compose down
```

Le traitement ponctuel reste possible avec les mêmes chemins de configuration,
par exemple :

```sh
docker compose run --rm ncts --unique --sans-couleur
```

## Accès et fichiers

- Le code et les modèles sont en lecture seule dans l'image.
- Seul `data/` est monté en lecture/écriture depuis le partage SMB.
- `.env` est monté en lecture seule pour les réglages ; il n'est pas dans l'image.
- Les fichiers temporaires OCR vont dans `/tmp` du conteneur.
- Le service n'expose aucun port réseau.
- Le conteneur tourne avec `PUID:PGID`, sans privilèges Linux supplémentaires.

Le premier lancement crée les sous-dossiers applicatifs manquants dans `data/`.
Le partage doit rester monté et disponible pendant l'analyse et l'archivage.
Monter le partage avant de démarrer Docker Compose. Après un démontage/remontage
manuel du partage, recréer le conteneur avec `docker compose up -d --force-recreate`
pour qu'il reprenne le nouveau montage.
