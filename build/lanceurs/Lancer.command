#!/bin/bash
# ULIX — annonce d'arrivée NCTS : traitement à la demande (version installée).
# Les dossiers de travail sont dans « ~/ULIX NCTS » (créés au premier lancement),
# sauf si ULIX_PROJET pointe ailleurs.
cd "$(dirname "$0")" || exit 1
export ULIX_PROJET="${ULIX_PROJET:-$HOME/ULIX NCTS}"
"./app/ulix-ncts" "$@"
CODE=$?
echo
if [ "$CODE" = 0 ]; then
    echo "Traitement terminé. Les annonces sont dans « $ULIX_PROJET/data/Annonces d'arrivées »."
else
    echo "Le traitement s'est arrêté avec le code $CODE (voir le message ci-dessus)."
fi
read -r -p "Appuyez sur Entrée pour fermer…" _
exit $CODE
