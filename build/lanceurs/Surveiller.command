#!/bin/bash
# ULIX — annonce d'arrivée NCTS : surveillance automatique des dépôts (version installée).
# Laisser cette fenêtre ouverte : déposer un PDF dans « ~/ULIX NCTS/Dépôts unique »
# ou « …/Dépôts multiple » suffit, l'annonce se génère seule.
cd "$(dirname "$0")" || exit 1
export ULIX_PROJET="${ULIX_PROJET:-$HOME/ULIX NCTS}"
exec "./app/ulix-ncts" --surveiller "$@"
