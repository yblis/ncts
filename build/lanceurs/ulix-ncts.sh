#!/bin/sh
# ULIX — annonce d'arrivée NCTS : lanceur installé par le paquet .deb.
# Le programme vit dans /opt/ulix-ncts ; les dossiers de travail de l'utilisateur
# dans « ~/ULIX NCTS » (créés au premier lancement), sauf ULIX_PROJET.
export ULIX_PROJET="${ULIX_PROJET:-$HOME/ULIX NCTS}"
exec /opt/ulix-ncts/ulix-ncts "$@"
